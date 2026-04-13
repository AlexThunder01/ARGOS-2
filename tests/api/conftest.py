"""
Conftest locale per i test FastAPI.

Applica il patch su get_connection() PRIMA che pytest importi test_api.py
e PRIMA che api.server inizializzi il lifespan. In questo modo il TestClient
usa sempre il DB in-memory isolato, senza inquinare la connessione degli
altri test.
"""

import os
import sqlite3
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

os.environ["DB_BACKEND"] = "sqlite"
os.environ.setdefault("ARGOS_API_KEY", "")
os.environ.setdefault("ARGOS_PERMISSIVE_MODE", "true")
os.environ.setdefault("ADMIN_CHAT_ID", "12345")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")

import pytest


def _create_api_test_db() -> sqlite3.Connection:
    """DB in-memory dedicato ai test API."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
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
        CREATE TABLE IF NOT EXISTS pending_emails (
            msg_id TEXT PRIMARY KEY, payload TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_suspicious_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, content TEXT NOT NULL,
            category TEXT, risk_score REAL, blocked_by TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_rate_limits (
            user_id INTEGER NOT NULL, window_start TEXT NOT NULL,
            hit_count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, window_start)
        )
    """)
    conn.commit()
    return conn


# Crea e patcha la connessione PRIMA che qualsiasi test (o import a livello
# di modulo in test_api.py) venga eseguito.
_api_conn = _create_api_test_db()

import unittest.mock as _mock

_p1 = _mock.patch("src.db.connection.get_connection", return_value=_api_conn)
_p2 = _mock.patch("src.telegram.db.get_connection", return_value=_api_conn)
_p3 = _mock.patch("src.core.rate_limit.get_connection", return_value=_api_conn)
_p1.start()
_p2.start()
_p3.start()


@pytest.fixture(autouse=True)
def api_db(monkeypatch):
    """Assicura che ogni test API usi il DB in-memory."""
    monkeypatch.setattr("src.db.connection.get_connection", lambda: _api_conn)
    monkeypatch.setattr("src.telegram.db.get_connection", lambda: _api_conn)
    monkeypatch.setattr("src.core.rate_limit.get_connection", lambda: _api_conn)
    # Azzera i contatori rate limit prima di ogni test per evitare interferenze
    _api_conn.execute("DELETE FROM tg_rate_limits")
    _api_conn.commit()
    yield _api_conn
