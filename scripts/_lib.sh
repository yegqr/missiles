# Спільна обгортка для всіх заходів у cron.
# Ставить блокування, щоб повільний прохід не накладався на наступний,
# і пише в лог із міткою часу.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

log() { printf '%s  %s\n' "$(date -Is)" "$*"; }

# lock <ім'я> — далі виконується тільки якщо блокування вільне
lock() {
    local name="$1"
    exec 9>"$ROOT/data/locks/$name.lock"
    if ! flock -n 9; then
        log "пропуск: попередній прохід $name ще працює"
        exit 0
    fi
}

# try <крок> <команда...> — крок не має валити весь прохід
try() {
    local name="$1"; shift
    if "$@"; then
        return 0
    else
        log "ЗБІЙ на кроці $name (код $?)"
        FAILED=1
        return 0
    fi
}
