"""
Shared pytest fixtures for the ARGOS-2 test suite.

patch_db is autouse so every test automatically runs against an isolated
in-memory SQLite database — no real DB required, no test pollution.
"""

import os
os.environ["DB_BACKEND"] = "sqlite"

import sqlite3

import pytest

os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")


def _create_test_db() -> sqlite3.Connection:
    """Creates an in-memory SQLite database with the full project schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src",
        "db",
        "migrations",
        "001_telegram_module.py",
    )
    with open(migration_path) as f:
        content = f.read()
    start = content.index('MIGRATION_SQL = """') + len('MIGRATION_SQL = """')
    end = content.index('"""', start)
    conn.executescript(content[start:end])

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_suspicious_memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            content     TEXT NOT NULL,
            category    TEXT,
            risk_score  REAL,
            blocked_by  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_rate_limits (
            user_id       INTEGER NOT NULL,
            window_start  TEXT NOT NULL,
            hit_count     INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, window_start)
        )
    """)
    conn.commit()
    return conn


@pytest.fixture(autouse=True)
def patch_db(monkeypatch):
    """
    Patches get_connection in all relevant modules to use an isolated
    in-memory SQLite database. Applied automatically to every test.
    """
    conn = _create_test_db()

    import src.core.rate_limit as rl_module
    import src.db.connection as conn_module
    import src.telegram.db as db_module

    monkeypatch.setattr(db_module, "get_connection", lambda: conn)
    monkeypatch.setattr(rl_module, "get_connection", lambda: conn)
    monkeypatch.setattr(conn_module, "get_connection", lambda: conn)

    yield conn
    conn.close()
