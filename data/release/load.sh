#!/usr/bin/env bash
# Завантаження набору назад у чистий Postgres.
#
# Вантажаться ТІЛЬКИ базові таблиці. Похідні шари (20_, 21_, 30_) — це
# представлення: їх створює schema.sql і перераховує сама база. Класти їх
# як таблиці означало б мати дві копії правди, які розійдуться.
set -euo pipefail
cd "$(dirname "$0")"

DB=${DATABASE_URL:-postgresql://missiles:missiles@127.0.0.1:5543/missiles}
psql() { command psql "$DB" -v ON_ERROR_STOP=1 "$@"; }

echo "1/3 схема"
psql -f schema.sql

echo "2/3 довідники"
for t in regions alert_sources tg_channels weather_locations; do
    echo "   $t"
    psql -c "\copy $t FROM '00_${t}.csv' WITH (FORMAT csv, HEADER true)"
done

echo "3/3 дані"
declare -A FILES=(
    [alerts]=10_alerts.csv
    [attack_observations]=11_attack_observations.csv
    [readiness_signals]=12_readiness_signals.csv
    [weather_hourly]=13_weather_hourly.csv
    [weather_forecast]=14_weather_forecast.csv
    [calendar_days]=15_calendar_days.csv
    [predictions]=31_predictions.csv
)
for t in "${!FILES[@]}"; do
    [ -f "${FILES[$t]}" ] || { echo "   $t — файлу немає, пропущено"; continue; }
    echo "   $t"
    psql -c "\copy $t FROM '${FILES[$t]}' WITH (FORMAT csv, HEADER true)"
done

echo
echo "Перевірка:"
psql -c "SELECT * FROM v_coverage"
