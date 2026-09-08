"""Експорт бази у відкритий набір даних, придатний для повторного завантаження.

Мета: щоб будь-хто міг узяти каталог `data/release`, виконати `load.sh` і
дістати ту саму базу, на якій рахується модель, — без телеграм-акаунта, без
кількох годин історичного завантаження і без доступу до цієї машини.

Три правила, за якими зібраний набір:

  * Шари роздільні й підписані. Сире (те, що сказало джерело), канонічне
    (звірене й злите), похідне (те, що подається в модель) лежать окремо.
    Змішувати їх в одному файлі означає втратити можливість перевірити
    розмітку — а це головна цінність усього проєкту.
  * Кожен файл має паспорт. manifest.json тримає кількість рядків, період,
    розмір, sha256 і назву парсера, який цей шар породив.
  * Схема їде разом із даними. schema.sql — це реальний DDL із бази, включно
    з представленнями: означення «масованої атаки» чи канонічного ряду не
    переказується словами, а виконується.

Запуск:  .venv/bin/python ingest/export_release.py [--with-messages]
"""
import gzip
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal

import psycopg

DB = os.environ.get("DATABASE_URL",
                    "postgresql://missiles:missiles@127.0.0.1:5543/missiles")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "release")
PG_CONTAINER = os.environ.get("PG_CONTAINER", "missiles-pg")

# (файл, SQL, колонка дати для періоду, парсер-джерело, опис)
LAYERS = [
    # ── довідники ─────────────────────────────────────────────────────
    ("00_regions", "SELECT * FROM regions ORDER BY id", None,
     "db/migrations/001_init.sql",
     "Довідник територій: місто, область, 7 районів. parent_id задає вкладеність — "
     "область є обʼєднанням районів, тому рівні НІКОЛИ не складаються між собою."),
    ("00_alert_sources", "SELECT * FROM alert_sources ORDER BY priority", None,
     "db/migrations/003_canonical.sql",
     "Джерела тривог і їхній пріоритет. Менше число — вищий пріоритет при злитті "
     "в канонічний ряд."),
    ("00_tg_channels", "SELECT * FROM tg_channels ORDER BY handle", None,
     "ingest/tg_accounts.py",
     "Телеграм-канали, з яких зібрано первинні повідомлення."),
    ("00_weather_locations", "SELECT * FROM weather_locations ORDER BY id", None,
     "ingest/weather.py", "Точки, для яких тягнеться погода."),

    # ── шар 1: сире ───────────────────────────────────────────────────
    ("10_alerts", "SELECT * FROM alerts ORDER BY started_at, region_id", "started_at",
     "ingest/kyiv_digital.py, ingest/tg_parse.py, ingest/alerts_backfill.py",
     "СИРІ тривоги всіх джерел, як їх віддало джерело, з полем raw. Перекриття "
     "і дублікати між джерелами тут ЩЕ Є: їх зводить канонічний шар."),
    ("11_attack_observations",
     "SELECT * FROM attack_observations ORDER BY raid_day, region_id, metric", "raid_day",
     "ingest/kpszsu_parse.py",
     "Спостереження зі зведень Повітряних Сил: цілі курсом на Київ, національні "
     "підсумки, наслідки. metric — що саме виміряно, scope — до чого це "
     "стосується ('kyiv' або 'ua'), evidence_text — рядок, з якого це взято. "
     "Величини різних scope НІКОЛИ не складаються між собою."),
    ("12_readiness_signals",
     "SELECT * FROM readiness_signals ORDER BY ts", "ts", "ingest/readiness_parse.py",
     "Зльоти носіїв (МіГ-31К, Ту-95/160, пуски «Калібрів») і відбої готовності."),
    ("13_weather_hourly",
     "SELECT * FROM weather_hourly ORDER BY ts, location_id", "ts", "ingest/weather.py",
     "Погодинна фактична погода (ERA5 + оперативні дані Open-Meteo), 20 показників. "
     "УВАГА: це реаналіз, тобто ЗАДНІМ ЧИСЛОМ. Для прогнозу він непридатний — на "
     "момент відсічки цих значень ще не існує."),
    ("14_weather_forecast",
     "SELECT * FROM weather_forecast ORDER BY issued_at, ts", "ts", "ingest/weather.py",
     "Прогноз погоди з часом видачі issued_at. Ось це подавати в модель можна: "
     "зріз відомий наперед."),
    ("15_calendar_days", "SELECT * FROM calendar_days ORDER BY day", "day",
     "ingest/calendar_build.py",
     "Календар: свята українські й російські з вагою, тривалість темного часу, "
     "опалювальний сезон. Доведений до 2027 року, тому МАЙБУТНІ доби тут теж є."),

    # ── шар 2: канонічне ──────────────────────────────────────────────
    ("20_alerts_canonical",
     "SELECT * FROM v_alerts_canonical ORDER BY started_at, region_code", "started_at",
     "db/migrations/020_parts_overlap.sql, 024_open_alert_now.sql",
     "Канонічний ряд тривог: джерела злиті за пріоритетом, дублікати прибрані, "
     "перекриття склеєні. Відкритий інтервал закінчується min(зараз, старт+24 год). "
     "Це той ряд, з якого рахуються всі хвилини."),
    ("21_alerts_daily",
     "SELECT * FROM v_canon_daily ORDER BY raid_day, region_code", "raid_day",
     "db/migrations/016_massive.sql",
     "Добові агрегати тривог по ДОБІ НАЛЬОТУ (12:00→12:00) для всіх 9 територій. "
     "Щоб дістати місто — фільтруйте region_code='kyiv_city'. Наївна сума по "
     "всьому файлу рахує область і райони двічі."),

    # ── шар 3: похідне, те що йде в модель ────────────────────────────
    ("30_daily_features",
     "SELECT * FROM v_daily_features ORDER BY raid_day", "raid_day",
     "ml/dataset.py",
     "Навчальна таблиця: один рядок — одна доба нальоту. Колонки *_prev — ознаки "
     "(відомі до відсічки 12:00), y_* — те, що сталося. y_attacked IS NULL означає "
     "«невідомо», а НЕ «атаки не було»: такі доби в навчання не йдуть."),
    ("31_predictions",
     "SELECT * FROM predictions ORDER BY raid_day, target, horizon, issued_at", "raid_day",
     "ml/final.py",
     "Кожна видана оцінка з часом видачі. model='climatology30' — опублікована "
     "кліматологія, 'backtest_*' — порахована заднім числом, members містить "
     "тіньовий вихід ансамблю ensemble_p. Рядки не перезаписуються."),
]

BIG = ("90_tg_messages",
       "SELECT * FROM tg_messages ORDER BY channel, msg_id", "posted_at",
       "ingest/tg_telethon.py, ingest/tg_crawl.py",
       "Сирі повідомлення каналів — первинне джерело для розмітки. Великий файл, "
       "у git не кладеться: віддається окремо або відновлюється парсером.")


def jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def dump(conn, name, sql, date_col, parser, doc):
    import csv
    path = os.path.join(OUT, f"{name}.csv.gz")
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = 0
    h = hashlib.sha256()
    # Період беремо з уже прочитаних рядків, а не окремим SELECT min/max по
    # тому самому SQL: представлення на кшталт v_daily_features рахуються
    # секундами, і другий прохід подвоював час експорту рівно ні за що.
    di = cols.index(date_col) if date_col in cols else None
    lo = hi = None
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        while True:
            batch = cur.fetchmany(5000)
            if not batch:
                break
            for r in batch:
                if di is not None and r[di] is not None:
                    lo = r[di] if lo is None or r[di] < lo else lo
                    hi = r[di] if hi is None or r[di] > hi else hi
                w.writerow([jsonable(v) for v in r])
            rows += len(batch)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    period = [jsonable(lo), jsonable(hi)] if lo is not None else None
    print(f"  {name:26s} {rows:>8} рядків  {os.path.getsize(path)/1e6:6.2f} МБ")
    return {"файл": os.path.basename(path), "рядків": rows, "колонок": len(cols),
            "байтів": os.path.getsize(path), "sha256": h.hexdigest(),
            "період": period, "парсер": parser, "опис": doc, "колонки": cols}


def main():
    os.makedirs(OUT, exist_ok=True)
    layers = LAYERS + ([BIG] if "--with-messages" in sys.argv else [])
    manifest = {"згенеровано": datetime.now().astimezone().isoformat(),
                "джерело": "https://github.com/mylovanov/MISSILES",
                "ліцензія": "CC BY 4.0 на дані, MIT на код",
                "часова_зона": "усі мітки часу в UTC; доба нальоту — київська",
                "шари": {}}
    print("Експорт шарів у data/release:")
    with psycopg.connect(DB) as c:
        for name, sql, dcol, parser, doc in layers:
            manifest["шари"][name] = dump(c, name, sql, dcol, parser, doc)

    # DDL їде разом із даними: означення представлень — це і є методологія
    ddl = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "pg_dump", "-s", "-U", "missiles", "missiles"],
        capture_output=True, text=True)
    if ddl.returncode == 0:
        with open(os.path.join(OUT, "schema.sql"), "w") as f:
            f.write(ddl.stdout)
        print(f"  schema.sql                 {len(ddl.stdout.splitlines()):>8} рядків DDL")
    else:
        print("  schema.sql: пропущено —", ddl.stderr.strip()[:200])

    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    total = sum(s["байтів"] for s in manifest["шари"].values())
    print(f"\nГотово: {len(manifest['шари'])} шарів, {total/1e6:.1f} МБ разом.")


if __name__ == "__main__":
    main()
