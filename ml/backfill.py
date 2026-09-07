"""Заповнення історії прогнозів walk-forward бектестом.

Ці значення НЕ є реально виданими прогнозами: їх пораховано заднім числом.
Тому вони пишуться з окремим model='backtest_median_top5' і на сайті
показуються інакше. Плутати їх із живими прогнозами не можна — саме на такій
підміні найлегше отримати картину, кращу за дійсність.

Чесність забезпечується тим, що для кожного блоку модель бачить лише доби,
підсумки яких були відомі на його відсічці: train = raid_day <= block_start - lag.
"""
import json
import sys

import pandas as pd
import psycopg

sys.path.insert(0, "ml")
import dataset
from final import prepare, fit_ensemble, predict

TARGET = "y_attacked_i"
LABEL = "attacked"
REFIT_EVERY = 30          # діб між перенавчаннями: компроміс ціни й реалістичності
START = pd.Timestamp("2026-03-01")


def main():
    rows = []
    for lag in (1, 2):
        d, feats = prepare(lag=lag)
        d = dataset.add_labels(d, int(len(d) * 0.8))
        blocks = pd.date_range(START, d.raid_day.max(), freq=f"{REFIT_EVERY}D")
        for i, b0 in enumerate(blocks):
            b1 = blocks[i + 1] if i + 1 < len(blocks) else d.raid_day.max() + pd.Timedelta(days=1)
            tr = d[d.raid_day <= b0 - pd.Timedelta(days=lag)]
            te = d[(d.raid_day >= b0) & (d.raid_day < b1)]
            if te.empty:
                continue
            top, models, cvs = fit_ensemble(tr, feats, TARGET)
            p = predict(models, te[feats])
            for day, pi in zip(te.raid_day, p):
                rows.append((day.date(), LABEL, lag, round(float(pi), 4),
                             "backtest_median_top5",
                             json.dumps(cvs, ensure_ascii=False), len(tr)))
            print(f"lag={lag} {b0.date()}→{b1.date()}: {len(te)} діб, навчено на {len(tr)}")

    with psycopg.connect(dataset.DB) as c:
        c.execute("DELETE FROM predictions WHERE model = 'backtest_median_top5'")
        c.cursor().executemany(
            "INSERT INTO predictions "
            "(raid_day,target,horizon,p,model,members,prior_shift,n_train) "
            "VALUES (%s,%s,%s,%s,%s,%s,false,%s)", rows)
    print(f"записано {len(rows)} бектест-прогнозів")


if __name__ == "__main__":
    main()
