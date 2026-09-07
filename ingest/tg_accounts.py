"""Позичені Telegram-акаунти з проєкту OLIVER.

Свої акаунти для цього заводити не треба: в OLIVER уже є пул авторизованих
сесій із проксі. Читаємо його БАЗУ ЛИШЕ НА ЧИТАННЯ і нічого там не міняємо.
Секрети не копіюються до MISSILES — беруться з .env OLIVER під час запуску.
"""
import os
import re
import subprocess
from pathlib import Path

OLIVER = Path(os.environ.get("OLIVER_ROOT", "/home/ye/PROJECTS/OLIVER"))
OLIVER_CONTAINER = os.environ.get("OLIVER_PG_CONTAINER", "oliver-pg")


def _dsn():
    env = (OLIVER / ".env").read_text()
    m = re.search(r"^DATABASE_URL=(.+)$", env, re.M)
    if not m:
        raise RuntimeError("не знайшов DATABASE_URL у .env OLIVER")
    url = m.group(1).strip()
    m = re.match(r".*://([^:]+):([^@]+)@[^/]+/(\w+)", url)
    if not m:
        raise RuntimeError("не розібрав DATABASE_URL OLIVER")
    return m.group(1), m.group(2), m.group(3)


def _q(sql):
    user, pw, dbname = _dsn()
    r = subprocess.run(
        ["docker", "exec", "-i", "-e", f"PGPASSWORD={pw}", OLIVER_CONTAINER,
         "psql", "-tAF", "\x1f", "-U", user, "-d", dbname, "-c", sql],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"OLIVER psql: {r.stderr.strip()}")
    return [line.split("\x1f") for line in r.stdout.splitlines() if line]


def active_accounts():
    """Список (name, api_id, api_hash, session_string, proxy|None)."""
    rows = _q("""
        SELECT a.name, a.api_id, a.api_hash, a.session_string,
               COALESCE(p.scheme::text, ''), COALESCE(p.host, ''),
               COALESCE(p.port::text, ''), COALESCE(p.username, ''),
               COALESCE(p.password, '')
        FROM accounts a
        LEFT JOIN proxies p ON p.id = a.proxy_id
        WHERE a.status = 'active' AND a.session_string IS NOT NULL
        ORDER BY a.id""")
    out = []
    for name, api_id, api_hash, sess, scheme, host, port, puser, ppass in rows:
        proxy = None
        if scheme and host and port:
            proxy = (scheme, host, int(port), puser or None, ppass or None)
        out.append((name, int(api_id), api_hash, sess, proxy))
    return out


if __name__ == "__main__":
    for name, api_id, _h, sess, proxy in active_accounts():
        print(f"{name:20} api_id={api_id} сесія={'є' if sess else 'нема'} "
              f"проксі={proxy[1] if proxy else 'без'}")
