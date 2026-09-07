#!/usr/bin/env python3
"""Обхід каналу @air_alert_ua через публічний веб-перегляд t.me/s/<канал>.

Навіщо. По м. Києву є реєстр КМДА, по області — нічого: єдине первинне джерело
офіційних тривог у районах Київщини це канал системи оповіщення. Веб-перегляд
віддає всю історію з повідомлення №1 (14.03.2022) без токена і без акаунта.

Що робить. Складає сирі повідомлення в tg_messages — усі, не тільки київські:
у тому ж каналі йдуть повідомлення про тип загрози (БпЛА, балістика, авіація),
і мати їх у себе означає, що перепарсити можна будь-коли, не перекачуючи канал.

Сторінка ?before=N віддає 20 повідомлень з id < N. Історія обходиться блоками
id, кожен блок послідовно — так обхід паралелиться, а перекриття на межах
блоків нешкідливі, бо запис іде через ON CONFLICT.
"""
import argparse
import html
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

CHANNEL = "air_alert_ua"
BASE = "https://t.me/s/{channel}"
UA = "Mozilla/5.0 (X11; Linux x86_64) KSE-missiles/1.0"
PAGE = 20

_print_lock = threading.Lock()


class MessageParser(HTMLParser):
    """Витягає (msg_id, posted_at, text) з веб-перегляду каналу."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.messages = {}
        self.cur_id = None
        self.text_depth = 0     # 0 = поза текстовим блоком
        self.buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")

        if "tgme_widget_message" in cls and a.get("data-post"):
            post = a["data-post"]
            if "/" in post:
                self.cur_id = int(post.rsplit("/", 1)[1])
                self.messages.setdefault(self.cur_id, {"text": "", "ts": None})

        if self.text_depth:
            # рахуємо вкладені div, щоб не обірвати текст на першому </div>
            if tag == "div":
                self.text_depth += 1
            elif tag == "br":
                self.buf.append("\n")
        elif "js-message_text" in cls and self.cur_id is not None:
            self.text_depth = 1
            self.buf = []

        if tag == "time" and a.get("datetime") and self.cur_id is not None:
            # у блоці може бути кілька <time>; час самого повідомлення — останній
            self.messages[self.cur_id]["ts"] = a["datetime"]

    def handle_endtag(self, tag):
        if self.text_depth and tag == "div":
            self.text_depth -= 1
            if self.text_depth == 0 and self.cur_id is not None:
                self.messages[self.cur_id]["text"] = "".join(self.buf).strip()

    def handle_data(self, data):
        if self.text_depth:
            self.buf.append(data)


def fetch_page(channel, before=None, attempts=5):
    url = BASE.format(channel=channel)
    if before is not None:
        url += f"?before={before}"
    delay = 1.0
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < attempts - 1:
                time.sleep(delay); delay *= 2; continue
            raise
        except Exception:
            if i < attempts - 1:
                time.sleep(delay); delay *= 2; continue
            raise


def parse_page(html_text):
    p = MessageParser()
    p.feed(html_text)
    out = []
    for mid, m in p.messages.items():
        if m["ts"] and m["text"]:
            out.append((mid, m["ts"], m["text"]))
    return sorted(out)


def store(channel, rows):
    return db.copy_upsert(
        "tg_messages",
        ["channel", "msg_id", "posted_at", "text"],
        [(channel, mid, ts, text) for mid, ts, text in rows],
        conflict="channel, msg_id")


def newest_id(channel):
    rows = parse_page(fetch_page(channel))
    return rows[-1][0] if rows else None


def walk_block(channel, hi, lo, pause):
    """Йде вниз від hi до lo. Повертає кількість збережених повідомлень."""
    saved, before = 0, hi
    while before > lo:
        rows = parse_page(fetch_page(channel, before))
        if not rows:
            break
        saved += store(channel, rows)
        nxt = rows[0][0]
        if nxt >= before:      # захист від зациклення
            break
        before = nxt
        time.sleep(pause)
    return saved


def crawl_backfill(channel, workers=4, pause=0.15):
    top = newest_id(channel)
    if not top:
        raise RuntimeError("не вдалося прочитати канал")
    with _print_lock:
        print(f"  найновіше повідомлення: {channel}/{top}")
    # ділимо простір id на блоки і йдемо кожен послідовно вниз
    block = max(2000, top // (workers * 12))
    bounds = list(range(top + 1, 0, -block))
    tasks = [(bounds[i], max(bounds[i] - block, 0)) for i in range(len(bounds))]

    done = [0]
    def job(t):
        hi, lo = t
        n = walk_block(channel, hi, lo, pause)
        with _print_lock:
            done[0] += 1
            print(f"  блок {lo}–{hi}: {n} повідомлень  ({done[0]}/{len(tasks)})",
                  flush=True)
        return n

    with ThreadPoolExecutor(max_workers=workers) as ex:
        total = sum(ex.map(job, tasks))
    return total, top


def crawl_incremental(channel, pause=0.15):
    """Тягне новіші повідомлення, доки не впремося у вже збережене."""
    known = db.scalar(
        f"SELECT max(msg_id) FROM tg_messages WHERE channel='{channel}'")
    known = int(known) if known else 0
    saved, before = 0, None
    while True:
        rows = parse_page(fetch_page(channel, before))
        if not rows:
            break
        saved += store(channel, [r for r in rows if r[0] > known])
        if rows[0][0] <= known + 1:
            break
        before = rows[0][0]
        time.sleep(pause)
    return saved


def update_state(channel):
    db.sql(f"""
INSERT INTO tg_scan_state (channel, min_msg_id, max_msg_id, updated_at)
SELECT '{channel}', min(msg_id), max(msg_id), now()
FROM tg_messages WHERE channel='{channel}'
ON CONFLICT (channel) DO UPDATE SET
  min_msg_id = EXCLUDED.min_msg_id,
  max_msg_id = EXCLUDED.max_msg_id,
  updated_at = now();""")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backfill", "incremental"])
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pause", type=float, default=0.15)
    a = ap.parse_args()

    mode = "backfill" if a.mode == "backfill" else "live"
    with db.Run(f"tg:{a.channel}", mode, {"workers": a.workers}) as run:
        if a.mode == "backfill":
            n, top = crawl_backfill(a.channel, a.workers, a.pause)
        else:
            n = crawl_incremental(a.channel, a.pause)
        update_state(a.channel)
        run.rows_read = run.rows_written = n
        total = db.scalar(f"SELECT count(*) FROM tg_messages WHERE channel='{a.channel}'")
        print(f"  збережено {n}, всього у базі {total}")
