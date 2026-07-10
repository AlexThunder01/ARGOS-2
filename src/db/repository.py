"""
ARGOS-2 DB Repository — Generic database infrastructure and memory functions.

This module owns all interface-agnostic DB logic. src/core and other non-Telegram
modules import from here. src/telegram/db.py imports infrastructure from here —
that direction (telegram depends on repository, never the reverse) must be preserved.
"""

import contextlib
import logging

from src.db.connection import DB_BACKEND, get_connection, ph, return_pg_connection

logger = logging.getLogger("argos")

# ==========================================================================
# Backend-Aware Query Infrastructure
# ==========================================================================

_ph = ph


def _now_expr() -> str:
    if DB_BACKEND == "postgres":
        return "NOW()"
    return "datetime('now')"


def _date_expr() -> str:
    if DB_BACKEND == "postgres":
        return "CURRENT_DATE"
    return "date('now')"


def _stale_expr(days: int) -> str:
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
            with contextlib.suppress(Exception):
                self.conn.rollback()

            return_pg_connection(self.conn)
        # SQLite connections are thread-local, never closed here

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _db():
    return _Ctx()


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
            (r["id"], r["content"], r["embedding"], r["category"], r["confidence"]) for r in rows
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


def db_insert_memory(user_id: int, content: str, embedding_blob, category: str = "general"):
    """
    Inserts a memory vector.
    embedding_blob: bytes (SQLite) or list[float] (PostgreSQL).
    """
    with _db() as db:
        if DB_BACKEND == "postgres":
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


def db_vector_search(
    user_id: int, query_vec: list[float], top_k: int = 3, min_similarity: float = 0.25
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
        if results:
            db_update_memory_access([r["id"] for r in results])
        return results


# ==========================================================================
# tg_suspicious_memories — Anti-Poisoning Audit Log
# ==========================================================================

MAX_MEMORIES_PER_USER = 500
GC_STALE_DAYS = 30


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


__all__ = [
    "_Ctx",
    "_db",
    "_now_expr",
    "_date_expr",
    "_stale_expr",
    "db_get_one_memory_blob",
    "db_count_memories",
    "db_vector_search",
    "db_get_all_memory_blobs",
    "db_update_memory_access",
    "db_insert_memory",
    "db_log_suspicious_memory",
    "db_prune_suspicious",
    "db_get_suspicious",
]
