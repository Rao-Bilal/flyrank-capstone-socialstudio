import os
import sqlite3

from app.db import init_db, get_connection, DB_PATH


def test_init_db_creates_tables():
    # clean slate
    if DB_PATH.exists():
        os.remove(DB_PATH)

    init_db()

    conn = get_connection()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {row["name"] for row in tables}
    conn.close()

    assert "campaigns" in table_names
    assert "social_post_entries" in table_names