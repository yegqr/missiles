#!/usr/bin/env bash
# Стан конвеєра. Ненульовий код виходу = щось протухло.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

docker exec -i missiles-pg psql -U missiles -d missiles -c "
SELECT source AS потік, стан, остання_вдала,
       date_trunc('second', давність) AS давність, невдач_за_добу
FROM v_health ORDER BY (стан <> 'ok') DESC, source;"

docker exec -i missiles-pg psql -U missiles -d missiles -c "
SELECT region_code AS регіон, остання_тривога,
       date_trunc('second', давність_запису) AS давність_запису
FROM v_freshness WHERE region_code IN ('kyiv_city','kyiv_oblast');"

bad=$(docker exec -i missiles-pg psql -tAU missiles -d missiles \
      -c "SELECT count(*) FROM v_health WHERE стан <> 'ok'")
if [ "$bad" -gt 0 ]; then
    echo "ПРОБЛЕМА: потоків у стані не-ok: $bad"
    exit 1
fi
echo "все ok"
