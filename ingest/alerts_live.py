#!/usr/bin/env python3
"""Лайв-оновлення тривог.

Основне джерело — alerts.in.ua (потрібен токен, заявка на alerts.in.ua/api-request):
дає стан "просто зараз", тобто відкриту тривогу видно в межах хвилин.

Без токена працює резервний шлях: перезавантаження щоденного датасету Vadimkin.
Він відстає на кілька годин, але дозволяє запустити пайплайн уже сьогодні.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db
import alerts_backfill

API = "https://api.alerts.in.ua/v1/alerts/active.json"


def esc(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def live_via_api(token):
    req = urllib.request.Request(API, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)

    tracked = {int(uid): int(rid) for rid, uid in db.query(
        "SELECT id, alerts_in_ua_uid FROM regions WHERE alerts_in_ua_uid IS NOT NULL")}

    active = {}
    for a in data.get("alerts", []):
        if a.get("alert_type") != "air_raid":
            continue
        uid = int(a["location_uid"]) if a.get("location_uid") else None
        if uid in tracked:
            active[tracked[uid]] = a

    stmts = []
    for region_id, a in active.items():
        stmts.append(
            f"INSERT INTO alerts (region_id, started_at, source, source_alert_id, raw) "
            f"VALUES ({region_id}, {esc(a['started_at'])}, 'alerts_in_ua', "
            f"{esc(a.get('id'))}, {esc(json.dumps(a, ensure_ascii=False))}::jsonb) "
            f"ON CONFLICT (source, region_id, alert_type, started_at) DO NOTHING;")

    # закриваємо все, чого вже немає серед активних
    still = ", ".join(str(r) for r in active) or "NULL"
    stmts.append(
        f"UPDATE alerts SET finished_at = now() "
        f"WHERE source='alerts_in_ua' AND finished_at IS NULL "
        f"AND region_id NOT IN ({still});")

    db.script("\n".join(stmts))
    return len(active)


def main():
    token = db.ENV.get("ALERTS_IN_UA_TOKEN") or ""
    if token:
        with db.Run("alerts_in_ua", "live") as run:
            n = live_via_api(token)
            run.rows_read = run.rows_written = n
        print(f"  alerts.in.ua: активних тривог у зоні моніторингу — {n}")
    else:
        print("  ALERTS_IN_UA_TOKEN не заданий — резервний шлях (датасет Vadimkin)")
        alerts_backfill.main()


if __name__ == "__main__":
    main()
