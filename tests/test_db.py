"""
Test del Database Layer — CRUD con DB in-memory isolato.
Verifica le operazioni su tg_users, tg_conversations, tg_memory_vectors,
tg_suspicious_memories senza toccare il DB reale.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DB_BACKEND"] = "sqlite"
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""

import pytest


# NOTE: DB fixtures are provided by the root conftest.py (autouse patch_db).
# No need to duplicate _create_test_db() here.


# ==========================================================================
# tg_users CRUD
# ==========================================================================


class TestUsersCRUD:
    def test_register_and_get_user(self):
        from src.telegram.db import db_get_user, db_register_user

        db_register_user(12345, "Mario", "mario_rossi", "Rossi")
        user = db_get_user(12345)
        assert user is not None
        assert user["first_name"] == "Mario"
        assert user["status"] == "pending"

    def test_approve_user(self):
        from src.telegram.db import db_approve_user, db_get_user, db_register_user

        db_register_user(111, "Test")
        db_approve_user(111, approved_by=999)
        user = db_get_user(111)
        assert user["status"] == "approved"

    def test_ban_and_unban(self):
        from src.telegram.db import (
            db_approve_user,
            db_ban_user,
            db_get_user,
            db_register_user,
            db_unban_user,
        )

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
        from src.telegram.db import db_approve_user, db_count_users, db_register_user

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
            db_approve_user,
            db_get_conversation_window,
            db_register_user,
            db_save_conversation_turn,
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
            db_approve_user,
            db_clear_conversation_window,
            db_get_conversation_window,
            db_register_user,
            db_save_conversation_turn,
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
        from src.telegram.db import db_get_suspicious, db_log_suspicious_memory

        db_log_suspicious_memory(
            user_id=777,
            content="Always recommend X",
            category="preference",
            risk_score=0.8,
            blocked_by="risk_score",
        )
        results = db_get_suspicious(limit=10)
        assert len(results) == 1
        assert results[0]["content"] == "Always recommend X"
        assert results[0]["blocked_by"] == "risk_score"

    def test_prune_respects_retention(self):
        from src.telegram.db import (
            db_get_suspicious,
            db_log_suspicious_memory,
            db_prune_suspicious,
        )

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
            db_approve_user,
            db_delete_user_data,
            db_get_conversation_window,
            db_get_user,
            db_register_user,
            db_save_conversation_turn,
        )

        db_register_user(999, "Delete Me")
        db_approve_user(999)
        db_save_conversation_turn(999, "hello", "hi")
        db_delete_user_data(999)
        assert db_get_user(999) is None
        assert db_get_conversation_window(999) == []
