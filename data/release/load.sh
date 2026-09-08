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
    f=$(ls 00_${t}.csv.gz)
    echo "   $t"
    gunzip -c "$f" | psql -c "\copy $t FROM STDIN WITH (FORMAT csv, HEADER true)"
done

echo "3/3 дані"
declare -A FILES=(
    [alerts]=10_alerts.csv.gz
    [attack_observations]=11_attack_observations.csv.gz
    [readiness_signals]=12_readiness_signals.csv.gz
    [weather_hourly]=13_weather_hourly.csv.gz
    [weather_forecast]=14_weather_forecast.csv.gz
    [calendar_days]=15_calendar_days.csv.gz
    [predictions]=31_predictions.csv.gz
)
for t in "${!FILES[@]}"; do
    [ -f "${FILES[$t]}" ] || { echo "   $t — файлу немає, пропущено"; continue; }
    echo "   $t"
    gunzip -c "${FILES[$t]}" | psql -c "\copy $t FROM STDIN WITH (FORMAT csv, HEADER true)"
done

echo
echo "Перевірка:"
psql -c "SELECT * FROM v_coverage"
