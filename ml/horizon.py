"""Бектест обох горизонтів фінальною конфігурацією.

«сьогодні» — вікно, що починається о 12:00 сьогодні (lag=1).
«завтра»   — наступне вікно (lag=2): на відсічці доба d-1 ще триває.
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "ml")
from final import prepare, fit_ensemble, predict, TARGETS
from train import metrics

rows = []
for lag, name in ((1, "сьогодні"), (2, "завтра")):
    d, feats = prepare(lag=lag)
    split = int(len(d) * 0.8)
    tr, te = d.iloc[:split], d.iloc[split:]
    for label, target in TARGETS.items():
        top, models, cvs = fit_ensemble(tr, feats, target)
        y = te[target].values
        prior = tr[target].mean()
        p_ens = predict(models, te[feats])
        p_clim = np.clip(np.nan_to_num(te[f"{target}_m30"].values, nan=prior), .02, .98)
        p_pers = np.nan_to_num(np.where(te[f"{target}_l1"].values == 1,
                    tr.loc[tr[f"{target}_l1"] == 1, target].mean(),
                    tr.loc[tr[f"{target}_l1"] == 0, target].mean()), nan=prior)
        rows.append(metrics(y, p_ens, f"{name} / {label}: медіана top-5"))
        rows.append(metrics(y, p_clim, f"{name} / {label}: [база] кліматологія"))
        rows.append(metrics(y, p_pers, f"{name} / {label}: [база] персистенція"))
        print(f"{name}/{label}: {list(cvs)}")

r = pd.DataFrame(rows).set_index("модель")[["log-loss", "Brier", "ROC-AUC", "PR-AUC"]]
print("\n" + r.to_string(float_format=lambda v: f"{v:.4f}"))
r.to_csv("ml/results_horizons.csv")
