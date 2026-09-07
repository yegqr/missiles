#!/usr/bin/env python3
"""Сирі повідомлення @air_alert_ua -> тривоги та загрози.

Розбір робиться з бази, не з мережі: канал качається один раз (tg_crawl.py),
далі правила можна міняти й перепарсювати скільки завгодно.

Формати повідомлень у каналі:
  🔴  ЧЧ:ХХ Повітряна тривога в <місце>            -> початок тривоги
  🟢  ЧЧ:ХХ Відбій тривоги в <місце>               -> відбій
  🟡  ЧЧ:ХХ Відбій тривоги в <місце>               -> відбій по цьому місцю,
      Зверніть увагу, тривога ще триває у: …          у вкладених — триває
  🔴🔴 ЧЧ:ХХ Загроза ударних БпЛА в <місце>        -> загроза, НЕ тривога
  🟡  ЧЧ:ХХ Відбій загрози застосування КАБів      -> зняття загрози
Останній рядок — хештеги місць. Саме вони, а не текст, визначають територію.
"""
import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

CHANNEL = "air_alert_ua"
MAX_ALERT = timedelta(hours=24)   # запобіжник, якщо повідомлення про відбій загубилось
NL = "§¶"                          # маркер переносу рядка: psql віддає все одним рядком

HASHTAGS = {
    "#м_київ": "kyiv_city",
    "#київська_область": "kyiv_oblast",
    "#вишгородський_район": "kyiv_obl_vyshhorod",
    "#броварський_район": "kyiv_obl_brovary",
    "#бориспільський_район": "kyiv_obl_boryspil",
    "#обухівський_район": "kyiv_obl_obukhiv",
    "#бучанський_район": "kyiv_obl_bucha",
    "#фастівський_район": "kyiv_obl_fastiv",
    "#білоцерківський_район": "kyiv_obl_bila_tserkva",
}

THREAT_PATTERNS = [
    ("ballistic", r"балістич"),
    ("kab",       r"керован\w*\s+авіаційн\w*\s+бомб|каб"),
    ("drone",     r"бпла|дрон"),
    ("missile",   r"ракетн"),
    ("aircraft",  r"авіаці"),
    ("artillery", r"артобстріл|артилер"),
]


def threat_type(text):
    low = text.lower()
    for name, pat in THREAT_PATTERNS:
        if re.search(pat, low):
            return name
    return "other"


def classify(first_line, body):
    """-> ('start'|'end'|'threat'|'threat_off'|None, тип загрози)"""
    if "Відбій тривоги" in first_line:
        return "end", None
    if "Відбій" in first_line:
        return "threat_off", threat_type(first_line)
    low = first_line.lower()
    if "загроза" in low or "небезпека" in low:
        return "threat", threat_type(first_line)
    if "Повітряна тривога" in first_line:
        return "start", None
    # трапляються обрізані рядки на кшталт "🟡 10:39 к" — впізнаємо за тілом
    if "тривога ще триває" in body:
        return "end", None
    if first_line.startswith("🔴"):
        return "start", None
    return None, None


def load_messages():
    """Тільки повідомлення, що згадують наші території, у порядку id."""
    like = " OR ".join(f"lower(text) LIKE '%{h}%'" for h in HASHTAGS)
    rows = db.query(f"""
        SELECT msg_id, posted_at, replace(text, chr(10), '{NL}')
        FROM tg_messages
        WHERE channel = '{CHANNEL}' AND ({like})
        ORDER BY msg_id""")
    for msg_id, ts, text in rows:
        yield int(msg_id), ts, text.replace(NL, "\n")


def locations(text):
    """Коди регіонів із хештегів останнього рядка."""
    last = text.strip().split("\n")[-1].lower()
    return [HASHTAGS[h] for h in last.split() if h in HASHTAGS]


def check_complete():
    """Розбір має сенс лише на суцільній історії.

    Обхід іде блоками id паралельно, і поки він не завершився, повідомлення
    в базі рвані: автомат станів побачить початок тривоги без відбою і навигадує
    інтервалів. Тому за замовчуванням парсимо тільки повний канал.
    """
    row = db.query(f"SELECT min_msg_id, max_msg_id FROM tg_scan_state "
                   f"WHERE channel='{CHANNEL}'")
    if not row or row[0][0] in (None, ''):
        return False, "канал ще не обходили"
    lo, hi = int(row[0][0]), int(row[0][1])
    have = int(db.scalar(f"SELECT count(*) FROM tg_messages WHERE channel='{CHANNEL}'"))
    # у каналі є видалені повідомлення, тому вимагаємо не 100%, а щільність
    density = have / max(hi - lo + 1, 1)
    if lo > 100:
        return False, f"історія обірвана знизу: найменший id {lo}"
    if density < 0.9:
        return False, f"забагато прогалин: {have} повідомлень на діапазон {lo}–{hi}"
    return True, f"повідомлень {have}, id {lo}–{hi}"


def run():
    ids = {c: int(i) for c, i in db.query("SELECT code, id FROM regions")}
    open_alert = {}
    alerts, threats = [], []
    seen = unparsed = 0

    for msg_id, ts_raw, text in load_messages():
        seen += 1
        lines = text.strip().split("\n")
        kind, tt = classify(lines[0], text)
        locs = locations(text)
        if not locs:
            continue
        if kind is None:
            unparsed += 1
            continue
        ts = datetime.fromisoformat(ts_raw.replace(" ", "T"))

        for code in locs:
            if kind == "start":
                prev = open_alert.get(code)
                if prev:
                    alerts.append((code, prev[0], min(ts, prev[0] + MAX_ALERT)))
                open_alert[code] = (ts, msg_id)
            elif kind == "end":
                prev = open_alert.pop(code, None)
                if prev:
                    alerts.append((code, prev[0], ts))
            elif kind == "threat":
                threats.append((code, ts, tt, msg_id))

    for code, (started, _mid) in open_alert.items():
        alerts.append((code, started, None))

    # повний перерозбір: спершу прибираємо попередній результат цього джерела,
    # інакше змінені правила лишать по собі старі інтервали
    db.sql("DELETE FROM alerts WHERE source='tg_air_alert_ua'")
    write_alerts(ids, alerts)
    write_threats(ids, threats)
    return seen, len(alerts), len(threats), unparsed


def write_alerts(ids, alerts):
    if not alerts:
        return
    tsv = "\n".join("\t".join([
        str(ids[c]), s.isoformat(), f.isoformat() if f else "\\N", "tg_air_alert_ua"
    ]) for c, s, f in alerts)
    db.script(f"""
CREATE TEMP TABLE _stage_tga (region_id smallint, started_at timestamptz,
                              finished_at timestamptz, source text);
COPY _stage_tga FROM STDIN;
{tsv}
\\.
INSERT INTO alerts (region_id, started_at, finished_at, source)
SELECT DISTINCT ON (region_id, started_at) region_id, started_at, finished_at, source
FROM _stage_tga ORDER BY region_id, started_at, finished_at DESC NULLS LAST
ON CONFLICT (source, region_id, alert_type, started_at) DO UPDATE
   SET finished_at = EXCLUDED.finished_at, updated_at = now()
   WHERE alerts.finished_at IS DISTINCT FROM EXCLUDED.finished_at;
""")


def write_threats(ids, threats):
    if not threats:
        return
    tsv = "\n".join("\t".join([
        str(ids[c]), ts.isoformat(), tt, str(mid)
    ]) for c, ts, tt, mid in threats)
    db.script(f"""
CREATE TEMP TABLE _stage_tgt (region_id smallint, ts timestamptz,
                              threat_type text, msg_id bigint);
COPY _stage_tgt FROM STDIN;
{tsv}
\\.
INSERT INTO threat_events (region_id, ts, threat_type, msg_id)
SELECT DISTINCT ON (region_id, ts, threat_type) region_id, ts, threat_type, msg_id
FROM _stage_tgt ORDER BY region_id, ts, threat_type, msg_id
ON CONFLICT (region_id, ts, threat_type) DO NOTHING;
""")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-partial", action="store_true",
                    help="розібрати навіть неповний канал (результат буде рваний)")
    args = ap.parse_args()

    ok, why = check_complete()
    print(f"  стан обходу: {why}")

    with db.Run("tg_parse", "backfill", {"channel": CHANNEL}) as r:
        if not ok and not args.allow_partial:
            r.skip(f"чекаємо на завершення обходу — {why}")
            print("  розбір пропущено (див. --allow-partial)")
            raise SystemExit(0)
        need, cur = db.parse_cursor("tg_parse", CHANNEL)
        if not need and not args.allow_partial:
            r.skip(f"канал не виріс (msg_id {cur})")
            print("  нових повідомлень немає — розбір пропущено")
            raise SystemExit(0)
        seen, n_alerts, n_threats, unparsed = run()
        db.parse_done("tg_parse", CHANNEL, cur, n_alerts + n_threats)
        r.rows_read, r.rows_written = seen, n_alerts + n_threats
        print(f"  київських повідомлень {seen}, тривог {n_alerts}, "
              f"загроз {n_threats}, не розібрано {unparsed}")
