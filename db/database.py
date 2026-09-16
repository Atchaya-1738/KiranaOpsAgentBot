import os
import time
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "store.db"),
)
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)


def get_conn():
    """
    A plain connection for reads and simple single-statement writes.
    autocommit-ish (isolation_level=None) so callers control transactions explicitly
    when they need atomicity (see immediate_transaction below).
    """
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


@contextmanager
def immediate_transaction():
    """
    Opens BEGIN IMMEDIATE, which grabs SQLite's write lock up front instead of
    on first write. This is the mechanism that makes stock mutations safe under
    concurrency: two 'sale' and 'stock-in' operations racing each other will
    serialize here instead of interleaving and corrupting qty_on_hand.

    In WAL mode, SQLite still only allows one writer at a time; BEGIN IMMEDIATE
    just makes sure *we* hold that slot before we start reading values we're
    about to base a write decision on (the oversell check in particular).
    """
    conn = get_conn()
    conn.execute("PRAGMA journal_mode = WAL;")
    attempts = 0
    while True:
        try:
            conn.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError as e:
            attempts += 1
            if attempts > 8 or "locked" not in str(e).lower():
                conn.close()
                raise
            time.sleep(0.05 * attempts)
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def init_db():
    conn = get_conn()
    conn.execute("PRAGMA journal_mode = WAL;")
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.close()
