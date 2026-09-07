#!/usr/bin/env python3
"""Канал Повітряних Сил -> спостереження для лейблів.

З одного каналу беремо дві РІЗНІ речі, і плутати їх не можна:

1. Добове зведення (щоранку) — точні числа за ніч, але ПО КРАЇНІ:
   скільки запущено БпЛА і ракет, скільки збито. scope='ua'.

2. Повідомлення супроводу цілей у реальному часі — єдине, що взагалі
   існує з київською прив'язкою: «Реактивні БпЛА курсом на Київ»,
   «Балістика на Київ!». Це НЕ кількість бортів (одне повідомлення може
   означати групу), тому метрика чесно зветься *_tracks. scope='kyiv'.

Формат зведень мінявся за чотири роки: числа то цифрами, то словами
(«ЗБИТО П'ЯТЬ УДАРНИХ ДРОНІВ»), структура різна. Тому парсимо консервативно:
що впевнено не розпізналось — не вигадуємо, а лишаємо порожнім і рахуємо
в статистиці покриття. Кожне число зберігає уривок тексту, з якого взяте.
"""
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import db

CHANNEL = "kpszsu"
KYIV = ZoneInfo("Europe/Kyiv")
NL = "§¶"

WORDS = {
    "один": 1, "одну": 1, "одного": 1, "два": 2, "дві": 2, "двома": 2,
    "три": 3, "трьома": 3, "чотири": 4, "п'ять": 5, "пʼять": 5, "п’ять": 5,
    "шість": 6, "сім": 7, "вісім": 8, "дев'ять": 9, "девʼять": 9, "дев’ять": 9,
    "десять": 10, "одинадцять": 11, "дванадцять": 12, "тринадцять": 13,
    "чотирнадцять": 14, "п'ятнадцять": 15, "пʼятнадцять": 15,
    "шістнадцять": 16, "сімнадцять": 17, "вісімнадцять": 18,
    "дев'ятнадцять": 19, "двадцять": 20,
}

# Київська прив'язка. Місто і область розводимо: «на Київ» ≠ «Київщина».
RE_CITY   = re.compile(r"\bКиїв\b|\bКиєв|\bКиїв[ауі]\b|над Києвом|на Київ", re.I)
RE_OBLAST = re.compile(r"Київщин|Київської обл|Бориспіл|Бровар|Вишгород|"
                       r"Обухів|Фастів|Бучан|Біла Церква|Білоцерк|Ірпін|Васильків",
                       re.I)

RE_DRONE  = re.compile(r"бпла|шахед|shahed|герань|гербера|дрон|пародія|"
                       r"бандероль|s8000", re.I)
RE_BALL   = re.compile(r"балістик|іскандер|kn-23|с-400|кинджал|кинжал", re.I)
RE_MISSILE= re.compile(r"ракет|калібр|х-101|х-555|х-59|х-22|х-31|крилат", re.I)

# Зведення впізнаємо за заголовком, а не за наявністю чисел
RE_SUMMARY = re.compile(r"ЗБИТО|ПОДАВЛЕНО|У ніч на|Протягом ночі", re.I)


def raid_day(ts):
    return ((ts.astimezone(KYIV)) - timedelta(hours=12)).date()


def num(token):
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return WORDS.get(token)


def _find(patterns, text):
    """Перше число, що знайшлося хоч одним із шаблонів."""
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            for g in m.groups():
                v = num(g) if g else None
                if v is not None:
                    return v, text[max(0, m.start() - 40):m.end() + 40]
    return None, None


LAUNCHED_DRONES = [
    r"атакував(?:\w*)?\s+(\d+)[- ]?(?:ма)?\s*ударними\s+БпЛА",
    r"зафіксовано пуски\s+(\d+)",
    r"атакували\s+(\d+)[- ]?ма\s+ударними\s+БпЛА",
    r"атакували\s+([а-яїієґ']+)\s+ударними\s+БпЛА",
    r"(\d+)\s+ударн\w+\s+БпЛА",
]
DOWNED_TOTAL = [
    r"ЗБИТО/ПОДАВЛЕНО\s+(\d+)",
    r"збито/подавлено\s+(\d+)",
    r"ЗБИТО\s+(\d+)",
    r"вдалось збити\s+(\d+)",
    r"ЗБИТО\s+([А-ЯЇІЄҐ']+)\s",
]
LAUNCHED_MISSILES = [
    r"(\d+)\s+РАКЕТ",
    r"(\d+)\s+крилат\w+\s+ракет",
    r"(\d+)\s+балістичн\w+\s+ракет",
    r"([а-яїієґ']+)\s+керован\w+\s+авіаційн\w+\s+ракет",
]
IMPACT_LOC = [r"влучання[^.]{0,60}?на\s+(\d+)\s+локаці"]


def parse_summary(text):
    """-> dict метрика -> (значення, уривок). Порожній, якщо це не зведення."""
    out = {}
    for key, pats in (("drones_launched", LAUNCHED_DRONES),
                      ("missiles_launched", LAUNCHED_MISSILES),
                      ("impact_locations", IMPACT_LOC)):
        v, ev = _find(pats, text)
        if v is not None:
            out[key] = (v, ev)
    v, ev = _find(DOWNED_TOTAL, text)
    if v is not None:
        # заголовок дає СУМАРНО збитих цілей; розділити на дрони й ракети
        # можна не завжди, тому пишемо в окрему метрику
        out["targets_downed"] = (v, ev)
    return out


def track_kind(text):
    if RE_BALL.search(text):
        return "missile_tracks"
    if RE_MISSILE.search(text):
        return "missile_tracks"
    if RE_DRONE.search(text):
        return "drone_tracks"
    return None


def run():
    rows = db.query(f"""
        SELECT msg_id, posted_at, replace(text, chr(10), '{NL}')
        FROM tg_messages WHERE channel = '{CHANNEL}' ORDER BY msg_id""")

    summaries = {}          # raid_day -> {metric: (value, evidence)}
    tracks = {}             # (raid_day, metric) -> [count, приклад]
    n_sum = n_sum_parsed = n_track = 0

    for msg_id, ts_raw, raw in rows:
        text = raw.replace(NL, "\n")
        ts = datetime.fromisoformat(ts_raw.replace(" ", "T"))
        day = raid_day(ts)

        if RE_SUMMARY.search(text.split("\n")[0]) and len(text) > 300:
            n_sum += 1
            got = parse_summary(text)
            if got:
                n_sum_parsed += 1
                summaries.setdefault(day, {}).update(got)
            continue

        # супровід цілей: коротке повідомлення з київською прив'язкою
        if len(text) < 400 and (RE_CITY.search(text) or RE_OBLAST.search(text)):
            kind = track_kind(text)
            if kind:
                n_track += 1
                k = (day, kind)
                if k not in tracks:
                    tracks[k] = [0, msg_id, text[:200]]
                tracks[k][0] += 1

    # Явні НУЛІ. Без них у лейблі будуть самі одиниці, і модель навчиться
    # відповідати «так» завжди. Але нуль можна ставити тільки там, де джерело
    # того дня точно працювало: інакше мовчання каналу через збій стане
    # «атаки не було».
    alive = {}
    for msg_id, ts_raw, raw in rows:
        d = raid_day(datetime.fromisoformat(ts_raw.replace(" ", "T")))
        alive[d] = alive.get(d, 0) + 1
    ALIVE_MIN = 5      # менше повідомлень за добу — вважаємо, що каналу не було

    obs = []
    for day, metrics in summaries.items():
        for metric, (value, ev) in metrics.items():
            obs.append((day, None, CHANNEL, "official", metric, "ua",
                        value, None, (ev or "")[:500]))
    for (day, metric), (cnt, msg_id, sample) in tracks.items():
        obs.append((day, None, CHANNEL, "official", metric, "kyiv",
                    cnt, msg_id, sample))
    # супровідні повідомлення самі по собі є свідченням удару по місту
    days_attacked = {d for (d, m) in tracks}
    for day in days_attacked:
        obs.append((day, None, CHANNEL, "official", "attacked", "kyiv",
                    1, None, "є повідомлення супроводу цілей на Київ"))
    for day, n in alive.items():
        if day not in days_attacked and n >= ALIVE_MIN:
            obs.append((day, None, CHANNEL, "official", "attacked", "kyiv",
                        0, None, f"канал працював ({n} повідомлень), "
                                 f"жодного супроводу на Київ"))

    write(obs)
    return n_sum, n_sum_parsed, n_track, len(obs)


def write(obs):
    if not obs:
        return
    region_id = int(db.scalar("SELECT id FROM regions WHERE code='kyiv_city'"))
    rows = [(d, region_id, src, tier, metric, scope, val, ev_id, ev_txt)
            for d, _r, src, tier, metric, scope, val, ev_id, ev_txt in obs]
    db.copy_upsert(
        "attack_observations",
        ["raid_day", "region_id", "source", "tier", "metric", "scope",
         "value", "evidence_msg_id", "evidence_text"],
        rows,
        conflict="raid_day, source, metric, scope",
        update=("value", "evidence_msg_id", "evidence_text", "extracted_at"))


if __name__ == "__main__":
    with db.Run("kpszsu_parse", "backfill", {"channel": CHANNEL}) as r:
        need, cur = db.parse_cursor("kpszsu_parse", CHANNEL)
        if not need:
            r.skip(f"канал не виріс від минулого розбору (msg_id {cur})")
            print("  нових повідомлень немає — розбір пропущено")
            raise SystemExit(0)
        n_sum, n_parsed, n_track, n_obs = run()
        db.parse_done("kpszsu_parse", CHANNEL, cur, n_obs)
        r.rows_read, r.rows_written = n_sum + n_track, n_obs
        pct = 100 * n_parsed / n_sum if n_sum else 0
        print(f"  зведень {n_sum}, з них розібрано {n_parsed} ({pct:.0f}%), "
              f"повідомлень супроводу по Києву {n_track}, спостережень {n_obs}")
