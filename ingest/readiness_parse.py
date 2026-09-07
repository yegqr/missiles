#!/usr/bin/env python3
"""Зльоти носіїв зброї з уже зібраних повідомлень каналу ПС.

Нового збору не потребує: канал @kpszsu лежить у tg_messages повністю.

Що витягуємо:
  МіГ-31К     — «🛫 Зафіксовано зліт МіГ-31К з аеродрому Саваслейка»
                та парний «📢 Відбій загрози по МіГ-31К»
  Ту-95/Ту-160 — згадки стратегічної авіації у зведеннях і попередженнях
  «Калібр»     — надводні й підводні носії в Чорному морі

Обмеження, яке треба знати: у 2022 році канал таких попереджень не публікував
взагалі (0 зльотів за рік проти 139 у 2024). Тобто ознака існує з 2023 року,
і для 2022 її треба або шукати в іншому джерелі, або лишати порожньою —
але не нулем, бо нуль означав би «носії не злітали».
"""
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

CHANNEL = "kpszsu"
NL = "§¶"

RE_MIG_UP   = re.compile(r"зліт\s+\d*х?\s*(?:винищувач\w+\s+)?МіГ-?31|зафіксовано зліт МіГ", re.I)
RE_MIG_DOWN = re.compile(r"відбій\s+(?:загроз\w+\s+)?по\s+МіГ-?31", re.I)
RE_TU       = re.compile(r"Ту-?160|Ту-?95", re.I)
RE_TU_UP    = re.compile(r"зліт|злет|піднял|вилет|фіксується", re.I)
RE_KALIBR   = re.compile(r"носі\w+.{0,40}Калібр|Калібр.{0,40}Чорн\w+ мор|"
                         r"надводн\w+ носі|підводн\w+ човн", re.I)
RE_AIRFIELD = re.compile(r"аеродром\w*\s+[«\"']?([А-ЯЇІЄҐA-Z][а-яїієґ'’\-A-Za-z]+)", re.I)


def rows():
    for msg_id, ts, raw in db.query(
            f"SELECT msg_id, posted_at, replace(text, chr(10), '{NL}') "
            f"FROM tg_messages WHERE channel='{CHANNEL}' ORDER BY msg_id"):
        yield int(msg_id), datetime.fromisoformat(ts.replace(" ", "T")), \
              raw.replace(NL, "\n")


def airfield(text):
    m = RE_AIRFIELD.search(text)
    return m.group(1) if m else None


def run():
    out = []
    for msg_id, ts, text in rows():
        head = text[:400]

        if RE_MIG_DOWN.search(head):
            out.append((ts, "carrier", "mig31k", None, True, msg_id, head[:300]))
            continue
        if RE_MIG_UP.search(head):
            out.append((ts, "carrier", "mig31k", airfield(head), False, msg_id, head[:300]))
            continue
        # стратегічна авіація: згадка носія разом зі словом про зліт
        if RE_TU.search(head) and RE_TU_UP.search(head):
            plat = "tu160" if re.search(r"Ту-?160", head, re.I) else "tu95"
            out.append((ts, "carrier", plat, airfield(head), False, msg_id, head[:300]))
            continue
        if RE_KALIBR.search(head):
            out.append((ts, "carrier", "kalibr_ship", None, False, msg_id, head[:300]))

    db.copy_upsert(
        "readiness_signals",
        ["ts", "signal_type", "platform", "airfield", "is_standdown",
         "source", "msg_id", "evidence"],
        [(ts, st, pl, af, sd, CHANNEL, mid, ev)
         for ts, st, pl, af, sd, mid, ev in out],
        conflict="source, msg_id, signal_type")
    return len(out)


if __name__ == "__main__":
    with db.Run("readiness_parse", "backfill", {"channel": CHANNEL}) as r:
        need, cur = db.parse_cursor("readiness_parse", CHANNEL)
        if not need:
            r.skip(f"канал не виріс (msg_id {cur})")
            print("  нових повідомлень немає — розбір пропущено")
            raise SystemExit(0)
        n = run()
        db.parse_done("readiness_parse", CHANNEL, cur, n)
        r.rows_read = r.rows_written = n
        print(f"  сигналів носіїв: {n}")
