"""Перевірка правила «корекція базової частки вмикається лише для S_ge3».

Правило народилося з таблиці на тесті, тому фіксувати його одразу не можна.
Перевіряємо на валідаційному зрізі ВСЕРЕДИНІ train: останні 160 діб train,
навчання — на перших 600. Тест не торкаємо взагалі.
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "ml")
import dataset
from train import zoo, metrics, CV
from ensemble import logit, prior_shift
from sklearn.model_selection import GridSearchCV

d, blocks = dataset.build(weather=True)
d = dataset.add_labels(d, int(len(d) * 0.8))
for t in ("y_attacked_i", "S_ge1", "S_ge3"):
    s = d[t].shift(1)
    d[f"{t}_l1"] = s
    d[f"{t}_m30"] = s.rolling(30, min_periods=10).mean()

feats = blocks["A_prev"] + blocks["B_hist"] + blocks["C_calendar"] + blocks["D_weather"]
split = int(len(d) * 0.8)
train_all = d.iloc[:split]
inner = 600
fit, val = train_all.iloc[:inner], train_all.iloc[inner:]
print(f"навчання: {fit.raid_day.min().date()} → {fit.raid_day.max().date()} ({len(fit)})")
print(f"валідація: {val.raid_day.min().date()} → {val.raid_day.max().date()} ({len(val)})")

for target in ("y_attacked_i", "S_ge1", "S_ge3"):
    cv, P = {}, {}
    for name, (pipe, grid) in zoo().items():
        gs = GridSearchCV(pipe, grid, cv=CV, scoring="neg_log_loss", n_jobs=-1)
        gs.fit(fit[feats], fit[target].values)
        cv[name] = -gs.best_score_
        P[name] = gs.predict_proba(val[feats])[:, 1]
    cv = pd.Series(cv).sort_values()
    P = pd.DataFrame(P)
    y = val[target].values
    top5 = list(cv.index[:5])
    med = P[top5].median(axis=1).values
    pi_old, pi_new = fit[target].mean(), np.clip(val[f"{target}_m30"].values, 0.02, 0.98)
    rows = [
        metrics(y, med, "медіана top-5 БЕЗ корекції"),
        metrics(y, prior_shift(med, pi_new, pi_old), "медіана top-5 + КОРЕКЦІЯ"),
        metrics(y, P[cv.index[0]].values, f"одиночна за CV ({cv.index[0]})"),
        metrics(y, np.clip(np.nan_to_num(val[f"{target}_m30"].values, nan=pi_old), .02, .98),
                "[база] кліматологія 30 діб"),
    ]
    r = pd.DataFrame(rows).set_index("модель")[["log-loss", "Brier", "ROC-AUC", "PR-AUC", "F1@.5"]]
    print(f"\n--- {target}: частка у fit {pi_old:.1%}, у валідації {y.mean():.1%} ---")
    print(r.to_string(float_format=lambda v: f"{v:.4f}"))
