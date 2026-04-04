"""
Migration 001: Telegram Chat Module Tables
Adds the 5 core tables for the Telegram chat module to argos_state.db.
Idempotent: uses IF NOT EXISTS on all tables and indexes.
Run once before deploying the module.
"""

import os
import sqlite3

DB_DIR = "/app/data" if os.environ.get("DOCKER_ENV") else "./data"
DB_PATH = os.path.join(DB_DIR, "argos_state.db")

MIGRATION_SQL = """
-- 1. User registry and access control
CREATE TABLE IF NOT EXISTS tg_users (
    user_id         INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'banned')),
    registered_at   TEXT NOT NULL DEFAULT (datetime('now')),
    approved_at     TEXT,
    approved_by     INTEGER,
    banned_at       TEXT,
    ban_reason      TEXT,
    msg_count_today INTEGER DEFAULT 0,
    msg_count_total INTEGER DEFAULT 0,
    last_seen       TEXT,
    last_daily_reset TEXT DEFAULT (date('now'))
);
CREATE INDEX IF NOT EXISTS idx_tg_users_status ON tg_users(status);

-- 2. Per-user preferences and declared facts
CREATE TABLE IF NOT EXISTS tg_user_profiles (
    user_id         INTEGER PRIMARY KEY
                    REFERENCES tg_users(user_id) ON DELETE CASCADE,
    display_name    TEXT,
    language        TEXT DEFAULT 'it',
    preferred_tone  TEXT DEFAULT 'neutral',
    custom_prefs    TEXT DEFAULT '{}',
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- 3. Conversation history (sliding window)
CREATE TABLE IF NOT EXISTS tg_conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL
                    REFERENCES tg_users(user_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    token_count     INTEGER,
    ts              TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tg_conv_user_ts
    ON tg_conversations(user_id, ts DESC);

-- 4. Long-term memory vectors (RAG)
CREATE TABLE IF NOT EXISTS tg_memory_vectors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL
                    REFERENCES tg_users(user_id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    embedding       BLOB NOT NULL,
    category        TEXT DEFAULT 'general'
                    CHECK(category IN ('preference','fact','task','interest','general')),
    source_turn_id  INTEGER,
    confidence      REAL DEFAULT 1.0,
    access_count    INTEGER DEFAULT 0,
    last_accessed   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tg_mem_user ON tg_memory_vectors(user_id);
CREATE INDEX IF NOT EXISTS idx_tg_mem_category ON tg_memory_vectors(user_id, category);

-- 5. Tasks and follow-ups
CREATE TABLE IF NOT EXISTS tg_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL
                    REFERENCES tg_users(user_id) ON DELETE CASCADE,
    description     TEXT NOT NULL,
    due_at          TEXT,
    status          TEXT DEFAULT 'open'
                    CHECK(status IN ('open', 'done', 'cancelled')),
    created_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_tg_tasks_user_status
    ON tg_tasks(user_id, status);
"""


def run():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(MIGRATION_SQL)
    conn.commit()
    conn.close()
    print("✅ Migration 001_telegram_module completed successfully.")
    print(f"   Database: {DB_PATH}")


if __name__ == "__main__":
    run()
