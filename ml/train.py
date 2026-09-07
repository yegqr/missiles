"""Воркфлоу навчання: хронологічний 80/20, добір гіперпараметрів на
TimeSeriesSplit усередині train, оцінка на недоторканому test.

Ніякого shuffle і ніякого KFold: сусідні доби корельовані, перемішування
дає завищену оцінку — це data leakage у чистому вигляді.
"""
import sys, warnings
import numpy as np
import pandas as pd

sys.path.insert(0, "ml")
import dataset

from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import (RandomForestClassifier, BaggingClassifier,
                              HistGradientBoostingClassifier, StackingClassifier)
from sklearn.neural_network import MLPClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (log_loss, brier_score_loss, roc_auc_score,
                             average_precision_score, accuracy_score, f1_score,
                             confusion_matrix)
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")
RS = 0
CV = TimeSeriesSplit(n_splits=5)


def num(**kw):
    return Pipeline([("imp", SimpleImputer(strategy="median")), *kw.get("steps", [])])


def zoo():
    """Моделі з програми курсу. Кожна — (pipeline, сітка гіперпараметрів)."""
    imp = ("imp", SimpleImputer(strategy="median"))
    sc = ("sc", StandardScaler())
    return {
        "kNN": (Pipeline([imp, sc, ("m", KNeighborsClassifier())]),
                {"m__n_neighbors": [15, 31, 61, 101], "m__weights": ["uniform", "distance"]}),
        "LogReg L2 (ridge)": (Pipeline([imp, sc, ("m", LogisticRegression(max_iter=4000))]),
                {"m__C": [0.01, 0.03, 0.1, 0.3, 1.0]}),
        "LogReg L1 (lasso)": (Pipeline([imp, sc, ("m", LogisticRegression(penalty="l1", solver="liblinear", max_iter=4000))]),
                {"m__C": [0.01, 0.03, 0.1, 0.3, 1.0]}),
        "PCA(10) + LogReg": (Pipeline([imp, sc, ("p", PCA(random_state=RS)), ("m", LogisticRegression(max_iter=4000))]),
                {"p__n_components": [5, 10, 20], "m__C": [0.03, 0.1, 0.3, 1.0]}),
        "Decision Tree": (Pipeline([imp, ("m", DecisionTreeClassifier(random_state=RS))]),
                {"m__max_depth": [2, 3, 4, 6], "m__min_samples_leaf": [10, 20, 40]}),
        "Bagging (дерева)": (Pipeline([imp, ("m", BaggingClassifier(
                    DecisionTreeClassifier(random_state=RS), n_estimators=300, random_state=RS))]),
                {"m__estimator__max_depth": [4, 8, None], "m__estimator__min_samples_leaf": [5, 15]}),
        "Random Forest": (Pipeline([imp, ("m", RandomForestClassifier(n_estimators=500, random_state=RS, n_jobs=-1))]),
                {"m__max_depth": [4, 8, None], "m__min_samples_leaf": [4, 8, 16],
                 "m__max_features": ["sqrt", 0.5]}),
        "HistGradientBoosting": (Pipeline([("m", HistGradientBoostingClassifier(random_state=RS))]),
                {"m__max_depth": [2, 3], "m__learning_rate": [0.02, 0.05],
                 "m__max_iter": [200, 400], "m__l2_regularization": [1.0, 10.0]}),
        "XGBoost": (Pipeline([("m", XGBClassifier(n_estimators=400, random_state=RS,
                    eval_metric="logloss", tree_method="hist"))]),
                {"m__max_depth": [2, 3], "m__learning_rate": [0.02, 0.05],
                 "m__subsample": [0.7, 1.0], "m__reg_lambda": [1.0, 10.0]}),
        "MLP (weight decay)": (Pipeline([imp, sc, ("m", MLPClassifier(max_iter=3000, random_state=RS,
                    early_stopping=False))]),
                {"m__hidden_layer_sizes": [(16,), (32, 16)], "m__alpha": [0.1, 1.0, 10.0]}),
    }


def metrics(y, p, name):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    yh = (p > 0.5).astype(int)
    return {
        "модель": name,
        "log-loss": log_loss(y, p),
        "Brier": brier_score_loss(y, p),
        "ROC-AUC": roc_auc_score(y, p) if len(np.unique(y)) > 1 else np.nan,
        "PR-AUC": average_precision_score(y, p) if len(np.unique(y)) > 1 else np.nan,
        "acc@.5": accuracy_score(y, yh),
        "F1@.5": f1_score(y, yh, zero_division=0),
    }


def baselines(tr, te, target):
    """Планки, які треба перебити. Без них будь-яка метрика беззмістовна."""
    out = []
    prior = tr[target].mean()
    y = te[target].values
    out.append(metrics(y, np.full(len(y), prior), f"[база] завжди «так» (p={prior:.2f})"))
    # персистенція: ймовірність = емпірична частка за станом учора, оцінена на train
    prev_tr, prev_te = tr[f"{target}_l1"], te[f"{target}_l1"]
    if prev_tr is not None and prev_tr.notna().any():
        p1 = tr.loc[prev_tr == 1, target].mean()
        p0 = tr.loc[prev_tr == 0, target].mean()
        p = np.where(prev_te.values == 1, p1, p0)
        out.append(metrics(y, np.nan_to_num(p, nan=prior), "[база] персистенція (як учора)"))
    clim = te[f"{target}_m30"].values
    out.append(metrics(y, np.clip(np.nan_to_num(clim, nan=prior), 0.02, 0.98),
                       "[база] кліматологія 30 діб"))
    return out


def run_target(d, feats, target, title, add_stack=True):
    print(f"\n{'='*100}\n{title}\n{'='*100}")
    n = len(d)
    split = int(n * 0.8)
    tr, te = d.iloc[:split], d.iloc[split:]
    print(f"train: {tr.raid_day.min().date()} → {tr.raid_day.max().date()}  ({len(tr)} діб, "
          f"позитивів {tr[target].mean():.1%})")
    print(f"test:  {te.raid_day.min().date()} → {te.raid_day.max().date()}  ({len(te)} діб, "
          f"позитивів {te[target].mean():.1%})")
    print(f"ознак: {len(feats)}\n")

    Xtr, ytr = tr[feats], tr[target].values
    Xte, yte = te[feats], te[target].values

    rows = baselines(tr, te, target)
    best = {}
    for name, (pipe, grid) in zoo().items():
        gs = GridSearchCV(pipe, grid, cv=CV, scoring="neg_log_loss", n_jobs=-1, refit=True)
        gs.fit(Xtr, ytr)
        p = gs.predict_proba(Xte)[:, 1]
        m = metrics(yte, p, name)
        m["CV log-loss"] = -gs.best_score_
        rows.append(m)
        best[name] = gs.best_estimator_
        print(f"  {name:24s} CV={-gs.best_score_:.4f}  {gs.best_params_}")

    # Стекінг руками: StackingClassifier усередині робить cross_val_predict,
    # а він вимагає розбиття-партиції, чого TimeSeriesSplit не дає. Тому мета-модель
    # учиться на ХВОСТІ train (останні 20%), бази — на голові. Хронологію збережено.
    if add_stack:
        base_names = ["LogReg L2 (ridge)", "Random Forest", "HistGradientBoosting", "XGBoost"]
        cut = int(len(tr) * 0.8)
        trA, trB = tr.iloc[:cut], tr.iloc[cut:]
        from sklearn.base import clone
        Z_tr, Z_te = [], []
        for bn in base_names:
            mA = clone(best[bn]).fit(trA[feats], trA[target].values)
            Z_tr.append(mA.predict_proba(trB[feats])[:, 1])
            Z_te.append(best[bn].predict_proba(Xte)[:, 1])   # база вже навчена на всьому train
        Z_tr, Z_te = np.column_stack(Z_tr), np.column_stack(Z_te)
        meta = LogisticRegression(max_iter=2000).fit(Z_tr, trB[target].values)
        rows.append(metrics(yte, meta.predict_proba(Z_te)[:, 1], "Stacking (LR+RF+GB+XGB)"))
        rows.append(metrics(yte, Z_te.mean(axis=1), "Blending (просте середнє)"))

        cal = CalibratedClassifierCV(best["Random Forest"], method="isotonic", cv=CV)
        cal.fit(Xtr, ytr)
        rows.append(metrics(yte, cal.predict_proba(Xte)[:, 1], "Random Forest + isotonic"))

    res = pd.DataFrame(rows).set_index("модель")
    cols = ["CV log-loss", "log-loss", "Brier", "ROC-AUC", "PR-AUC", "acc@.5", "F1@.5"]
    res = res.reindex(columns=cols)
    print("\nРЕЗУЛЬТАТИ НА ТЕСТІ (упорядковано за log-loss; менше = краще):\n")
    print(res.sort_values("log-loss").to_string(float_format=lambda v: f"{v:.4f}"))
    return res, best, (tr, te)


def ablation(d, blocks, target, model_name="XGBoost"):
    """Чи справді потрібні блоки ознак. Той самий добір, різні набори колонок."""
    print(f"\n{'-'*100}\nАБЛЯЦІЯ БЛОКІВ ОЗНАК ({model_name}, ціль {target})\n{'-'*100}")
    sets = {
        "A (стан за d-1)": blocks["A_prev"],
        "C (календар)": blocks["C_calendar"],
        "A+C": blocks["A_prev"] + blocks["C_calendar"],
        "A+B+C (історія)": blocks["A_prev"] + blocks["B_hist"] + blocks["C_calendar"],
        "A+B+C+D (+погода)": blocks["A_prev"] + blocks["B_hist"] + blocks["C_calendar"] + blocks["D_weather"],
    }
    split = int(len(d) * 0.8)
    tr, te = d.iloc[:split], d.iloc[split:]
    pipe, grid = zoo()[model_name]
    rows = []
    for nm, fs in sets.items():
        gs = GridSearchCV(pipe, grid, cv=CV, scoring="neg_log_loss", n_jobs=-1)
        gs.fit(tr[fs], tr[target].values)
        m = metrics(te[target].values, gs.predict_proba(te[fs])[:, 1], nm)
        m["ознак"] = len(fs)
        rows.append(m)
    r = pd.DataFrame(rows).set_index("модель")[["ознак", "log-loss", "Brier", "ROC-AUC", "PR-AUC"]]
    print(r.to_string(float_format=lambda v: f"{v:.4f}"))
    return r


def importances(model, feats, k=15):
    m = model[-1] if hasattr(model, "steps") else model
    if hasattr(m, "feature_importances_"):
        s = pd.Series(m.feature_importances_, index=feats).sort_values(ascending=False)
        print(f"\nНАЙВАЖЛИВІШІ ОЗНАКИ (top-{k}):")
        for n, v in s.head(k).items():
            print(f"   {v:6.3f}  {n}")


def threshold_report(d, model, feats, target):
    """Поріг — це рішення про ціну помилки, а не властивість моделі."""
    split = int(len(d) * 0.8)
    te = d.iloc[split:]
    p = model.predict_proba(te[feats])[:, 1]
    y = te[target].values
    print("\nПОРІГ РІШЕННЯ (тест):")
    print(f"   {'поріг':>6} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}  {'precision':>9} {'recall':>7}")
    for t in (0.3, 0.5, 0.6, 0.7, 0.8, 0.9):
        yh = (p > t).astype(int)
        tn, fp, fn, tp = confusion_matrix(y, yh, labels=[0, 1]).ravel()
        prec = tp / (tp + fp) if tp + fp else float("nan")
        rec = tp / (tp + fn) if tp + fn else float("nan")
        print(f"   {t:6.2f} {tp:4d} {fp:4d} {fn:4d} {tn:4d}  {prec:9.3f} {rec:7.3f}")


def strategies(d, feats, target, model_name="XGBoost"):
    """Різні СТРАТЕГІЇ НАВЧАННЯ на тих самих ознаках.

    Причина: частка позитивів у train 67%, у тесті 82% — розподіл поїхав.
    Модель, що однаково важить 2024 і 2026 роки, вчиться на застарілому режимі.
    """
    print(f"\n{'-'*100}\nСТРАТЕГІЇ НАВЧАННЯ ({model_name}, ціль {target})\n{'-'*100}")
    split = int(len(d) * 0.8)
    tr, te = d.iloc[:split], d.iloc[split:]
    Xte, yte = te[feats], te[target].values
    pipe, grid = zoo()[model_name]
    rows = []

    def fit_eval(name, sub, w=None):
        gs = GridSearchCV(pipe, grid, cv=CV, scoring="neg_log_loss", n_jobs=-1)
        kw = {}
        if w is not None:
            kw["m__sample_weight"] = w
        gs.fit(sub[feats], sub[target].values, **kw)
        rows.append(metrics(yte, gs.predict_proba(Xte)[:, 1], name))

    fit_eval("вікно: усе (760 діб)", tr)
    fit_eval("вікно: останні 365 діб", tr.iloc[-365:])
    fit_eval("вікно: останні 180 діб", tr.iloc[-180:])
    for hl in (90, 180, 365):
        age = (tr["raid_day"].max() - tr["raid_day"]).dt.days.values
        fit_eval(f"вага за свіжістю (напівперіод {hl} діб)", tr, w=0.5 ** (age / hl))

    r = pd.DataFrame(rows).set_index("модель")[["log-loss", "Brier", "ROC-AUC", "PR-AUC", "acc@.5"]]
    print(r.to_string(float_format=lambda v: f"{v:.4f}"))
    return r


def regression(d, feats):
    """Регресійна постановка: скільки хвилин тривог буде у вікні.

    Ціль log1p(хвилини) — розподіл важкохвостий, у сирих хвилинах RMSE
    визначається кількома найгіршими ночами і модель вчиться тільки на них.
    """
    from sklearn.linear_model import Ridge, Lasso
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.dummy import DummyRegressor
    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

    print(f"\n{'-'*100}\nРЕГРЕСІЯ: тривалість тривог у вікні (log1p хвилин)\n{'-'*100}")
    split = int(len(d) * 0.8)
    tr, te = d.iloc[:split], d.iloc[split:]
    ytr = np.log1p(tr["y_alert_minutes"].values)
    yte = np.log1p(te["y_alert_minutes"].values)
    imp = ("imp", SimpleImputer(strategy="median"))
    sc = ("sc", StandardScaler())
    models = {
        "[база] середнє train": (Pipeline([imp, ("m", DummyRegressor())]), {}),
        "Ridge": (Pipeline([imp, sc, ("m", Ridge())]), {"m__alpha": [1, 10, 100, 1000]}),
        "Lasso": (Pipeline([imp, sc, ("m", Lasso(max_iter=10000))]), {"m__alpha": [0.001, 0.01, 0.1]}),
        "Random Forest": (Pipeline([imp, ("m", RandomForestRegressor(n_estimators=500, random_state=RS, n_jobs=-1))]),
                          {"m__min_samples_leaf": [4, 8, 16], "m__max_depth": [4, 8, None]}),
    }
    rows = []
    for nm, (pipe, grid) in models.items():
        gs = GridSearchCV(pipe, grid or {"m__fit_intercept" if nm.startswith("[") else "m__alpha": [True] if nm.startswith("[") else [1]},
                          cv=CV, scoring="neg_mean_squared_error", n_jobs=-1) if grid else pipe
        if grid:
            gs.fit(tr[feats], ytr); pred = gs.predict(te[feats])
        else:
            pipe.fit(tr[feats], ytr); pred = pipe.predict(te[feats])
        rows.append({"модель": nm,
                     "RMSE (log)": float(np.sqrt(mean_squared_error(yte, pred))),
                     "MAE (log)": float(mean_absolute_error(yte, pred)),
                     "R2": float(r2_score(yte, pred)),
                     "RMSE (хв)": float(np.sqrt(mean_squared_error(np.expm1(yte), np.expm1(pred)))),
                     "MAE (хв)": float(mean_absolute_error(np.expm1(yte), np.expm1(pred)))})
    r = pd.DataFrame(rows).set_index("модель")
    print(r.to_string(float_format=lambda v: f"{v:.3f}"))
    return r


if __name__ == "__main__":
    d, blocks = dataset.build(weather=True)
    d = dataset.add_labels(d, int(len(d) * 0.8))
    for t in ("y_attacked_i", "S_ge1", "S_ge2", "S_ge3"):
        s_ = d[t].shift(1)
        d[f"{t}_l1"] = s_
        d[f"{t}_m30"] = s_.rolling(30, min_periods=10).mean()
    print("Пороги шкали з train-розподілу:", d.attrs["thresholds"])
    print("Розподіл S:", d["S"].value_counts().sort_index().to_dict())

    feats = blocks["A_prev"] + blocks["B_hist"] + blocks["C_calendar"] + blocks["D_weather"]

    res1, best1, _ = run_target(d, feats, "y_attacked_i",
        "ЗАДАЧА 1: чи буде обстріл Києва у вікні 12:00 → 12:00 (бінарна)")
    # S>=2 за побудовою збігається з y_attacked (лейбл «атака» = треки > 0),
    # тому друга задача — інша межа шкали: чи буде взагалі значуща тривога
    res2, best2, _ = run_target(d, feats, "S_ge1",
        "ЗАДАЧА 2: P(S>=1) — значуща тривога (>= 30 хв) у вікні")
    res3, best3, _ = run_target(d, feats, "S_ge3",
        "ЗАДАЧА 3: P(S>=3) — масована атака")

    for nm, r in (("attacked", res1), ("S_ge1", res2), ("S_ge3", res3)):
        r.to_csv(f"ml/results_{nm}.csv")

    strategies(d, feats, "y_attacked_i").to_csv("ml/results_strategies.csv")
    strategies(d, feats, "S_ge3", model_name="Random Forest").to_csv("ml/results_strategies_sge3.csv")
    regression(d, feats).to_csv("ml/results_regression.csv")
    ablation(d, blocks, "y_attacked_i").to_csv("ml/results_ablation_attacked.csv")
    ablation(d, blocks, "S_ge3").to_csv("ml/results_ablation_sge3.csv")

    print(f"\n{'-'*100}\nРОЗБІР ПЕРЕМОЖЦЯ\n{'-'*100}")
    importances(best1["XGBoost"], feats)
    threshold_report(d, best1["XGBoost"], feats, "y_attacked_i")
    print("\nЗадача 3 (масована атака):")
    importances(best3["Random Forest"], feats)
    threshold_report(d, best3["Random Forest"], feats, "S_ge3")
