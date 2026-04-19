"""
ARGOS-2 Telegram Module — Database Helper Functions.

Dual-backend: works with both SQLite (dev) and PostgreSQL (production).
All queries use a paramstyle adapter to handle the difference between
SQLite (?-placeholders) and psycopg (%s-placeholders).

Infrastructure (_Ctx, _db, etc.) and generic memory functions live in
src/db/repository.py. This module contains only Telegram-specific tables.
"""

import logging
from datetime import date

from src.db.connection import DB_BACKEND
from src.db.repository import (
    _db,
    _now_expr,
    _stale_expr,
    db_count_memories,
    db_get_all_memory_blobs,
    db_get_suspicious,
    db_log_suspicious_memory,
    db_prune_suspicious,
)

logger = logging.getLogger("argos")

MAX_MEMORIES_PER_USER = 500
GC_STALE_DAYS = 30


# ==========================================================================
# tg_users — User Registry & Access Control
# ==========================================================================


def db_get_user(user_id: int) -> dict | None:
    with _db() as db:
        cur = db.execute("SELECT * FROM tg_users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def db_register_user(user_id: int, first_name: str = "", username: str = "", last_name: str = ""):
    with _db() as db:
        if DB_BACKEND == "postgres":
            db.execute(
                "INSERT INTO tg_users (user_id, first_name, username, last_name) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (user_id, first_name, username, last_name),
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO tg_users (user_id, first_name, username, last_name) VALUES (?, ?, ?, ?)",
                (user_id, first_name, username, last_name),
            )
        db.commit()


def db_approve_user(user_id: int, approved_by: int = 0):
    with _db() as db:
        db.execute(
            f"UPDATE tg_users SET status='approved', approved_at={_now_expr()}, approved_by=? WHERE user_id=?",
            (approved_by, user_id),
        )
        db.commit()


def db_ban_user(user_id: int, reason: str = ""):
    with _db() as db:
        db.execute(
            f"UPDATE tg_users SET status='banned', banned_at={_now_expr()}, ban_reason=? WHERE user_id=?",
            (reason, user_id),
        )
        db.commit()


def db_unban_user(user_id: int):
    with _db() as db:
        db.execute(
            "UPDATE tg_users SET status='approved', banned_at=NULL, ban_reason=NULL WHERE user_id=?",
            (user_id,),
        )
        db.commit()


def db_increment_msg_count(user_id: int):
    """Increments message counters. Lazily resets daily counter when the date changes."""
    with _db() as db:
        today = date.today().isoformat()
        cur = db.execute("SELECT last_daily_reset FROM tg_users WHERE user_id=?", (user_id,))
        row = cur.fetchone()

        reset_val = None
        if row:
            reset_val = row["last_daily_reset"]
            if isinstance(reset_val, date):
                reset_val = reset_val.isoformat()

        if row and reset_val != today:
            db.execute(
                f"UPDATE tg_users SET msg_count_today=1, msg_count_total=msg_count_total+1, "
                f"last_daily_reset=?, last_seen={_now_expr()} WHERE user_id=?",
                (today, user_id),
            )
        else:
            db.execute(
                f"UPDATE tg_users SET msg_count_today=msg_count_today+1, msg_count_total=msg_count_total+1, "
                f"last_seen={_now_expr()} WHERE user_id=?",
                (user_id,),
            )
        db.commit()


def db_count_users(status: str) -> int:
    with _db() as db:
        cur = db.execute("SELECT COUNT(*) as c FROM tg_users WHERE status=?", (status,))
        row = cur.fetchone()
        return row["c"] if row else 0


def db_list_users(status: str) -> list[dict]:
    with _db() as db:
        cur = db.execute(
            "SELECT user_id, username, first_name, status, registered_at, msg_count_total "
            "FROM tg_users WHERE status=? ORDER BY registered_at DESC",
            (status,),
        )
        return [dict(r) for r in cur.fetchall()]


# ==========================================================================
# tg_user_profiles — Per-User Preferences
# ==========================================================================


def db_get_profile(user_id: int) -> dict | None:
    with _db() as db:
        cur = db.execute("SELECT * FROM tg_user_profiles WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def db_update_profile(user_id: int, **kwargs):
    """Updates profile fields. Creates the profile row if it doesn't exist."""
    with _db() as db:
        if DB_BACKEND == "postgres":
            db.execute(
                "INSERT INTO tg_user_profiles (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (user_id,),
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO tg_user_profiles (user_id) VALUES (?)",
                (user_id,),
            )

        allowed_cols = {
            "display_name": "display_name",
            "language": "language",
            "preferred_tone": "preferred_tone",
            "custom_prefs": "custom_prefs",
        }
        for key, value in kwargs.items():
            if key in allowed_cols:
                safe_col = allowed_cols[key]
                db.execute(
                    f"UPDATE tg_user_profiles SET {safe_col}=?, updated_at={_now_expr()} WHERE user_id=?",
                    (value, user_id),
                )
        db.commit()


# ==========================================================================
# tg_conversations — Sliding Window History
# ==========================================================================


def db_save_conversation_turn(user_id: int, user_text: str, assistant_text: str):
    """Saves both turns, then trims old messages."""
    with _db() as db:
        user_tokens = len(user_text) // 4
        assistant_tokens = len(assistant_text) // 4
        db.execute(
            "INSERT INTO tg_conversations (user_id, role, content, token_count) VALUES (?, 'user', ?, ?)",
            (user_id, user_text, user_tokens),
        )
        db.execute(
            "INSERT INTO tg_conversations (user_id, role, content, token_count) VALUES (?, 'assistant', ?, ?)",
            (user_id, assistant_text, assistant_tokens),
        )
        MAX_HISTORY = 200
        db.execute(
            "DELETE FROM tg_conversations WHERE user_id=? AND id NOT IN ("
            "  SELECT id FROM tg_conversations WHERE user_id=? ORDER BY ts DESC LIMIT ?"
            ")",
            (user_id, user_id, MAX_HISTORY),
        )
        db.commit()


def db_get_conversation_window(user_id: int, limit: int = 20, max_tokens: int = 4000) -> list[dict]:
    with _db() as db:
        cur = db.execute(
            "SELECT role, content, token_count FROM tg_conversations "
            "WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]

    rows = list(reversed(rows))
    total_tokens = 0
    trimmed = []
    for row in rows:
        total_tokens += row["token_count"] or len(row["content"]) // 4
        if total_tokens > max_tokens:
            break
        trimmed.append({"role": row["role"], "content": row["content"]})
    return trimmed


def db_clear_conversation_window(user_id: int):
    with _db() as db:
        db.execute("DELETE FROM tg_conversations WHERE user_id=?", (user_id,))
        db.commit()


# ==========================================================================
# tg_tasks — Open Tasks & Follow-ups
# ==========================================================================


def db_get_open_tasks(user_id: int) -> list[dict]:
    with _db() as db:
        cur = db.execute(
            "SELECT id, description, due_at, created_at FROM tg_tasks "
            "WHERE user_id=? AND status='open' ORDER BY created_at DESC",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# ==========================================================================
# Memory Garbage Collection (Telegram-initiated)
# ==========================================================================


def db_gc_memories(user_id: int):
    """Prunes stale and excess memories for a user."""
    with _db() as db:
        db.execute(
            f"DELETE FROM tg_memory_vectors WHERE user_id=? AND access_count=0 "
            f"AND created_at < {_stale_expr(GC_STALE_DAYS)}",
            (user_id,),
        )
        db.execute(
            "DELETE FROM tg_memory_vectors WHERE user_id=? AND id NOT IN ("
            "  SELECT id FROM tg_memory_vectors WHERE user_id=? "
            "  ORDER BY access_count DESC, created_at DESC LIMIT ?"
            ")",
            (user_id, user_id, MAX_MEMORIES_PER_USER),
        )
        db.commit()


# ==========================================================================
# User Statistics & Deletion
# ==========================================================================


def db_get_user_stats(user_id: int) -> dict:
    with _db() as db:
        cur = db.execute(
            "SELECT msg_count_total, registered_at FROM tg_users WHERE user_id=?",
            (user_id,),
        )
        user = cur.fetchone()
        cur2 = db.execute("SELECT COUNT(*) as c FROM tg_memory_vectors WHERE user_id=?", (user_id,))
        mem_count = cur2.fetchone()
        cur3 = db.execute(
            "SELECT COUNT(*) as c FROM tg_tasks WHERE user_id=? AND status='open'",
            (user_id,),
        )
        task_count = cur3.fetchone()
        return {
            "msg_count": user["msg_count_total"] if user else 0,
            "registered_at": user["registered_at"] if user else "unknown",
            "memory_count": mem_count["c"] if mem_count else 0,
            "open_tasks": task_count["c"] if task_count else 0,
        }


def db_delete_user_data(user_id: int):
    with _db() as db:
        db.execute("DELETE FROM tg_users WHERE user_id=?", (user_id,))
        db.commit()


# Re-exported from repository for callers that still import from this module
__all__ = [
    "db_get_user",
    "db_register_user",
    "db_approve_user",
    "db_ban_user",
    "db_unban_user",
    "db_increment_msg_count",
    "db_count_users",
    "db_list_users",
    "db_get_profile",
    "db_update_profile",
    "db_save_conversation_turn",
    "db_get_conversation_window",
    "db_clear_conversation_window",
    "db_get_open_tasks",
    "db_gc_memories",
    "db_get_user_stats",
    "db_delete_user_data",
    # Re-exported from repository (backward compat for existing callers)
    "db_count_memories",
    "db_get_all_memory_blobs",
    "db_get_suspicious",
    "db_log_suspicious_memory",
    "db_prune_suspicious",
]
