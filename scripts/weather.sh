#!/usr/bin/env bash
# Погода: оперативні дані + прогноз. Модель Open-Meteo оновлюється щогодини.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
lock weather
FAILED=0
try weather_recent   "$PY" ingest/weather.py recent
try weather_forecast "$PY" ingest/weather.py forecast
exit $FAILED
