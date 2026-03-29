"""
Test degli Endpoint FastAPI — usa TestClient per verificare
la risposta HTTP degli endpoint senza avviare il server reale.

Patches the DB connection to use an in-memory SQLite database.
"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set env vars BEFORE importing server
os.environ["ARGOS_API_KEY"] = ""  # Permissive mode for testing
os.environ["ADMIN_CHAT_ID"] = "12345"

import pytest
from unittest.mock import patch


def _make_test_db():
    """Creates an in-memory DB with the required tables."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS pending_emails (
        msg_id TEXT PRIMARY KEY, payload TEXT
    )""")

    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "db", "migrations", "001_telegram_module.py"
    )
    with open(migration_path) as f:
        content = f.read()
    start = content.index('MIGRATION_SQL = """') + len('MIGRATION_SQL = """')
    end = content.index('"""', start)
    conn.executescript(content[start:end])

    conn.execute("""CREATE TABLE IF NOT EXISTS tg_suspicious_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, content TEXT NOT NULL,
        category TEXT, risk_score REAL, blocked_by TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    return conn


# Patch the connection pool and db._get_conn BEFORE importing the app
_test_conn = _make_test_db()

_patcher1 = patch("src.db.connection.get_connection", return_value=_test_conn)
_patcher2 = patch("src.telegram.db._get_conn", return_value=_test_conn)
_patcher1.start()
_patcher2.start()

from fastapi.testclient import TestClient
from api.server import app

client = TestClient(app)


# ==========================================================================
# Health & Status Endpoints
# ==========================================================================

class TestHealthEndpoints:

    def test_status_returns_200(self):
        r = client.get("/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "online"
        assert "backend" in data

    def test_health_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200


# ==========================================================================
# Email HITL Endpoints
# ==========================================================================

class TestEmailEndpoints:

    def test_consume_nonexistent_returns_404(self):
        r = client.post("/pending_email/nonexistent-id/consume")
        assert r.status_code == 404


# ==========================================================================
# Telegram Endpoint — Basic Validation
# ==========================================================================

class TestTelegramEndpoint:

    def test_missing_fields_returns_422(self):
        """Missing required fields should return 422 Unprocessable Entity."""
        r = client.post("/telegram/chat", json={})
        assert r.status_code == 422
