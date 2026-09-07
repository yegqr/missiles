#!/usr/bin/env python3
"""Тривоги по м. Києву з реєстру КМДА («Київ Цифровий»).

https://kyiv.digital/open-api/air-alert/history — XML, без токена.
Один запит віддає всю історію змін стану з 25.02.2022 і поточний стан.
Тому backfill і лайв — це той самий виклик: просто ганяємо його щогодини.

Формат: послідовність подій <item><state>0|1</state><causes>…</causes>
<created_at>YYYY-MM-DD HH:MM:SS</created_at></item>, час київський локальний.
state=1 — початок тривоги, state=0 — відбій. Складаємо їх у інтервали.
"""
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import db

URL = "https://kyiv.digital/open-api/air-alert/history"
KYIV = ZoneInfo("Europe/Kyiv")

# Якщо відбою немає понад стільки — вважаємо, що подію відбою загубили,
# і не тягнемо "відкриту" тривогу через тижні. Найдовша реальна тривога
# в Києві — близько 11 годин.
MAX_ALERT = timedelta(hours=24)


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "KSE-missiles/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def parse(xml_bytes):
    """XML -> список (started_at, finished_at, causes) в UTC."""
    root = ET.fromstring(xml_bytes)
    events = []
    for item in root.findall("./items/item"):
        raw = item.findtext("created_at")
        if not raw:
            continue
        ts = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=KYIV).astimezone(timezone.utc)
        causes = [c.text for c in item.findall("./causes/item") if c.text]
        events.append((ts, item.findtext("state"), causes))

    events.sort(key=lambda e: e[0])          # у фіді порядок зворотний
    alerts, open_at, open_causes = [], None, []
    for ts, state, causes in events:
        if state == "1":
            if open_at is not None:
                # відбій загубився: закриваємо попередню з обмеженням
                alerts.append((open_at, min(ts, open_at + MAX_ALERT), open_causes))
            open_at, open_causes = ts, causes
        elif state == "0":
            if open_at is not None:
                alerts.append((open_at, ts, open_causes))
                open_at, open_causes = None, []
            # відбій без початку — сміття у фіді, ігноруємо
    if open_at is not None:
        alerts.append((open_at, None, open_causes))   # тривога триває просто зараз
    return alerts, len(events)


def pg_array(values):
    if not values:
        return "\\N"
    return "{" + ",".join(v.replace('"', '') for v in values) + "}"


def upsert(region_id, alerts):
    tsv = "\n".join(
        "\t".join([
            str(region_id),
            s.isoformat(),
            f.isoformat() if f else "\\N",
            "kyiv_digital",
            pg_array(c),
        ]) for s, f, c in alerts)
    db.script(f"""
CREATE TEMP TABLE _stage_kd (
    region_id smallint, started_at timestamptz, finished_at timestamptz,
    source text, causes text[]);
COPY _stage_kd FROM STDIN;
{tsv}
\\.
INSERT INTO alerts (region_id, started_at, finished_at, source, causes)
SELECT region_id, started_at, finished_at, source, causes FROM _stage_kd
ON CONFLICT (source, region_id, alert_type, started_at) DO UPDATE
   SET finished_at = EXCLUDED.finished_at,
       causes      = EXCLUDED.causes,
       updated_at  = now()
   WHERE alerts.finished_at IS DISTINCT FROM EXCLUDED.finished_at
      OR alerts.causes      IS DISTINCT FROM EXCLUDED.causes;
""")


def main():
    region_id = int(db.scalar("SELECT id FROM regions WHERE code='kyiv_city'"))
    with db.Run("kyiv_digital", "live", {"url": URL}) as run:
        alerts, n_events = parse(fetch())
        run.rows_read = n_events
        before = int(db.scalar(
            "SELECT count(*) FROM alerts WHERE source='kyiv_digital'"))
        upsert(region_id, alerts)
        after = int(db.scalar(
            "SELECT count(*) FROM alerts WHERE source='kyiv_digital'"))
        run.rows_written = after - before
        open_now = sum(1 for _, f, _ in alerts if f is None)
        print(f"  подій {n_events}, тривог {len(alerts)}, нових {after - before}, "
              f"всього {after}" + (", ЗАРАЗ ТРИВАЄ ТРИВОГА" if open_now else ""))


if __name__ == "__main__":
    main()
