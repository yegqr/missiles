#!/usr/bin/env python3
"""Історія тривог по Києву і Київській області.

Джерело: Vadimkin/ukrainian-air-raid-sirens-dataset (оновлюється щодня).
  volunteer_data_uk.csv — з 2022-02-25, рівень регіону (eTryvoga)
  official_data_uk.csv  — з 2022-03-15, офіційні канали, рівні oblast/raion/hromada

Обидва джерела пишемо в alerts і розрізняємо колонкою source: офіційні дані
починаються лише 15.03.2022, тож перші три тижні великої війни закриває
лише волонтерський набір.
"""
import csv
import io
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

BASE = "https://raw.githubusercontent.com/Vadimkin/ukrainian-air-raid-sirens-dataset/main/datasets"
CACHE = Path(__file__).resolve().parent.parent / "data"

# назва в датасеті -> code у regions
OFFICIAL_OBLAST = {"м. Київ": "kyiv_city", "Київська область": "kyiv_oblast"}
OFFICIAL_RAION = {
    "Вишгородський район": "kyiv_obl_vyshhorod",
    "Броварський район": "kyiv_obl_brovary",
    "Бориспільський район": "kyiv_obl_boryspil",
    "Обухівський район": "kyiv_obl_obukhiv",
    "Бучанський район": "kyiv_obl_bucha",
    "Фастівський район": "kyiv_obl_fastiv",
    "Білоцерківський район": "kyiv_obl_bila_tserkva",
}
VOLUNTEER = {"Київ": "kyiv_city", "Київська область": "kyiv_oblast"}


def fetch(name, refresh=True):
    path = CACHE / name
    if refresh or not path.exists():
        CACHE.mkdir(exist_ok=True)
        urllib.request.urlretrieve(f"{BASE}/{name}", path)
    return path


def region_ids():
    return {code: int(rid) for code, rid in db.query("SELECT code, id FROM regions")}


def load_official(path, ids):
    """Повертає рядки (region_id, started_at, finished_at, source)."""
    out, read = [], 0
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            read += 1
            code = None
            if r["level"] == "oblast":
                code = OFFICIAL_OBLAST.get(r["oblast"])
            elif r["level"] == "raion" and r["oblast"] == "Київська область":
                code = OFFICIAL_RAION.get(r["raion"])
            # рівень hromada свідомо пропускаємо: у Києві його немає,
            # а по області він фрагментарний (десятки записів за 4 роки)
            if not code:
                continue
            out.append((ids[code], r["started_at"], r["finished_at"] or None, "official"))
    return out, read


def load_volunteer(path, ids):
    out, read = [], 0
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            read += 1
            code = VOLUNTEER.get(r["region"])
            if not code:
                continue
            out.append((ids[code], r["started_at"], r["finished_at"] or None, "volunteer"))
    return out, read


def upsert(rows):
    """COPY у тимчасову таблицю -> INSERT ON CONFLICT у alerts.

    Temp-таблиця живе тільки в межах сесії psql, тому створення, COPY
    і INSERT ідуть одним скриптом.
    """
    payload = "\n".join(
        "\t".join("\\N" if v is None else str(v) for v in row) for row in rows)
    script = f"""
CREATE TEMP TABLE _stage_alerts (
    region_id smallint, started_at timestamptz,
    finished_at timestamptz, source text);
COPY _stage_alerts FROM STDIN;
{payload}
\\.
INSERT INTO alerts (region_id, started_at, finished_at, source)
SELECT DISTINCT ON (source, region_id, started_at)
       region_id, started_at, finished_at, source
FROM _stage_alerts
ORDER BY source, region_id, started_at, finished_at DESC NULLS LAST
ON CONFLICT (source, region_id, alert_type, started_at) DO UPDATE
   SET finished_at = EXCLUDED.finished_at
   WHERE alerts.finished_at IS DISTINCT FROM EXCLUDED.finished_at;
"""
    db.script(script)


def main():
    ids = region_ids()
    with db.Run("vadimkin_dataset", "backfill", {"datasets": ["official", "volunteer"]}) as run:
        off, n1 = load_official(fetch("official_data_uk.csv"), ids)
        vol, n2 = load_volunteer(fetch("volunteer_data_uk.csv"), ids)
        rows = off + vol
        run.rows_read = n1 + n2
        before = int(db.scalar("SELECT count(*) FROM alerts"))
        upsert(rows)
        after = int(db.scalar("SELECT count(*) FROM alerts"))
        run.rows_written = after - before
        print(f"прочитано {run.rows_read}, київських {len(rows)}, "
              f"нових у БД {run.rows_written}, всього {after}")


if __name__ == "__main__":
    main()
