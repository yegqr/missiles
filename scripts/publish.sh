#!/usr/bin/env bash
# Публікація на GitHub: перезбирає відкритий набір і пушить, якщо щось змінилось.
#
# ЧОМУ ВАРТОВИЙ ПО ГОДИНІ, А НЕ ПРОСТО ЧАС У CRON. Debian-івський cron ігнорує
# CRON_TZ і працює за UTC, а Київ узимку UTC+2, улітку UTC+3. Тому cron будить
# скрипт на обидві можливі години, а скрипт сам звіряє київську годину.
#
#   06:00 — після нічної атаки і реаналізу ERA5 о 03:40: у пуші повні факти за ніч
#   12:20 — після відсічки о 12:00 і видачі прогнозу о 12:05: у пуші свіже число
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh 2>/dev/null || true

HOUR=$(TZ=Europe/Kyiv date +%-H)
MIN=$(TZ=Europe/Kyiv date +%-M)
if [ "${1:-}" != "--force" ]; then
    case "$HOUR:$(( MIN / 10 ))" in
        6:0|12:2) ;;                       # 06:00-06:09 або 12:20-12:29
        *) echo "$(TZ=Europe/Kyiv date '+%F %T') $HOUR:$MIN — не час публікації, пропущено"
           exit 0 ;;
    esac
fi

exec 9>data/locks/publish.lock
flock -n 9 || { echo "публікація вже виконується"; exit 0; }

.venv/bin/python ingest/export_release.py

if [ -z "$(git status --porcelain data/release)" ]; then
    echo "$(TZ=Europe/Kyiv date '+%F %T') набір не змінився — пушити нічого"
    exit 0
fi

# Заголовок комміту несе стан, а не слово «update»: у стрічці репозиторію
# видно, що саме змінилось, без відкривання дифа.
DAY=$(TZ=Europe/Kyiv date -d '12 hours ago' +%F)
STAT=$(.venv/bin/python - "$DAY" <<'PY'
import csv, sys
day = sys.argv[1]
rows = {r["raid_day"]: r for r in csv.DictReader(open("data/release/30_daily_features.csv"))}
r = rows.get(day, {})
alerts = round(float(r.get("y_alert_minutes") or 0))
trk = int(float(r.get("y_drone_tracks") or 0)) + int(float(r.get("y_missile_tracks") or 0))
p = [x for x in csv.DictReader(open("data/release/31_predictions.csv"))
     if x["raid_day"] == day and x["target"] == "attacked" and x["horizon"] == "1"]
pv = f", прогноз був {round(float(p[-1]['p'])*100)}%" if p else ""
print(f"{day}: тривог {alerts} хв, цілей {trk}{pv}")
PY
)

git add data/release
git commit -q -m "Дані: $STAT" -m "Автоматичне оновлення відкритого набору. $(git status --porcelain data/release | wc -l) файлів."
git push -q origin HEAD
echo "$(TZ=Europe/Kyiv date '+%F %T') опубліковано — $STAT"
