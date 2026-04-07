"""
ARGOS-2 Telegram Module — Database Helper Functions.

Dual-backend: works with both SQLite (dev) and PostgreSQL (production).
All queries use a paramstyle adapter to handle the difference between
SQLite (?-placeholders) and psycopg (%s-placeholders).
"""

import logging
from datetime import date

from src.db.connection import DB_BACKEND, get_connection, ph, return_pg_connection

logger = logging.getLogger("argos")

# ---------------------------------------------------------------------------
# Backend-Aware Query Helpers
# ---------------------------------------------------------------------------

# Alias for backward compatibility within this module
_ph = ph


def _now_expr() -> str:
    """Returns the 'current timestamp' expression for the active backend."""
    if DB_BACKEND == "postgres":
        return "NOW()"
    return "datetime('now')"


def _date_expr() -> str:
    if DB_BACKEND == "postgres":
        return "CURRENT_DATE"
    return "date('now')"


def _stale_expr(days: int) -> str:
    """Returns 'N days ago' date expression."""
    if DB_BACKEND == "postgres":
        return f"NOW() - INTERVAL '{days} days'"
    return f"datetime('now', '-{days} days')"


class _Ctx:
    """Context manager for proper connection lifecycle."""

    def __init__(self):
        self.conn = get_connection()

    def execute(self, query, params=None):
        q = _ph(query)
        if DB_BACKEND == "postgres":
            cur = self.conn.cursor()
            cur.execute(q, params)
            return cur
        else:
            return self.conn.execute(q, params) if params else self.conn.execute(q)

    def commit(self):
        self.conn.commit()

    def close(self):
        if DB_BACKEND == "postgres":
            return_pg_connection(self.conn)
        # SQLite connections are thread-local, never closed here

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _db():
    return _Ctx()


# ==========================================================================
# tg_users — User Registry & Access Control
# ==========================================================================


def db_get_user(user_id: int) -> dict | None:
    with _db() as db:
        cur = db.execute("SELECT * FROM tg_users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def db_register_user(
    user_id: int, first_name: str = "", username: str = "", last_name: str = ""
):
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
        cur = db.execute(
            "SELECT last_daily_reset FROM tg_users WHERE user_id=?", (user_id,)
        )
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


def db_get_conversation_window(
    user_id: int, limit: int = 20, max_tokens: int = 4000
) -> list[dict]:
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
# tg_memory_vectors — Long-Term RAG Memory
# ==========================================================================


def db_get_all_memory_blobs(user_id: int) -> list[tuple]:
    """Returns raw (id, content, embedding, category, confidence) tuples."""
    with _db() as db:
        cur = db.execute(
            "SELECT id, content, embedding, category, confidence "
            "FROM tg_memory_vectors WHERE user_id=?",
            (user_id,),
        )
        rows = cur.fetchall()
        return [
            (r["id"], r["content"], r["embedding"], r["category"], r["confidence"])
            for r in rows
        ]


def db_get_one_memory_blob() -> bytes | None:
    """Returns a single embedding for dimension checking on boot."""
    with _db() as db:
        cur = db.execute("SELECT embedding FROM tg_memory_vectors LIMIT 1")
        row = cur.fetchone()
        return row["embedding"] if row else None


def db_update_memory_access(memory_ids: list[int]):
    if not memory_ids:
        return
    with _db() as db:
        placeholders = ",".join("?" * len(memory_ids))
        db.execute(
            f"UPDATE tg_memory_vectors SET access_count=access_count+1, "
            f"last_accessed={_now_expr()} WHERE id IN ({_ph(placeholders)})",
            memory_ids,
        )
        db.commit()


def db_insert_memory(
    user_id: int, content: str, embedding_blob, category: str = "general"
):
    """
    Inserts a memory vector.
    embedding_blob: bytes (SQLite) or list[float] (PostgreSQL).
    """
    with _db() as db:
        if DB_BACKEND == "postgres":
            # pgvector accepts list[float] natively
            vec_str = "[" + ",".join(f"{v:.8f}" for v in embedding_blob) + "]"
            db.execute(
                "INSERT INTO tg_memory_vectors (user_id, content, embedding, category) "
                "VALUES (%s, %s, %s::vector, %s)",
                (user_id, content, vec_str, category),
            )
        else:
            db.execute(
                "INSERT INTO tg_memory_vectors (user_id, content, embedding, category) VALUES (?, ?, ?, ?)",
                (user_id, content, embedding_blob, category),
            )
        db.commit()


def db_count_memories(user_id: int = 0) -> int:
    with _db() as db:
        if user_id:
            cur = db.execute(
                "SELECT COUNT(*) as c FROM tg_memory_vectors WHERE user_id=?",
                (user_id,),
            )
        else:
            cur = db.execute("SELECT COUNT(*) as c FROM tg_memory_vectors")
        row = cur.fetchone()
        return row["c"] if row else 0


# pgvector-native similarity search (used by core/memory.py when backend=postgres)
def db_vector_search(
    user_id: int, query_vec: list[float], top_k: int = 3, min_similarity: float = 0.70
) -> list[dict]:
    """
    Performs HNSW-accelerated cosine similarity search using pgvector.
    Returns top_k results with similarity >= min_similarity.
    """
    vec_str = "[" + ",".join(f"{v:.8f}" for v in query_vec) + "]"
    with _db() as db:
        cur = db.execute(
            "SELECT id, content, category, confidence, "
            "1 - (embedding <=> %s::vector) AS similarity "
            "FROM tg_memory_vectors "
            "WHERE user_id = %s AND 1 - (embedding <=> %s::vector) >= %s "
            "ORDER BY similarity DESC LIMIT %s",
            (vec_str, user_id, vec_str, min_similarity, top_k),
        )
        results = []
        for r in cur.fetchall():
            results.append(
                {
                    "id": r["id"],
                    "content": r["content"],
                    "category": r["category"],
                    "similarity": round(float(r["similarity"]), 4),
                    "confidence": r["confidence"],
                }
            )
        # Update access counters
        if results:
            db_update_memory_access([r["id"] for r in results])
        return results


# ==========================================================================
# Memory Garbage Collection
# ==========================================================================

MAX_MEMORIES_PER_USER = 500
GC_STALE_DAYS = 30


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
        cur2 = db.execute(
            "SELECT COUNT(*) as c FROM tg_memory_vectors WHERE user_id=?", (user_id,)
        )
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


# ==========================================================================
# tg_suspicious_memories — Anti-Poisoning Audit Log
# ==========================================================================


def _ensure_suspicious_table():
    """Creates the audit table idempotently."""
    with _db() as db:
        if DB_BACKEND == "postgres":
            db.execute("""
                CREATE TABLE IF NOT EXISTS tg_suspicious_memories (
                    id          SERIAL PRIMARY KEY,
                    user_id     BIGINT NOT NULL,
                    content     TEXT NOT NULL,
                    category    TEXT,
                    risk_score  REAL,
                    blocked_by  TEXT,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        else:
            db.execute("""
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
        db.commit()


def db_log_suspicious_memory(
    user_id: int, content: str, category: str, risk_score: float, blocked_by: str
):
    _ensure_suspicious_table()
    with _db() as db:
        db.execute(
            "INSERT INTO tg_suspicious_memories (user_id, content, category, risk_score, blocked_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, content, category, risk_score, blocked_by),
        )
        db.commit()


def db_prune_suspicious(retention: int = 500):
    _ensure_suspicious_table()
    with _db() as db:
        db.execute(
            "DELETE FROM tg_suspicious_memories WHERE id NOT IN ("
            "  SELECT id FROM tg_suspicious_memories ORDER BY created_at DESC LIMIT ?"
            ")",
            (retention,),
        )
        db.commit()


def db_get_suspicious(limit: int = 50, offset: int = 0) -> list[dict]:
    _ensure_suspicious_table()
    with _db() as db:
        cur = db.execute(
            "SELECT id, user_id, content, category, risk_score, blocked_by, created_at "
            "FROM tg_suspicious_memories ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]
