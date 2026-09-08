"""Чесний бейк-оф: чи є взагалі ML, кращий за середнє за 30 діб.

Питання, на яке відповідає цей файл: «модель програє кліматології тому, що
задача така, чи тому, що модель у нас слабка?» Щоб відповідь щось означала,
потрібні три речі, яких не було в ml/train.py:

  1. Ходьба вперед (walk-forward), а не один зріз train/test. Модель
     перенавчається кожні REFIT діб на всьому, що відомо на той момент,
     і прогнозує наступний блок. Це рівно те, що робить продакшн.
  2. Однакові умови для всіх кандидатів: одні й ті самі доби, один і той
     самий момент відсічки, жодного підбору по тесту.
  3. Довірчі інтервали різниці. На 180 добах різниця 0.004 у log-loss —
     це шум, і без бутстрепу її прийматимуть за перемогу.

Запуск:  .venv/bin/python ml/bakeoff.py [--refit 14] [--start 2026-03-08]
"""
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, "ml")
from final import prepare
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")
RS = 0
TARGET = "y_attacked_i"
CLIP = (0.02, 0.98)
CLIM_WINDOWS = (7, 14, 30, 60, 90)


def models():
    """Фіксовані розумні гіперпараметри, без сітки.

    Сітка всередині ходьби вперед коштувала б годин і додала б ще один
    спосіб підігнатись. Ці значення взяті з CV попереднього етапу і далі
    не чіпаються — так кандидати чесно порівнюються між собою.
    """
    imp = ("imp", SimpleImputer(strategy="median"))
    sc = ("sc", StandardScaler())
    return {
        "LogReg L2": Pipeline([imp, sc, ("m", LogisticRegression(C=0.1, max_iter=4000))]),
        "Random Forest": Pipeline([imp, ("m", RandomForestClassifier(
            n_estimators=500, min_samples_leaf=8, max_features="sqrt",
            random_state=RS, n_jobs=-1))]),
        "HistGB": Pipeline([imp, ("m", HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.03, max_iter=400, min_samples_leaf=20,
            l2_regularization=1.0, random_state=RS))]),
        "XGBoost": Pipeline([imp, ("m", XGBClassifier(
            n_estimators=400, max_depth=3, learning_rate=0.03, subsample=0.8,
            colsample_bytree=0.8, reg_lambda=2.0, eval_metric="logloss",
            random_state=RS, n_jobs=-1))]),
    }


def walk_forward(d, feats, start, refit):
    """Повертає DataFrame: доба, факт і колонка ймовірностей на кандидата."""
    d = d[d.y_known].reset_index(drop=True)
    # Кліматології різної довжини. Рахуються ПІСЛЯ відсіву непозначених діб —
    # рівно так, як їх рахує ml/final.prepare, інакше кандидат «кліматологія 30»
    # у бейк-офі означав би не те, що публікується.
    for w in CLIM_WINDOWS:
        d[f"clim{w}"] = (d[TARGET].shift(1)
                         .rolling(w, min_periods=max(5, w // 3)).mean())
    test_idx = d.index[d.raid_day >= start]
    if not len(test_idx):
        raise SystemExit(f"немає тестових діб з {start}")
    rows = []
    blocks = range(test_idx[0], test_idx[-1] + 1, refit)
    for bi, b0 in enumerate(blocks, 1):
        b1 = min(b0 + refit, test_idx[-1] + 1)
        tr, te = d.iloc[:b0], d.iloc[b0:b1]
        print(f"  блок {bi}/{len(blocks)}: навчання на {len(tr)} добах "
              f"→ прогноз {te.raid_day.iloc[0].date()}…{te.raid_day.iloc[-1].date()}",
              flush=True)
        out = {"raid_day": te.raid_day.values, "y": te[TARGET].values}
        prior = tr[TARGET].mean()
        # кліматології різної довжини рахуються з уже зсунутих колонок
        for w in CLIM_WINDOWS:
            out[f"кліматологія {w}"] = np.clip(
                np.nan_to_num(te[f"clim{w}"].values, nan=prior), *CLIP)
        P = []
        for name, m in models().items():
            m.fit(tr[feats], tr[TARGET].values)
            p = np.clip(m.predict_proba(te[feats])[:, 1], *CLIP)
            out[name] = p
            P.append(p)
        out["Медіана 4 моделей"] = np.median(np.column_stack(P), axis=1)
        rows.append(pd.DataFrame(out))
    return pd.concat(rows, ignore_index=True)


def block_bootstrap(loss_a, loss_b, block=7, reps=5000, seed=0):
    """Довірчий інтервал різниці середніх втрат для корельованого ряду."""
    rng = np.random.default_rng(seed)
    diff = loss_a - loss_b
    n = len(diff)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, max(1, n - block + 1), size=(reps, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(reps, -1)[:, :n]
    samples = diff[np.clip(idx, 0, n - 1)].mean(axis=1)
    return np.percentile(samples, [2.5, 97.5])


def main():
    refit = int(sys.argv[sys.argv.index("--refit") + 1]) if "--refit" in sys.argv else 14
    start = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else "2026-03-08"
    d, feats = prepare(lag=1)
    print(f"Бейк-оф: ходьба вперед з {start}, перенавчання кожні {refit} діб, "
          f"{len(feats)} ознак\n")
    R = walk_forward(d, feats, pd.Timestamp(start), refit)
    y = R["y"].values
    cands = [c for c in R.columns if c not in ("raid_day", "y")]
    ref = "кліматологія 30"
    ll = {c: -(y * np.log(R[c]) + (1 - y) * np.log(1 - R[c])) for c in cands}

    rows = []
    for c in cands:
        lo, hi = block_bootstrap(ll[c].values, ll[ref].values)
        rows.append({
            "кандидат": c,
            "log-loss": log_loss(y, R[c]),
            "Brier": brier_score_loss(y, R[c]),
            "ROC-AUC": roc_auc_score(y, R[c]) if len(np.unique(y)) > 1 else np.nan,
            "Δ до кліматології": ll[c].mean() - ll[ref].mean(),
            "95% ДІ різниці": f"[{lo:+.4f}, {hi:+.4f}]",
            "краще значуще": "так" if hi < 0 else "ні",
        })
    T = pd.DataFrame(rows).sort_values("log-loss").set_index("кандидат")
    print(f"\n{len(y)} тестових діб, атак {y.mean():.1%}\n")
    print(T.to_string(float_format=lambda v: f"{v:.4f}"))
    R.to_csv("ml/bakeoff_preds.csv", index=False)
    T.to_csv("ml/bakeoff.csv")
    print("\nЗаписано ml/bakeoff.csv і ml/bakeoff_preds.csv")
    print("\nЧитати так: «краще значуще = так» означає, що верхня межа довірчого "
          "інтервалу різниці нижча за нуль,\nтобто кандидат виграє в кліматології "
          "30 діб не випадково. Усе інше — нічия.")


if __name__ == "__main__":
    main()
