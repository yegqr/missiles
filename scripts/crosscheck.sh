#!/usr/bin/env bash
# Не в cron. Тягне сторонній датасет Vadimkin як НЕЗАЛЕЖНУ звірку наших парсерів:
# розбіжність у годинах тривог — привід дивитися, хто помиляється.
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python ingest/alerts_backfill.py
docker exec -i missiles-pg psql -U missiles -d missiles -c "
SELECT r.code AS регіон, a.source AS джерело, count(*) AS тривог,
       round(sum(a.duration_min)/60) AS годин,
       min(a.started_at)::date AS від, max(a.started_at)::date AS до
FROM alerts a JOIN regions r ON r.id = a.region_id
WHERE r.code IN ('kyiv_city','kyiv_oblast')
GROUP BY 1,2 ORDER BY 1,2;"
