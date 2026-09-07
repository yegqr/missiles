#!/usr/bin/env bash
# Раз на добу: реаналіз ERA5 поверх оперативної погоди + продовження календаря.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
lock daily
FAILED=0
try weather_archive "$PY" ingest/weather.py archive --start "$(date -u -d '20 days ago' +%F)"
try calendar        "$PY" ingest/calendar_build.py
exit $FAILED
