"""ФІНАЛЬНА КОНФІГУРАЦІЯ: щоденний прогноз і дотренування.

Рішення і підстави (обидва зрізи: валідація всередині train + тест):

  * Ансамбль, а не одна модель. Відбір за CV не переноситься на майбутнє:
    на тесті задачі 1 CV поставив LogReg L1 першим, а виграв XGBoost, восьмий
    за CV. Медіана top-5 не гірша за одиночну в жодному зрізі й краща на тесті.
  * Медіана, а не середнє: одна модель, що з'їхала (MLP, CV=1.12), тягне
    середнє за собою, медіану — ні.
  * Корекція базової частки ВИМКНЕНА. На задачах 1 і 2 шкодить в обох зрізах.
    На задачі 3 виграла на тесті й програла на валідації — тобто шум.
  * Погода ВИМКНЕНА. У v_daily_features нічна погода фактична: це і витік,
    і train/serve skew — на момент відсічки 12:00 її ще не існує. Вмикати
    після того, як накопичаться прогнозні зрізи weather_forecast.
  * Вікно навчання — усе доступне. Обрізання до 365 і 180 діб програло,
    вага за свіжістю теж: втрата обсягу дорожча за застарілість режиму.
  * Масована атака НЕ видається як ймовірність: у жодному чесному зрізі
    ансамбль не перебив кліматологію 30 діб. Видається ранг (модель уміє
    ранжувати: ROC-AUC 0.70-0.73) плюс кліматологічна ймовірність.
"""
import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import psycopg

sys.path.insert(0, "ml")
import dataset
from train import zoo, metrics, CV
from sklearn.model_selection import GridSearchCV

TOP_K = 5
USE_WEATHER = False
PRIOR_SHIFT = False
TARGETS = {"attacked": "y_attacked_i", "alert30": "S_ge1", "massive": "S_ge3"}
# Публікується кліматологія, а не вихід ансамблю — для ВСІХ трьох цілей.
# Підстава (бектест на чистому лейблі, 191 доба тесту):
#   attacked  ансамбль 0.7281 проти кліматології 0.6985, ROC-AUC 0.523
#   alert30   ансамбль 0.6303 проти персистенції   0.6187, ROC-AUC 0.552
#   massive   ансамбль 0.2672 проти кліматології  0.1911, ROC-AUC 0.823
# ROC-AUC 0.52 на головній цілі — це монета. Попередня перевага моделі трималась
# на зіпсованому лейблі: область потрапляла в мітку через повідомлення каналу,
# а балакучість каналу автокорельована, і модель вчилась передбачати саме її.
# Вихід ансамблю далі пишеться тінню в members, щоб міряти його чесно.
CLIMATOLOGY_ONLY = {"attacked", "alert30", "massive"}


def prepare(lag: int = 1, future_days: int = 0):
    d, blocks = dataset.build(weather=USE_WEATHER, lag=lag, future_days=future_days)
    d = dataset.add_labels(d, int(len(d) * 0.8))
    for t in TARGETS.values():
        s = d[t].shift(lag)
        d[f"{t}_l1"] = s
        d[f"{t}_m30"] = s.rolling(30, min_periods=10).mean()
    feats = blocks["A_prev"] + blocks["B_hist"] + blocks["C_calendar"]
    if USE_WEATHER:
        feats += blocks["D_weather"]
    return d, feats


def fit_ensemble(tr, feats, target):
    """Відбір top-K за CV усередині train і навчання їх на всьому train."""
    cv, models = {}, {}
    for name, (pipe, grid) in zoo().items():
        gs = GridSearchCV(pipe, grid, cv=CV, scoring="neg_log_loss", n_jobs=-1)
        gs.fit(tr[feats], tr[target].values)
        cv[name] = -gs.best_score_
        models[name] = gs.best_estimator_
    # NaN трапляється, коли у фолді TimeSeriesSplit опинився один клас і
    # log_loss невизначений. Така модель не має CV-оцінки, отже не може брати
    # участь у відборі: мовчки лишати її з NaN означало б впустити в ансамбль
    # модель, яку ніхто не перевірив.
    scored = pd.Series(cv).dropna().sort_values()
    if scored.empty:
        raise SystemExit("жодна модель не отримала валідної CV-оцінки")
    # Для рідкісних цілей (масована атака — 33 доби з 951) у частині фолдів
    # TimeSeriesSplit немає жодного позитиву, log_loss невизначений, і частина
    # моделей лишається без оцінки. Беремо стільки, скільки реально перевірено:
    # добирати до пʼяти моделями без оцінки означало б впустити неперевірене.
    k = min(TOP_K, len(scored))
    if k < TOP_K:
        print(f"    (валідну CV-оцінку має лише {k} моделей — ансамбль з {k})")
    top = list(scored.index[:k])
    return top, {n: models[n] for n in top}, {n: round(float(cv[n]), 4) for n in top}


def predict(models, X):
    P = np.column_stack([m.predict_proba(X)[:, 1] for m in models.values()])
    return np.median(P, axis=1)


def current_raid_day() -> pd.Timestamp:
    """Доба нальоту, що триває зараз: вона починається о 12:00 за Києвом.

    Зона, а не зсув: наприкінці жовтня Київ переходить на UTC+2, і зашитий
    +3 зрушив би відсічку на годину — рівно в той бік, де починається витік.
    """
    kyiv = datetime.now(ZoneInfo("Europe/Kyiv"))
    return pd.Timestamp((kyiv - timedelta(hours=12)).date())


def backtest():
    """Оцінка САМЕ ТІЄЇ конфігурації, що йде в продакшн."""
    d, feats = prepare()
    split = int(len(d) * 0.8)
    tr, te = d.iloc[:split], d.iloc[split:]
    print(f"Бектест фінальної конфігурації (top-{TOP_K}, погода={USE_WEATHER})")
    print(f"train {tr.raid_day.min().date()}→{tr.raid_day.max().date()} ({len(tr)}), "
          f"test {te.raid_day.min().date()}→{te.raid_day.max().date()} ({len(te)})\n")
    rows = []
    for label, target in TARGETS.items():
        top, models, cvs = fit_ensemble(tr, feats, target)
        y = te[target].values
        p_ens = predict(models, te[feats])
        prior = tr[target].mean()
        p_clim = np.clip(np.nan_to_num(te[f"{target}_m30"].values, nan=prior), .02, .98)
        p_pers = np.where(te[f"{target}_l1"].values == 1,
                          tr.loc[tr[f"{target}_l1"] == 1, target].mean(),
                          tr.loc[tr[f"{target}_l1"] == 0, target].mean())
        rows.append(metrics(y, p_ens, f"{label}: медіана top-5"))
        rows.append(metrics(y, p_clim, f"{label}: [база] кліматологія"))
        rows.append(metrics(y, np.nan_to_num(p_pers, nan=prior), f"{label}: [база] персистенція"))
        print(f"{label}: склад ансамблю {json.dumps(cvs, ensure_ascii=False)}")
    r = pd.DataFrame(rows).set_index("модель")[["log-loss", "Brier", "ROC-AUC", "PR-AUC", "F1@.5"]]
    print("\n" + r.to_string(float_format=lambda v: f"{v:.4f}"))
    r.to_csv("ml/results_final_backtest.csv")
    return r


def daily(write: bool = True):
    """Дотренування і прогноз на обидва горизонти.

    horizon=1 — вікно, що починається сьогодні о 12:00.
    horizon=2 — наступне вікно. Ознаки зі зсувом 2, бо на відсічці доба
    між сьогодні й завтра ще триває і її підсумків не існує.
    """
    # Горизонти незалежні. Падіння одного не має ховати другий і не має
    # зупиняти перебудову сайту: саме так «завтра» тихо зникло зі сторінки.
    failed = []
    for lag, day_off in ((1, 0), (2, 1)):
        try:
            _daily_one(lag, day_off, write)
        except SystemExit as e:
            failed.append(f"горизонт {lag}: {e}")
            print(f"  ПОМИЛКА горизонту {lag}: {e}")
    if failed:
        raise SystemExit("; ".join(failed))


def _daily_one(lag: int, day_off: int, write: bool):
    d, feats = prepare(lag=lag, future_days=day_off)
    day = current_raid_day() + pd.Timedelta(days=day_off)
    row = d[d.raid_day == day]
    if row.empty:
        raise SystemExit(f"немає рядка ознак на {day.date()} — спершу оновіть дані")
    # У навчання йдуть лише доби, підсумки яких повністю відомі на відсічці.
    # y_known обовʼязковий: у d тепер лишається хвіст майбутніх діб без лейбла,
    # інакше горизонт «завтра» не мав би рядка ознак на цільову добу.
    tr = d[(d.raid_day <= day - pd.Timedelta(days=lag)) & d.y_known]
    print(f"\nГоризонт {lag} → доба нальоту {day.date()} (12:00 → 12:00). "
          f"Навчання на {len(tr)} добах ({tr.raid_day.min().date()} → {tr.raid_day.max().date()})")

    out = []
    for label, target in TARGETS.items():
        top, models, cvs = fit_ensemble(tr, feats, target)
        p_ens = float(predict(models, row[feats])[0])
        prior = tr[target].mean()
        clim = float(np.clip(np.nan_to_num(row[f"{target}_m30"].values, nan=prior), .02, .98)[0])
        if label in CLIMATOLOGY_ONLY:
            p, model_name = clim, "climatology30"
            note = f"тінь ансамблю {p_ens:.3f}"
        else:
            p, model_name = p_ens, f"median_top{TOP_K}"
            note = f"кліматологія {clim:.3f}"
        print(f"  {label:9s} p = {p:.3f}   ({note})")
        meta = {"members": cvs, "ensemble_p": round(p_ens, 4), "climatology_p": round(clim, 4)}
        out.append((day.date(), label, lag, p, model_name,
                    json.dumps(meta, ensure_ascii=False), len(tr)))

    if write:
        with psycopg.connect(dataset.DB) as c:
            c.cursor().executemany(
                "INSERT INTO predictions "
                "(raid_day,target,horizon,p,model,members,prior_shift,n_train) "
                "VALUES (%s,%s,%s,%s,%s,%s,false,%s)", out)
        print(f"\nЗаписано {len(out)} прогнозів у predictions.")


if __name__ == "__main__":
    if "--backtest" in sys.argv:
        backtest()
    else:
        daily(write="--dry-run" not in sys.argv)
