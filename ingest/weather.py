#!/usr/bin/env python3
"""Погода по Києву з Open-Meteo (ключ не потрібен).

Три режими:
  archive  — реаналіз ERA5 з 2022-02-24, лаг ~5 діб. Еталонні значення.
  recent   — оперативна модель за останні дні: закриває розрив між
             кінцем архіву і "зараз". Пізніше перезаписується архівом.
  forecast — прогноз уперед, у окрему таблицю weather_forecast зі зрізом issued_at.

visibility в ERA5 відсутня — приходить тільки з forecast-API.
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

WAR_START = date(2022, 2, 24)

ARCHIVE_VARS = [
    "temperature_2m", "apparent_temperature", "relative_humidity_2m", "dew_point_2m",
    "precipitation", "rain", "snowfall", "cloud_cover", "cloud_cover_low",
    "cloud_cover_mid", "cloud_cover_high", "wind_speed_10m", "wind_speed_100m",
    "wind_gusts_10m", "wind_direction_10m", "surface_pressure", "pressure_msl",
    "weather_code", "is_day",
]
LIVE_VARS = ARCHIVE_VARS + ["visibility"]

FORECAST_VARS = [
    "temperature_2m", "precipitation", "cloud_cover", "cloud_cover_low", "visibility",
    "wind_speed_10m", "wind_speed_100m", "wind_gusts_10m", "wind_direction_10m",
    "surface_pressure", "weather_code",
]


def get(url, params):
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{q}", timeout=120) as r:
        return json.load(r)


def locations():
    return [(int(i), code, float(lat), float(lon))
            for i, code, lat, lon in
            db.query("SELECT id, code, lat, lon FROM weather_locations ORDER BY id")]


def _rows(payload, variables):
    """JSON колонками -> рядки; None де змінної немає або значення порожнє."""
    h = payload["hourly"]
    times = h["time"]
    cols = [h.get(v) or [None] * len(times) for v in variables]
    for i, t in enumerate(times):
        yield t, [c[i] for c in cols]


def upsert_hourly(loc_id, source, variables, payload):
    rows = []
    for t, vals in _rows(payload, variables):
        rows.append([loc_id, f"{t}+00", source] + [v for v in vals])
    if not rows:
        return 0
    cols = ["location_id", "ts", "source"] + variables
    payload_tsv = "\n".join(
        "\t".join("\\N" if v is None else str(v) for v in r) for r in rows)
    coldef = ", ".join(
        f"{c} text" for c in cols)
    script = f"""
CREATE TEMP TABLE _stage_w ({coldef});
COPY _stage_w FROM STDIN;
{payload_tsv}
\\.
INSERT INTO weather_hourly ({", ".join(cols)})
SELECT location_id::smallint, ts::timestamptz, source,
       {", ".join(f"{c}::" + ("smallint" if c in
            ("relative_humidity_2m","cloud_cover","cloud_cover_low","cloud_cover_mid",
             "cloud_cover_high","wind_direction_10m","weather_code")
            else "boolean" if c == "is_day" else "real")
          for c in variables)}
FROM _stage_w
ON CONFLICT (location_id, ts) DO UPDATE SET
  {", ".join(f"{c} = EXCLUDED.{c}" for c in variables)},
  source = EXCLUDED.source,
  fetched_at = now()
-- архів (ERA5) завжди має пріоритет над оперативною моделлю
WHERE EXCLUDED.source = 'era5_archive' OR weather_hourly.source = EXCLUDED.source;
"""
    db.script(script)
    return len(rows)


def run_archive(start=None, end=None):
    end = end or (date.today() - timedelta(days=6))
    start = start or WAR_START
    total = 0
    with db.Run("open_meteo_archive", "backfill",
                {"start": str(start), "end": str(end)}) as run:
        for loc_id, code, lat, lon in locations():
            # ріжемо на роки: один запит на 4 роки віддає ~40k годин
            y = start
            while y <= end:
                chunk_end = min(date(y.year, 12, 31), end)
                data = get("https://archive-api.open-meteo.com/v1/archive", {
                    "latitude": lat, "longitude": lon,
                    "start_date": str(y), "end_date": str(chunk_end),
                    "hourly": ",".join(ARCHIVE_VARS), "timezone": "UTC",
                })
                n = upsert_hourly(loc_id, "era5_archive", ARCHIVE_VARS, data)
                total += n
                print(f"  {code} {y}..{chunk_end}: {n} годин")
                y = chunk_end + timedelta(days=1)
        run.rows_read = run.rows_written = total
    return total


def run_recent(past_days=10):
    total = 0
    with db.Run("open_meteo_recent", "live", {"past_days": past_days}) as run:
        for loc_id, code, lat, lon in locations():
            data = get("https://api.open-meteo.com/v1/forecast", {
                "latitude": lat, "longitude": lon,
                "hourly": ",".join(LIVE_VARS), "past_days": past_days,
                "forecast_days": 1, "timezone": "UTC",
            })
            total += upsert_hourly(loc_id, "forecast", LIVE_VARS, data)
        run.rows_read = run.rows_written = total
    print(f"  оперативні дані: {total} годин")
    return total


def run_forecast(days=7):
    issued = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    total = 0
    with db.Run("open_meteo_forecast", "live", {"days": days}) as run:
        for loc_id, code, lat, lon in locations():
            data = get("https://api.open-meteo.com/v1/forecast", {
                "latitude": lat, "longitude": lon,
                "hourly": ",".join(FORECAST_VARS), "forecast_days": days,
                "timezone": "UTC",
            })
            rows = [[loc_id, issued.isoformat(), f"{t}+00"] + vals
                    for t, vals in _rows(data, FORECAST_VARS)]
            cols = ["location_id", "issued_at", "ts"] + FORECAST_VARS
            tsv = "\n".join("\t".join("\\N" if v is None else str(v) for v in r)
                            for r in rows)
            coldef = ", ".join(f"{c} text" for c in cols)
            casts = ", ".join(
                f"{c}::" + ("smallint" if c in ("cloud_cover", "cloud_cover_low",
                                                "wind_direction_10m", "weather_code")
                            else "real")
                for c in FORECAST_VARS)
            db.script(f"""
CREATE TEMP TABLE _stage_f ({coldef});
COPY _stage_f FROM STDIN;
{tsv}
\\.
INSERT INTO weather_forecast ({", ".join(cols)})
SELECT location_id::smallint, issued_at::timestamptz, ts::timestamptz, {casts}
FROM _stage_f
ON CONFLICT (location_id, issued_at, ts) DO NOTHING;
""")
            total += len(rows)
        run.rows_read = run.rows_written = total
    print(f"  прогноз: {total} годин")
    return total


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["archive", "recent", "forecast", "all"])
    p.add_argument("--start"); p.add_argument("--end")
    a = p.parse_args()
    s = date.fromisoformat(a.start) if a.start else None
    e = date.fromisoformat(a.end) if a.end else None
    if a.mode in ("archive", "all"):
        run_archive(s, e)
    if a.mode in ("recent", "all"):
        run_recent()
    if a.mode in ("forecast", "all"):
        run_forecast()
