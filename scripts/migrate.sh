#!/usr/bin/env bash
# Застосовує db/migrations/*.sql по порядку, один раз кожну.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

PSQL=(docker exec -i missiles-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q)

"${PSQL[@]}" -c "CREATE TABLE IF NOT EXISTS schema_migrations (
    filename text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now());"

for f in db/migrations/*.sql; do
    name=$(basename "$f")
    applied=$("${PSQL[@]}" -tAc "SELECT 1 FROM schema_migrations WHERE filename='$name'")
    if [[ "$applied" == "1" ]]; then
        echo "  skip  $name"
        continue
    fi
    echo "  apply $name"
    "${PSQL[@]}" -1 -f - < <(cat "$f"; echo "INSERT INTO schema_migrations(filename) VALUES ('$name');")
done
echo "migrations done"
