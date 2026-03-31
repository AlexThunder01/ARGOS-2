"""
ARGOS-2 Telegram Module — SQLite Database Helper Functions
Provides all CRUD operations for tg_users, tg_user_profiles,
tg_conversations, tg_memory_vectors, and tg_tasks.
"""
import sqlite3
import os
from datetime import date
from src.db.connection import get_connection


def _get_conn():
    return get_connection()


# ==========================================================================
# tg_users — User Registry & Access Control
# ==========================================================================

def db_get_user(user_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM tg_users WHERE user_id = ?", (user_id,)).fetchone()

    return dict(row) if row else None


def db_register_user(user_id: int, first_name: str = "", username: str = "", last_name: str = ""):
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO tg_users (user_id, first_name, username, last_name) VALUES (?, ?, ?, ?)",
        (user_id, first_name, username, last_name)
    )
    conn.commit()



def db_approve_user(user_id: int, approved_by: int = 0):
    conn = _get_conn()
    conn.execute(
        "UPDATE tg_users SET status='approved', approved_at=datetime('now'), approved_by=? WHERE user_id=?",
        (approved_by, user_id)
    )
    conn.commit()



def db_ban_user(user_id: int, reason: str = ""):
    conn = _get_conn()
    conn.execute(
        "UPDATE tg_users SET status='banned', banned_at=datetime('now'), ban_reason=? WHERE user_id=?",
        (reason, user_id)
    )
    conn.commit()



def db_unban_user(user_id: int):
    conn = _get_conn()
    conn.execute(
        "UPDATE tg_users SET status='approved', banned_at=NULL, ban_reason=NULL WHERE user_id=?",
        (user_id,)
    )
    conn.commit()



def db_increment_msg_count(user_id: int):
    """Increments message counters. Lazily resets daily counter when the date changes."""
    conn = _get_conn()
    today = date.today().isoformat()
    row = conn.execute("SELECT last_daily_reset FROM tg_users WHERE user_id=?", (user_id,)).fetchone()
    if row and row["last_daily_reset"] != today:
        conn.execute(
            "UPDATE tg_users SET msg_count_today=1, msg_count_total=msg_count_total+1, "
            "last_daily_reset=?, last_seen=datetime('now') WHERE user_id=?",
            (today, user_id)
        )
    else:
        conn.execute(
            "UPDATE tg_users SET msg_count_today=msg_count_today+1, msg_count_total=msg_count_total+1, "
            "last_seen=datetime('now') WHERE user_id=?",
            (user_id,)
        )
    conn.commit()



def db_count_users(status: str) -> int:
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM tg_users WHERE status=?", (status,)).fetchone()

    return row["c"] if row else 0


def db_list_users(status: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT user_id, username, first_name, status, registered_at, msg_count_total "
        "FROM tg_users WHERE status=? ORDER BY registered_at DESC", (status,)
    ).fetchall()

    return [dict(r) for r in rows]


# ==========================================================================
# tg_user_profiles — Per-User Preferences
# ==========================================================================

def db_get_profile(user_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM tg_user_profiles WHERE user_id=?", (user_id,)).fetchone()

    return dict(row) if row else None


def db_update_profile(user_id: int, **kwargs):
    """Updates profile fields. Creates the profile row if it doesn't exist."""
    conn = _get_conn()
    conn.execute("INSERT OR IGNORE INTO tg_user_profiles (user_id) VALUES (?)", (user_id,))
    allowed_cols = {
        "display_name": "display_name",
        "language": "language",
        "preferred_tone": "preferred_tone",
        "custom_prefs": "custom_prefs"
    }
    for key, value in kwargs.items():
        if key in allowed_cols:
            safe_col = allowed_cols[key]
            conn.execute(
                f"UPDATE tg_user_profiles SET {safe_col}=?, updated_at=datetime('now') WHERE user_id=?",
                (value, user_id)
            )
    conn.commit()



# ==========================================================================
# tg_conversations — Sliding Window History
# ==========================================================================

def db_save_conversation_turn(user_id: int, user_text: str, assistant_text: str):
    """Saves both the user and assistant turns, then trims old messages."""
    conn = _get_conn()
    user_tokens = len(user_text) // 4
    assistant_tokens = len(assistant_text) // 4
    conn.execute(
        "INSERT INTO tg_conversations (user_id, role, content, token_count) VALUES (?, 'user', ?, ?)",
        (user_id, user_text, user_tokens)
    )
    conn.execute(
        "INSERT INTO tg_conversations (user_id, role, content, token_count) VALUES (?, 'assistant', ?, ?)",
        (user_id, assistant_text, assistant_tokens)
    )
    # Trim: keep only the most recent MAX_HISTORY messages per user
    MAX_HISTORY = 200
    conn.execute(
        "DELETE FROM tg_conversations WHERE user_id=? AND id NOT IN ("
        "  SELECT id FROM tg_conversations WHERE user_id=? ORDER BY ts DESC LIMIT ?"
        ")", (user_id, user_id, MAX_HISTORY)
    )
    conn.commit()



def db_get_conversation_window(user_id: int, limit: int = 20, max_tokens: int = 4000) -> list[dict]:
    """Retrieves the recent conversation window, trimmed by token budget."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, token_count FROM tg_conversations "
        "WHERE user_id=? ORDER BY ts DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()

    rows = list(reversed(rows))  # Chronological order
    total_tokens = 0
    trimmed = []
    for row in rows:
        total_tokens += (row["token_count"] or len(row["content"]) // 4)
        if total_tokens > max_tokens:
            break
        trimmed.append({"role": row["role"], "content": row["content"]})
    return trimmed


def db_clear_conversation_window(user_id: int):
    conn = _get_conn()
    conn.execute("DELETE FROM tg_conversations WHERE user_id=?", (user_id,))
    conn.commit()



# ==========================================================================
# tg_tasks — Open Tasks & Follow-ups
# ==========================================================================

def db_get_open_tasks(user_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, description, due_at, created_at FROM tg_tasks "
        "WHERE user_id=? AND status='open' ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()

    return [dict(r) for r in rows]


# ==========================================================================
# tg_memory_vectors — Long-Term RAG Memory (read-side helpers)
# ==========================================================================

def db_get_all_memory_blobs(user_id: int) -> list[tuple]:
    """Returns raw (id, content, embedding_blob, category, confidence) tuples."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, content, embedding, category, confidence "
        "FROM tg_memory_vectors WHERE user_id=?",
        (user_id,)
    ).fetchall()

    return [(r["id"], r["content"], r["embedding"], r["category"], r["confidence"]) for r in rows]

def db_get_one_memory_blob() -> bytes | None:
    """Returns a single embedding blob for dimension checking on boot."""
    conn = _get_conn()
    row = conn.execute("SELECT embedding FROM tg_memory_vectors LIMIT 1").fetchone()
    return row["embedding"] if row else None


def db_update_memory_access(memory_ids: list[int]):
    if not memory_ids:
        return
    conn = _get_conn()
    placeholders = ",".join("?" * len(memory_ids))
    conn.execute(
        f"UPDATE tg_memory_vectors SET access_count=access_count+1, "
        f"last_accessed=datetime('now') WHERE id IN ({placeholders})",
        memory_ids
    )
    conn.commit()



def db_insert_memory(user_id: int, content: str, embedding_blob: bytes, category: str = "general"):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO tg_memory_vectors (user_id, content, embedding, category) VALUES (?, ?, ?, ?)",
        (user_id, content, embedding_blob, category)
    )
    conn.commit()



def db_count_memories(user_id: int = 0) -> int:
    conn = _get_conn()
    if user_id:
        row = conn.execute("SELECT COUNT(*) as c FROM tg_memory_vectors WHERE user_id=?", (user_id,)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) as c FROM tg_memory_vectors").fetchone()

    return row["c"] if row else 0


# ==========================================================================
# Memory Garbage Collection
# ==========================================================================

MAX_MEMORIES_PER_USER = 500
GC_STALE_DAYS = 30

def db_gc_memories(user_id: int):
    """Prunes stale and excess memories for a user."""
    conn = _get_conn()
    # 1. Delete never-accessed memories older than GC_STALE_DAYS
    conn.execute(
        "DELETE FROM tg_memory_vectors WHERE user_id=? AND access_count=0 "
        "AND created_at < datetime('now', ?)",
        (user_id, f'-{GC_STALE_DAYS} days')
    )
    # 2. Enforce hard cap
    conn.execute(
        "DELETE FROM tg_memory_vectors WHERE user_id=? AND id NOT IN ("
        "  SELECT id FROM tg_memory_vectors WHERE user_id=? "
        "  ORDER BY access_count DESC, created_at DESC LIMIT ?"
        ")", (user_id, user_id, MAX_MEMORIES_PER_USER)
    )
    conn.commit()



# ==========================================================================
# User Statistics & Deletion
# ==========================================================================

def db_get_user_stats(user_id: int) -> dict:
    conn = _get_conn()
    user = conn.execute(
        "SELECT msg_count_total, registered_at FROM tg_users WHERE user_id=?", (user_id,)
    ).fetchone()
    mem_count = conn.execute(
        "SELECT COUNT(*) as c FROM tg_memory_vectors WHERE user_id=?", (user_id,)
    ).fetchone()
    task_count = conn.execute(
        "SELECT COUNT(*) as c FROM tg_tasks WHERE user_id=? AND status='open'", (user_id,)
    ).fetchone()

    return {
        "msg_count": user["msg_count_total"] if user else 0,
        "registered_at": user["registered_at"] if user else "unknown",
        "memory_count": mem_count["c"] if mem_count else 0,
        "open_tasks": task_count["c"] if task_count else 0,
    }


def db_delete_user_data(user_id: int):
    """Deletes ALL data for a user (CASCADE handles child tables)."""
    conn = _get_conn()
    conn.execute("DELETE FROM tg_users WHERE user_id=?", (user_id,))
    conn.commit()



# ==========================================================================
# tg_suspicious_memories — Anti-Poisoning Audit Log (Sprint 4)
# ==========================================================================

def _ensure_suspicious_table():
    """Creates the audit table idempotently (no separate migration needed)."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_suspicious_memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            content     TEXT NOT NULL,
            category    TEXT,
            risk_score  REAL,
            blocked_by  TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()



def db_log_suspicious_memory(user_id: int, content: str, category: str,
                             risk_score: float, blocked_by: str):
    """Logs a blocked memory attempt to the audit table."""
    _ensure_suspicious_table()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO tg_suspicious_memories (user_id, content, category, risk_score, blocked_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, content, category, risk_score, blocked_by)
    )
    conn.commit()



def db_prune_suspicious(retention: int = 500):
    """Enforces retention cap on the suspicious audit table."""
    _ensure_suspicious_table()
    conn = _get_conn()
    conn.execute(
        "DELETE FROM tg_suspicious_memories WHERE id NOT IN ("
        "  SELECT id FROM tg_suspicious_memories ORDER BY created_at DESC LIMIT ?"
        ")", (retention,)
    )
    conn.commit()



def db_get_suspicious(limit: int = 50, offset: int = 0) -> list[dict]:
    """Returns paginated suspicious memory attempts for admin review."""
    _ensure_suspicious_table()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, user_id, content, category, risk_score, blocked_by, created_at "
        "FROM tg_suspicious_memories ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()

    return [dict(r) for r in rows]

