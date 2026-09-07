#!/usr/bin/env bash
# Погодинний прохід. Усе з первинних джерел, без сторонніх датасетів.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
echo "=== $(date -Is) ==="

# м. Київ: реєстр КМДА. Один запит віддає всю історію І поточний стан,
# тому окремий backfill не потрібен — щогодинного виклику достатньо.
$PY ingest/kyiv_digital.py

# Київська область і райони: канал системи оповіщення @air_alert_ua.
# incremental бере лише нові повідомлення; розбір мовчки пропускається,
# доки не завершився повний обхід історії.
$PY ingest/tg_crawl.py incremental
$PY ingest/tg_parse.py

# Погода
$PY ingest/weather.py recent
$PY ingest/weather.py forecast
