from db.database import get_conn


def get_preference(key):
    conn = get_conn()
    try:
        row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def set_preference(key, value):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO preferences(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"key": key, "value": value, "saved": True}


def list_preferences():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT key, value FROM preferences ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()
