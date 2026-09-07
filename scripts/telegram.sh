#!/usr/bin/env bash
# Телеграм-канали: добір нових повідомлень і перерозбір.
# Парсери самі пропускаються, якщо канал не виріс, тому частий запуск дешевий.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
lock telegram
FAILED=0

try crawl_alerts "$PY" ingest/tg_telethon.py air_alert_ua incremental --account 0
try crawl_ps     "$PY" ingest/tg_telethon.py kpszsu       incremental --account 1

try parse_alerts    "$PY" ingest/tg_parse.py
try parse_ps        "$PY" ingest/kpszsu_parse.py
try parse_readiness "$PY" ingest/readiness_parse.py

exit $FAILED
