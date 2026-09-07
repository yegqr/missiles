"""Доступ до Postgres.

Основний шлях — psycopg (.venv). Раніше все йшло через `docker exec psql`;
на обході каналу це поклало машину: кожен запис породжував окремий процес,
а їх десятки тисяч. Тому тепер справжнє з'єднання, а psql лишився запасним
шляхом для скриптів, які запускають системним python3 без venv.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTAINER = os.environ.get("PG_CONTAINER", "missiles-pg")


def _env():
    env = {}
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k, v in os.environ.items():
        if k.startswith("POSTGRES") or k in ("DATABASE_URL", "ALERTS_IN_UA_TOKEN"):
            env[k] = v
    return env


ENV = _env()
DB = ENV.get("POSTGRES_DB", "missiles")
USER = ENV.get("POSTGRES_USER", "missiles")
DSN = ENV.get("DATABASE_URL")

try:
    import psycopg
    from psycopg_pool import ConnectionPool
    _pool = ConnectionPool(DSN, min_size=1, max_size=10, open=True) if DSN else None
except Exception:
    psycopg = None
    _pool = None

if _pool:
    import atexit
    atexit.register(_pool.close)


# --- запасний шлях: psql у контейнері -----------------------------------------

def _psql(args, stdin=None):
    cmd = ["docker", "exec", "-i", CONTAINER, "psql", "-v", "ON_ERROR_STOP=1",
           "-U", USER, "-d", DB] + args
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


# --- публічний інтерфейс -------------------------------------------------------

def sql(q, params=None):
    """Виконати запит без результату."""
    if _pool:
        with _pool.connection() as c:
            c.execute(q, params)
        return ""
    return _psql(["-c", q])


def script(text):
    """Багатокомандний скрипт із COPY ... FROM STDIN. Завжди через psql:
    у ньому працює метакоманда \\. і temp-таблиці в межах однієї сесії."""
    return _psql(["-f", "-"], stdin=text)


def query(q, params=None):
    """Список кортежів (усе як текст, щоб не залежати від шляху доступу)."""
    if _pool:
        with _pool.connection() as c:
            cur = c.execute(q, params)
            if cur.description is None:
                return []
            return [tuple("" if v is None else str(v) for v in row)
                    for row in cur.fetchall()]
    out = _psql(["-tAF", "\t", "-c", q])
    return [line.split("\t") for line in out.splitlines() if line]


def scalar(q, params=None):
    rows = query(q, params)
    return rows[0][0] if rows else None


def copy_rows(table, columns, rows):
    """Bulk-вставка через COPY. Повертає кількість рядків."""
    rows = list(rows)
    if not rows:
        return 0
    if _pool:
        cols = ", ".join(columns)
        with _pool.connection() as c:
            with c.cursor().copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row(r)
        return len(rows)
    tsv = "\n".join("\t".join(
        "\\N" if v is None else str(v).replace("\\", "\\\\")
        .replace("\t", " ").replace("\n", "\\n") for v in r) for r in rows)
    _psql(["-c", f"COPY {table} ({', '.join(columns)}) FROM STDIN"], stdin=tsv + "\n")
    return len(rows)


def copy_upsert(table, columns, rows, conflict, update=()):
    """COPY у тимчасову таблицю -> INSERT ... ON CONFLICT у цільову.

    Все в одному з'єднанні, тому temp-таблиця видима і живе рівно стільки,
    скільки треба. Повертає кількість поданих рядків.
    """
    rows = list(rows)
    if not rows:
        return 0
    cols = ", ".join(columns)
    setter = ", ".join(f"{c} = EXCLUDED.{c}" for c in update)
    action = f"DO UPDATE SET {setter}" if update else "DO NOTHING"
    if not _pool:
        raise RuntimeError("copy_upsert потребує psycopg (.venv)")
    with _pool.connection() as c:
        c.execute(f"CREATE TEMP TABLE _stage (LIKE {table} INCLUDING DEFAULTS) "
                  f"ON COMMIT DROP")
        with c.cursor().copy(f"COPY _stage ({cols}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
        c.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _stage "
                  f"ON CONFLICT ({conflict}) {action}")
    return len(rows)


def parse_cursor(parser, channel):
    """Чи виріс канал від минулого розбору. -> (треба_розбирати, поточний_max_id)"""
    cur = scalar("SELECT max(msg_id) FROM tg_messages WHERE channel=%s", (channel,))
    cur = int(cur) if cur else 0
    seen = scalar("SELECT last_msg_id FROM parse_state WHERE parser=%s", (parser,))
    seen = int(seen) if seen else -1
    return cur > seen, cur


def parse_done(parser, channel, msg_id, rows_written):
    sql("""INSERT INTO parse_state (parser, channel, last_msg_id, last_run_at, rows_written)
           VALUES (%s, %s, %s, now(), %s)
           ON CONFLICT (parser) DO UPDATE SET
             channel=EXCLUDED.channel, last_msg_id=EXCLUDED.last_msg_id,
             last_run_at=now(), rows_written=EXCLUDED.rows_written""",
        (parser, channel, msg_id, rows_written))


class Run:
    """Контекст-менеджер, що логує захід у ingest_runs."""

    def __init__(self, source, mode, params=None):
        self.source, self.mode, self.params = source, mode, params or {}
        self.rows_read = 0
        self.rows_written = 0
        self.id = None

    def __enter__(self):
        import json
        p = json.dumps(self.params, ensure_ascii=False).replace("'", "''")
        self.id = scalar(
            f"INSERT INTO ingest_runs (source, mode, params) "
            f"VALUES ('{self.source}', '{self.mode}', '{p}'::jsonb) RETURNING id")
        return self

    def skip(self, reason):
        """Крок свідомо нічого не зробив — це не помилка і не успіх."""
        import json
        p = json.dumps({**self.params, "reason": reason},
                       ensure_ascii=False).replace("'", "''")
        sql(f"UPDATE ingest_runs SET finished_at=now(), status='skipped', "
            f"params='{p}'::jsonb WHERE id={self.id}")
        self.skipped = True

    def __exit__(self, exc_type, exc, tb):
        # skip() уже проставив статус; sys.exit(0) усередині блоку прилітає
        # сюди як SystemExit і не повинен перетворити пропуск на помилку
        if getattr(self, "skipped", False):
            return False
        if exc:
            err = str(exc).replace("'", "''")[:4000]
            sql(f"UPDATE ingest_runs SET finished_at=now(), status='error', "
                f"error='{err}', rows_read={self.rows_read}, "
                f"rows_written={self.rows_written} WHERE id={self.id}")
        else:
            sql(f"UPDATE ingest_runs SET finished_at=now(), status='ok', "
                f"rows_read={self.rows_read}, rows_written={self.rows_written} "
                f"WHERE id={self.id}")
        return False
