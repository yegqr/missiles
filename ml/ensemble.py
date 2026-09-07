"""Ансамблі: чи краще брати медіану кількох моделей, ніж одну «найкращу».

Чесність порівняння тут головна. Одиночну модель у продакшені обирають за
валідацією всередині train, а не за тестом — інакше тест уже використано для
відбору і перестав бути тестом. Тому базою для порівняння є best-by-CV.
Best-by-test наведено окремо і підписано як оракул: це недосяжна верхня межа.
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "ml")
import dataset
from train import zoo, metrics, baselines, CV
from sklearn.model_selection import GridSearchCV

TARGETS = [("y_attacked_i", "ЗАДАЧА 1: обстріл у вікні 12:00 → 12:00"),
           ("S_ge1", "ЗАДАЧА 2: значуща тривога (>= 30 хв)"),
           ("S_ge3", "ЗАДАЧА 3: масована атака")]


def fit_all(tr, te, feats, target):
    """Навчити весь зоопарк, повернути CV-оцінки і ймовірності на тесті."""
    cv, P = {}, {}
    for name, (pipe, grid) in zoo().items():
        gs = GridSearchCV(pipe, grid, cv=CV, scoring="neg_log_loss", n_jobs=-1)
        gs.fit(tr[feats], tr[target].values)
        cv[name] = -gs.best_score_
        P[name] = gs.predict_proba(te[feats])[:, 1]
    return pd.Series(cv).sort_values(), pd.DataFrame(P)


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def prior_shift(p, pi_new, pi_old):
    """Перенос базової частки: train навчений на pi_old, а зараз режим pi_new.

    pi_new береться з ковзного середнього за 30 діб ДО відсічки — це відомо
    на момент прогнозу, витоку немає.
    """
    z = logit(p) + logit(pi_new) - logit(np.full_like(p, pi_old))
    return 1 / (1 + np.exp(-z))


def run(d, feats, target, title):
    print(f"\n{'='*96}\n{title}\n{'='*96}")
    split = int(len(d) * 0.8)
    tr, te = d.iloc[:split], d.iloc[split:]
    y = te[target].values
    cv, P = fit_all(tr, te, feats, target)
    print("Рейтинг за CV усередині train (за ним і треба обирати):")
    for i, (n, v) in enumerate(cv.items(), 1):
        print(f"  {i:2d}. {n:24s} CV={v:.4f}")

    rows = baselines(tr, te, target)
    bcv = cv.index[0]
    rows.append(metrics(y, P[bcv].values, f"одиночна, обрана за CV: {bcv}"))

    for k in (3, 5, 7, 10):
        top = list(cv.index[:k])
        rows.append(metrics(y, P[top].median(axis=1).values, f"МЕДІАНА top-{k} за CV"))
        rows.append(metrics(y, P[top].mean(axis=1).values, f"середнє top-{k} за CV"))
    top5 = list(cv.index[:5])
    rows.append(metrics(y, 1 / (1 + np.exp(-logit(P[top5]).mean(axis=1).values)),
                        "середнє логітів top-5"))
    rows.append(metrics(y, P[top5].rank(axis=0, pct=True).mean(axis=1).values,
                        "усереднення рангів top-5 (лише ранжування)"))

    # медіана top-5 + корекція базової частки за ковзним вікном
    pi_old = tr[target].mean()
    pi_new = np.clip(te[f"{target}_m30"].values, 0.02, 0.98)
    med5 = P[top5].median(axis=1).values
    rows.append(metrics(y, prior_shift(med5, pi_new, pi_old),
                        "МЕДІАНА top-5 + корекція частки (30 діб)"))

    rows.append(metrics(y, P[P.apply(lambda c: metrics(y, c.values, "")["log-loss"]).idxmin()].values,
                        "[оракул] найкраща за ТЕСТОМ — недосяжна"))

    res = pd.DataFrame(rows).set_index("модель")[
        ["log-loss", "Brier", "ROC-AUC", "PR-AUC", "acc@.5", "F1@.5"]]
    print("\nРЕЗУЛЬТАТИ НА ТЕСТІ:\n")
    print(res.sort_values("log-loss").to_string(float_format=lambda v: f"{v:.4f}"))
    return res


if __name__ == "__main__":
    d, blocks = dataset.build(weather=True)
    d = dataset.add_labels(d, int(len(d) * 0.8))
    for t, _ in TARGETS:
        s = d[t].shift(1)
        d[f"{t}_l1"] = s
        d[f"{t}_m30"] = s.rolling(30, min_periods=10).mean()
    feats = blocks["A_prev"] + blocks["B_hist"] + blocks["C_calendar"] + blocks["D_weather"]
    for t, title in TARGETS:
        run(d, feats, t, title).to_csv(f"ml/results_ensemble_{t}.csv")
