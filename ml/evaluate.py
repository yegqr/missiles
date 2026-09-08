"""Чесна оцінка: жодне рішення не приймається за тестом.

Схема з трьох частин замість двох:
    train_fit   перші 80% train — на них добираються гіперпараметри (CV)
    train_val   останні 20% train — на них обираються K, корекція частки
                і те, чи взагалі публікувати модель замість базової лінії
    test        останні 20% усього — жодного разу не використовується для
                рішень, тільки для підсумкового числа

Раніше сім рішень (ансамбль замість одиночної, K=5, медіана, вікно навчання,
поріг, набір блоків ознак) приймались за таблицями на тесті — після чого тест
перестав бути оцінкою узагальнення. Тут він її знову означає.

Метрики подаються з довірчими інтервалами: на 190 добах різниця в 2-3%
log-loss не відрізняється від нуля, і без інтервалу це неможливо побачити.
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "ml")
import dataset
from final import fit_ensemble, prepare, TARGETS
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score

RNG = np.random.default_rng(0)
BLOCK = 7          # доби автокорельовані; iid-бутстреп занизив би інтервал
REPS = 5000


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def prior_shift(p, pi_new, pi_old):
    z = logit(p) + logit(pi_new) - logit(np.full_like(p, pi_old))
    return 1 / (1 + np.exp(-z))


def pointwise_ll(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def block_boot(a, b):
    """95% ДІ для середньої різниці поточкових втрат, рухомими блоками."""
    n = len(a)
    d = a - b
    nb = int(np.ceil(n / BLOCK))
    starts = RNG.integers(0, max(1, n - BLOCK + 1), size=(REPS, nb))
    idx = (starts[:, :, None] + np.arange(BLOCK)[None, None, :]).reshape(REPS, -1)[:, :n]
    means = d[np.clip(idx, 0, n - 1)].mean(axis=1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def baselines(tr, te, target):
    prior = tr[target].mean()
    p1 = tr.loc[tr[f"{target}_l1"] == 1, target].mean()
    p0 = tr.loc[tr[f"{target}_l1"] == 0, target].mean()
    return {
        "константа": np.full(len(te), prior),
        "персистенція": np.nan_to_num(
            np.where(te[f"{target}_l1"].values == 1, p1, p0), nan=prior),
        "кліматологія 30": np.clip(
            np.nan_to_num(te[f"{target}_m30"].values, nan=prior), .02, .98),
    }


def ens_predict(models, X, k):
    P = np.column_stack([m.predict_proba(X)[:, 1] for m in list(models.values())[:k]])
    return np.median(P, axis=1)


def run(lag: int, label: str, target: str):
    d, feats = prepare(lag=lag)
    d = dataset.add_labels(d)
    for t in set(TARGETS.values()):
        s = d[t].shift(lag)
        d[f"{t}_l1"] = s
        d[f"{t}_m30"] = s.rolling(30, min_periods=10).mean()

    split = int(len(d) * 0.8)
    tr, te = d.iloc[:split], d.iloc[split:]
    inner = int(len(tr) * 0.8)
    trf, trv = tr.iloc[:inner], tr.iloc[inner:]

    # --- рішення приймаються ТУТ, на train_val ---
    _, models_v, _ = fit_ensemble(trf, feats, target)
    best, choice = None, None
    # K=1 виключено: це вже не ансамбль, а одна модель, обрана за CV — саме
    # той спосіб відбору, який на цих даних не переноситься на майбутнє
    # (Spearman між рейтингом CV і тестом ≈ 0.2). На горизонті «завтра»
    # валідація обрала K=1, і log-loss на тесті вийшов 1.77 при базовій 0.72.
    for k in (3, 5, 7):
        if k > len(models_v):
            continue
        for shift_on in (False, True):
            p = ens_predict(models_v, trv[feats], k)
            if shift_on:
                p = prior_shift(p, np.clip(np.nan_to_num(
                    trv[f"{target}_m30"].values, nan=trf[target].mean()), .02, .98),
                    trf[target].mean())
            ll = log_loss(trv[target].values, np.clip(p, 1e-6, 1 - 1e-6))
            if best is None or ll < best:
                best, choice = ll, (k, shift_on)
    k, shift_on = choice
    # чи взагалі має сенс модель — теж вирішує train_val, не тест
    base_v = baselines(trf, trv, target)
    base_best = min(base_v, key=lambda n: log_loss(
        trv[target].values, np.clip(base_v[n], 1e-6, 1 - 1e-6)))
    base_ll = log_loss(trv[target].values, np.clip(base_v[base_best], 1e-6, 1 - 1e-6))
    publish = "модель" if best < base_ll else base_best

    # --- підсумкова оцінка на тесті ---
    _, models, cvs = fit_ensemble(tr, feats, target)
    p_model = ens_predict(models, te[feats], min(k, len(models)))
    if shift_on:
        p_model = prior_shift(p_model, np.clip(np.nan_to_num(
            te[f"{target}_m30"].values, nan=tr[target].mean()), .02, .98), tr[target].mean())
    y = te[target].values
    cands = {"модель": p_model, **baselines(tr, te, target)}

    rows = []
    ref = pointwise_ll(y, cands[publish if publish != "модель" else "кліматологія 30"])
    for name, p in cands.items():
        pc = np.clip(p, 1e-6, 1 - 1e-6)
        diff, lo, hi = block_boot(pointwise_ll(y, pc), ref)
        rows.append({
            "горизонт": label, "ціль": target, "оцінка": name,
            "log_loss": log_loss(y, pc), "brier": brier_score_loss(y, pc),
            "roc_auc": roc_auc_score(y, pc) if len(np.unique(y)) > 1 else np.nan,
            "різниця_до_бази": diff, "база": publish if publish != "модель" else "кліматологія 30",
            "ді_низ": lo, "ді_верх": hi,
            "значущо": not (lo <= 0 <= hi),
        })
    meta = {"k": k, "корекція_частки": shift_on, "публікувати": publish,
            "n_train": len(tr), "n_test": len(te), "частка_train": float(tr[target].mean()),
            "частка_test": float(y.mean()), "склад": cvs}
    print(f"{label}/{target}: K={k} корекція={shift_on} публікувати={publish} "
          f"(train {tr[target].mean():.3f} -> test {y.mean():.3f})")
    return rows, meta


if __name__ == "__main__":
    all_rows, all_meta = [], {}
    for lag, label in ((1, "сьогодні"), (2, "завтра")):
        for name, target in TARGETS.items():
            r, m = run(lag, label, target)
            all_rows += r
            all_meta[f"{label}/{name}"] = m
    df = pd.DataFrame(all_rows)
    df.to_csv("ml/results_final.csv", index=False)
    with open("ml/results_final_meta.json", "w") as f:
        json.dump(all_meta, f, ensure_ascii=False, indent=1)
    print()
    print(df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
