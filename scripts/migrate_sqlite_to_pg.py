#!/usr/bin/env python3
"""
ARGOS-2 — One-Shot Migration: SQLite → PostgreSQL + pgvector.

Reads data from the existing argos_state.db and inserts into PostgreSQL.
Embedding BLOBs are deserialized from float32 bytes and inserted as
native pgvector arrays.

Usage:
    DATABASE_URL=postgresql://argos:argos_secret@localhost:5432/argos \
    python3 scripts/migrate_sqlite_to_pg.py

The original SQLite file is NEVER modified or deleted.
"""

import logging
import os
import sqlite3
import struct
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate")

# ---------------------------------------------------------------------------
# Inline deserialization (self-contained, no external imports needed)
# ---------------------------------------------------------------------------


def _deserialize_blob(blob: bytes, dim: int = 768) -> list[float]:
    """Converts a raw float32 BLOB into a Python list of floats."""
    if blob is None:
        return [0.0] * dim
    n_floats = len(blob) // 4
    return list(struct.unpack(f"{n_floats}f", blob))


def _format_vector(floats: list[float]) -> str:
    """Formats a float list as a pgvector literal: '[0.1,0.2,...]'"""
    return "[" + ",".join(f"{v:.8f}" for v in floats) + "]"


# ---------------------------------------------------------------------------
# Migration Logic
# ---------------------------------------------------------------------------


def migrate():
    # --- Source: SQLite ---
    sqlite_path = os.environ.get("SQLITE_PATH", "./data/argos_state.db")
    if not os.path.exists(sqlite_path):
        logger.error(f"SQLite file not found: {sqlite_path}")
        sys.exit(1)

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    logger.info(f"📂 Source: {sqlite_path}")

    # --- Destination: PostgreSQL ---
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error(
            "DATABASE_URL not set. Example: postgresql://argos:argos_secret@localhost:5432/argos"
        )
        sys.exit(1)

    try:
        import psycopg
    except ImportError:
        logger.error("psycopg not installed. Run: pip install 'psycopg[binary]'")
        sys.exit(1)

    dst = psycopg.connect(database_url, autocommit=False)
    cur = dst.cursor()
    logger.info("🐘 Destination: PostgreSQL connected")

    # --- 1. pending_emails ---
    rows = src.execute("SELECT msg_id, payload FROM pending_emails").fetchall()
    for r in rows:
        cur.execute(
            "INSERT INTO pending_emails (msg_id, payload) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (r["msg_id"], r["payload"]),
        )
    logger.info(f"  ✅ pending_emails: {len(rows)} rows")

    # --- 2. tg_users ---
    rows = src.execute("SELECT * FROM tg_users").fetchall()
    for r in rows:
        cur.execute(
            """INSERT INTO tg_users (user_id, username, first_name, last_name, status,
               registered_at, approved_at, approved_by, banned_at, ban_reason,
               msg_count_today, msg_count_total, last_seen, last_daily_reset)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (user_id) DO NOTHING""",
            (
                r["user_id"],
                r["username"],
                r["first_name"],
                r["last_name"],
                r["status"],
                r["registered_at"],
                r["approved_at"],
                r["approved_by"],
                r["banned_at"],
                r["ban_reason"],
                r["msg_count_today"],
                r["msg_count_total"],
                r["last_seen"],
                r["last_daily_reset"],
            ),
        )
    logger.info(f"  ✅ tg_users: {len(rows)} rows")

    # --- 3. tg_user_profiles ---
    rows = src.execute("SELECT * FROM tg_user_profiles").fetchall()
    for r in rows:
        cur.execute(
            """INSERT INTO tg_user_profiles (user_id, display_name, language, preferred_tone, custom_prefs, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO NOTHING""",
            (
                r["user_id"],
                r["display_name"],
                r["language"],
                r["preferred_tone"],
                r["custom_prefs"],
                r["updated_at"],
            ),
        )
    logger.info(f"  ✅ tg_user_profiles: {len(rows)} rows")

    # --- 4. tg_conversations ---
    rows = src.execute("SELECT * FROM tg_conversations ORDER BY id").fetchall()
    for r in rows:
        cur.execute(
            """INSERT INTO tg_conversations (user_id, role, content, token_count, ts)
               VALUES (%s,%s,%s,%s,%s)""",
            (r["user_id"], r["role"], r["content"], r["token_count"], r["ts"]),
        )
    logger.info(f"  ✅ tg_conversations: {len(rows)} rows")

    # --- 5. tg_memory_vectors (BLOB → pgvector) ---
    rows = src.execute(
        "SELECT user_id, content, embedding, category, source_turn_id, "
        "confidence, access_count, last_accessed, created_at, updated_at "
        "FROM tg_memory_vectors"
    ).fetchall()
    for r in rows:
        vec = _deserialize_blob(r["embedding"])
        vec_literal = _format_vector(vec)
        cur.execute(
            """INSERT INTO tg_memory_vectors
               (user_id, content, embedding, category, source_turn_id,
                confidence, access_count, last_accessed, created_at, updated_at)
               VALUES (%s,%s,%s::vector,%s,%s,%s,%s,%s,%s,%s)""",
            (
                r["user_id"],
                r["content"],
                vec_literal,
                r["category"],
                r["source_turn_id"],
                r["confidence"],
                r["access_count"],
                r["last_accessed"],
                r["created_at"],
                r["updated_at"],
            ),
        )
    logger.info(f"  ✅ tg_memory_vectors: {len(rows)} rows (BLOBs → pgvector)")

    # --- 6. tg_tasks ---
    rows = src.execute("SELECT * FROM tg_tasks").fetchall()
    for r in rows:
        cur.execute(
            """INSERT INTO tg_tasks (user_id, description, due_at, status, created_at, completed_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                r["user_id"],
                r["description"],
                r["due_at"],
                r["status"],
                r["created_at"],
                r["completed_at"],
            ),
        )
    logger.info(f"  ✅ tg_tasks: {len(rows)} rows")

    # --- 7. tg_suspicious_memories (if exists) ---
    try:
        rows = src.execute("SELECT * FROM tg_suspicious_memories").fetchall()
        for r in rows:
            cur.execute(
                """INSERT INTO tg_suspicious_memories (user_id, content, category, risk_score, blocked_by, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (
                    r["user_id"],
                    r["content"],
                    r["category"],
                    r["risk_score"],
                    r["blocked_by"],
                    r["created_at"],
                ),
            )
        logger.info(f"  ✅ tg_suspicious_memories: {len(rows)} rows")
    except sqlite3.OperationalError:
        logger.info("  ⏭️ tg_suspicious_memories: table not found (skipped)")

    # --- Commit ---
    dst.commit()
    cur.close()
    dst.close()
    src.close()

    logger.info("\n🎉 Migration complete! SQLite file preserved at: " + sqlite_path)


if __name__ == "__main__":
    migrate()
