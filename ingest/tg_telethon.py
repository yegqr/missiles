#!/usr/bin/env python3
"""Збір історії Telegram-каналів через MTProto (акаунти з OLIVER).

Веб-перегляд t.me/s/ працює без акаунта, але Telegram душить його паралелізм:
338 тисяч повідомлень качаються годинами. Через MTProto той самий обсяг іде
на порядок швидше і без здогадок про розмітку HTML.

Акаунти позичені з OLIVER (див. tg_accounts.py), по одному на канал,
з їхніми ж проксі. Пишемо в ті самі tg_messages, що й веб-обхід, тому
джерела взаємозамінні: що встигло зайти першим, те й лишається.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db
import tg_accounts

from telethon import TelegramClient
from telethon.sessions import StringSession
from python_socks import ProxyType

BATCH = 2000
_PROXY = {"socks5": ProxyType.SOCKS5, "socks4": ProxyType.SOCKS4,
          "http": ProxyType.HTTP}


def build_client(acc):
    name, api_id, api_hash, sess, proxy = acc
    p = None
    if proxy:
        scheme, host, port, user, pw = proxy
        p = (_PROXY[scheme], host, port, True, user, pw)
    return TelegramClient(StringSession(sess), api_id, api_hash, proxy=p)


def flush(channel, buf):
    if not buf:
        return 0
    n = db.copy_upsert("tg_messages",
                       ["channel", "msg_id", "posted_at", "text"],
                       buf, conflict="channel, msg_id")
    buf.clear()
    return n


async def collect(channel, mode, account_index=0, limit=None):
    accounts = tg_accounts.active_accounts()
    if not accounts:
        raise RuntimeError("в OLIVER немає активних акаунтів")
    acc = accounts[account_index % len(accounts)]
    print(f"  акаунт {acc[0]}")

    if mode == "incremental":
        known = db.scalar("SELECT max(msg_id) FROM tg_messages WHERE channel=%s",
                          (channel,))
        min_id = int(known) if known else 0
    else:
        min_id = 0

    client = build_client(acc)
    saved, buf, last_day = 0, [], None
    async with client:
        entity = await client.get_entity(channel)
        async for m in client.iter_messages(entity, reverse=True, min_id=min_id,
                                            limit=limit):
            if not m.message:
                continue
            buf.append((channel, m.id, m.date.isoformat(), m.message))
            if m.date.date() != last_day:
                last_day = m.date.date()
            if len(buf) >= BATCH:
                saved += flush(channel, buf)
                print(f"    {last_day}: {saved}", flush=True)
        saved += flush(channel, buf)

    db.sql("""
        INSERT INTO tg_scan_state (channel, min_msg_id, max_msg_id, updated_at)
        SELECT %s, min(msg_id), max(msg_id), now()
        FROM tg_messages WHERE channel = %s
        ON CONFLICT (channel) DO UPDATE SET
          min_msg_id = EXCLUDED.min_msg_id,
          max_msg_id = EXCLUDED.max_msg_id,
          updated_at = now()""", (channel, channel))
    return saved


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("channel")
    ap.add_argument("mode", choices=["backfill", "incremental"])
    ap.add_argument("--account", type=int, default=0)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    with db.Run(f"tg:{a.channel}", "backfill" if a.mode == "backfill" else "live",
                {"transport": "mtproto"}) as r:
        n = asyncio.run(collect(a.channel, a.mode, a.account, a.limit))
        r.rows_read = r.rows_written = n
        total = db.scalar("SELECT count(*) FROM tg_messages WHERE channel=%s",
                          (a.channel,))
        print(f"  збережено {n}, всього по каналу {total}")
