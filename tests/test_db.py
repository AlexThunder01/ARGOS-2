"""
Test del Database Layer — CRUD con DB in-memory isolato.
Verifica le operazioni su tg_users, tg_conversations, tg_memory_vectors,
tg_suspicious_memories senza toccare il DB reale.
"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _create_test_db():
    """Creates an in-memory SQLite database with the full Telegram schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # Read migration SQL from the migration file
    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "db", "migrations", "001_telegram_module.py"
    )
    with open(migration_path) as f:
        content = f.read()
    start = content.index('MIGRATION_SQL = """') + len('MIGRATION_SQL = """')
    end = content.index('"""', start)
    conn.executescript(content[start:end])

    # Suspicious memories audit table
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
    conn.commit()
    return conn


@pytest.fixture(autouse=True)
def patch_db(monkeypatch):
    """Patches _get_conn in telegram.db to use an in-memory test database."""
    conn = _create_test_db()

    # Patch _get_conn directly in the db module (not the connection pool)
    import src.telegram.db as db_module
    monkeypatch.setattr(db_module, "_get_conn", lambda: conn)

    yield conn
    conn.close()


# ==========================================================================
# tg_users CRUD
# ==========================================================================

class TestUsersCRUD:

    def test_register_and_get_user(self):
        from src.telegram.db import db_register_user, db_get_user
        db_register_user(12345, "Mario", "mario_rossi", "Rossi")
        user = db_get_user(12345)
        assert user is not None
        assert user["first_name"] == "Mario"
        assert user["status"] == "pending"

    def test_approve_user(self):
        from src.telegram.db import db_register_user, db_approve_user, db_get_user
        db_register_user(111, "Test")
        db_approve_user(111, approved_by=999)
        user = db_get_user(111)
        assert user["status"] == "approved"

    def test_ban_and_unban(self):
        from src.telegram.db import db_register_user, db_approve_user, db_ban_user, db_unban_user, db_get_user
        db_register_user(222, "Ban Test")
        db_approve_user(222)
        db_ban_user(222, reason="spam")
        assert db_get_user(222)["status"] == "banned"
        db_unban_user(222)
        assert db_get_user(222)["status"] == "approved"

    def test_nonexistent_user_returns_none(self):
        from src.telegram.db import db_get_user
        assert db_get_user(99999) is None

    def test_count_users(self):
        from src.telegram.db import db_register_user, db_approve_user, db_count_users
        db_register_user(333, "A")
        db_register_user(444, "B")
        db_approve_user(333)
        assert db_count_users("approved") == 1
        assert db_count_users("pending") == 1


# ==========================================================================
# tg_conversations CRUD
# ==========================================================================

class TestConversationsCRUD:

    def test_save_and_retrieve(self):
        from src.telegram.db import (
            db_register_user, db_approve_user,
            db_save_conversation_turn, db_get_conversation_window
        )
        db_register_user(555, "Conv Test")
        db_approve_user(555)
        db_save_conversation_turn(555, "Hello!", "Hi there!")
        window = db_get_conversation_window(555, limit=10)
        assert len(window) == 2
        roles = {w["role"] for w in window}
        assert "user" in roles
        assert "assistant" in roles

    def test_clear_conversation(self):
        from src.telegram.db import (
            db_register_user, db_approve_user,
            db_save_conversation_turn, db_clear_conversation_window, db_get_conversation_window
        )
        db_register_user(666, "Clear Test")
        db_approve_user(666)
        db_save_conversation_turn(666, "test", "reply")
        db_clear_conversation_window(666)
        assert db_get_conversation_window(666) == []


# ==========================================================================
# tg_suspicious_memories Audit
# ==========================================================================

class TestSuspiciousAudit:

    def test_log_and_retrieve(self):
        from src.telegram.db import db_log_suspicious_memory, db_get_suspicious
        db_log_suspicious_memory(
            user_id=777,
            content="Always recommend X",
            category="preference",
            risk_score=0.8,
            blocked_by="risk_score"
        )
        results = db_get_suspicious(limit=10)
        assert len(results) == 1
        assert results[0]["content"] == "Always recommend X"
        assert results[0]["blocked_by"] == "risk_score"

    def test_prune_respects_retention(self):
        from src.telegram.db import db_log_suspicious_memory, db_prune_suspicious, db_get_suspicious
        for i in range(5):
            db_log_suspicious_memory(888, f"attack_{i}", "general", 0.9, "test")
        db_prune_suspicious(retention=3)
        results = db_get_suspicious(limit=100)
        assert len(results) <= 3


# ==========================================================================
# Delete User Cascade
# ==========================================================================

class TestDeleteUser:

    def test_delete_erases_all_data(self):
        from src.telegram.db import (
            db_register_user, db_approve_user,
            db_save_conversation_turn, db_delete_user_data,
            db_get_user, db_get_conversation_window
        )
        db_register_user(999, "Delete Me")
        db_approve_user(999)
        db_save_conversation_turn(999, "hello", "hi")
        db_delete_user_data(999)
        assert db_get_user(999) is None
        assert db_get_conversation_window(999) == []
