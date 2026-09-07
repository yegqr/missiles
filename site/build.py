"""Експорт даних для сайту airalert.mylovanov.media.

Статика навмисно: жодного застосунку, який може впасти. Cron перебудовує
JSON і CSV, nginx роздає файли. Сторінка сама перепитує api/latest.json,
тому «майже лайв» коштує нуль процесів.
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ml"))
DB = os.environ.get("DATABASE_URL", "postgresql://missiles:missiles@127.0.0.1:5543/missiles")
OUT = os.path.dirname(os.path.abspath(__file__))


KYIV = ZoneInfo("Europe/Kyiv")


def kyiv_now():
    """Справжня зона, не зсув: наприкінці жовтня Київ переходить на UTC+2,
    і зашитий +3 посунув би і відсічку, і підпис «оновлено» на годину."""
    return datetime.now(KYIV)


def num(v):
    return float(v) if isinstance(v, Decimal) else v


def fetch(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def main():
    now = kyiv_now()
    today = (now - timedelta(hours=12)).date()      # доба нальоту, що триває
    with psycopg.connect(DB) as c:
        # Живий прогноз завжди виграє в бектесту на ту саму добу. Бектест
        # рахується заднім числом і запускається пізніше, тому за самим лише
        # issued_at він перекривав би те, що модель справді видала о 12:00.
        preds = fetch(c, """
            SELECT DISTINCT ON (raid_day, target, horizon)
                   raid_day, target, horizon, p, issued_at, model, n_train, members
            FROM predictions
            ORDER BY raid_day, target, horizon,
                     starts_with(model, 'backtest') ASC, issued_at DESC""")
        hist = fetch(c, """
            SELECT raid_day, y_attacked, y_alert_minutes, y_drone_tracks, y_missile_tracks
            FROM v_daily_features
            WHERE raid_day <= %s AND raid_day >= %s
            ORDER BY raid_day DESC""", (today, today - timedelta(days=400)))
        scores = fetch(c, """
            SELECT horizon, target, count(*) n, avg(brier) brier
            FROM v_prediction_scores GROUP BY 1,2 ORDER BY 1,2""")
        cov = fetch(c, "SELECT * FROM v_coverage")

    by_key = {(p["raid_day"], p["target"], p["horizon"]): p for p in preds}

    def card(day, horizon):
        p = by_key.get((day, "attacked", horizon))
        if not p:
            return None
        mass = by_key.get((day, "massive", horizon))
        alert = by_key.get((day, "alert30", horizon))
        return {
            "raid_day": day.isoformat(),
            "horizon": horizon,
            "window": f"{day.isoformat()} 12:00 → {(day + timedelta(days=1)).isoformat()} 12:00",
            "p_attack": round(num(p["p"]), 4),
            "p_massive": round(num(mass["p"]), 4) if mass else None,
            "p_alert30": round(num(alert["p"]), 4) if alert else None,
            "issued_at": p["issued_at"].isoformat(),
            "model": p["model"],
            "n_train": p["n_train"],
            "members": p["members"],
        }

    # факт по добах + який прогноз на них видавався
    rows = []
    for h in hist:
        d = h["raid_day"]
        done = d < today
        rows.append({
            "raid_day": d.isoformat(),
            "attacked": bool(h["y_attacked"]) if done else None,
            "alert_minutes": int(h["y_alert_minutes"] or 0),
            "drone_tracks": int(h["y_drone_tracks"] or 0),
            "missile_tracks": int(h["y_missile_tracks"] or 0),
            # масована = 8+ годин під тривогою або надзвичайно щільний супровід
            "massive": done and bool(
                (int(h["y_drone_tracks"] or 0) + int(h["y_missile_tracks"] or 0)) > 0
                and (int(h["y_alert_minutes"] or 0) >= 480
                     or int(h["y_drone_tracks"] or 0) >= 15)),
            "p_today": (lambda x: round(num(x["p"]), 4) if x else None)(
                by_key.get((d, "attacked", 1))),
            "p_tomorrow": (lambda x: round(num(x["p"]), 4) if x else None)(
                by_key.get((d, "attacked", 2))),
            # true = пораховано заднім числом, false = виданий наживо
            "backtest": (lambda x: x["model"].startswith("backtest") if x else None)(
                by_key.get((d, "attacked", 1)) or by_key.get((d, "attacked", 2))),
        })

    data = {
        "generated_at": now.isoformat(),
        "today": card(today, 1),
        "tomorrow": card(today + timedelta(days=1), 2),
        "history": rows,
        "scores": [{"horizon": s["horizon"], "target": s["target"],
                    "n": s["n"], "brier": round(num(s["brier"]), 4)} for s in scores],
        "coverage": [{k: (v.isoformat() if hasattr(v, "isoformat") else num(v))
                      for k, v in row.items()} for row in cov],
    }
    with open(os.path.join(OUT, "api", "latest.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # CSV на завантаження: сирі добові ознаки і всі видані прогнози
    with psycopg.connect(DB) as c:
        for name, sql in (("daily_features",
                           "SELECT * FROM v_daily_features "
                           "WHERE raid_day < (now() AT TIME ZONE 'Europe/Kyiv')::date "
                           "ORDER BY raid_day"),
                          ("predictions", "SELECT * FROM predictions ORDER BY raid_day, target, horizon, issued_at"),
                          # Тільки МІСТО. У v_canon_daily лежать 9 територій, і рівні
                          # вкладені: область = обʼєднання районів. Наївна сума по
                          # файлу з усіма рядками рахує область двічі й дає ~4x.
                          ("alerts_daily",
                           "SELECT * FROM v_canon_daily WHERE region_code = 'kyiv_city' "
                           "AND raid_day < (now() AT TIME ZONE 'Europe/Kyiv')::date "
                           "ORDER BY raid_day")):
            cur = c.execute(sql)
            with open(os.path.join(OUT, "dl", f"{name}.csv"), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([d[0] for d in cur.description])
                w.writerows(cur.fetchall())

    # ваги ознак перераховуються разом із даними, а не зашиті в сторінку
    try:
        import subprocess
        subprocess.run([sys.executable, os.path.join(OUT, "..", "ml", "importances.py")],
                       check=False, capture_output=True, timeout=600)
    except Exception as e:
        print("importances: пропущено —", e)

    print(f"site: {len(rows)} діб історії, прогнози "
          f"сьогодні={'є' if data['today'] else 'нема'} "
          f"завтра={'є' if data['tomorrow'] else 'нема'}")


if __name__ == "__main__":
    main()
