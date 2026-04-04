-- ==========================================================================
-- ARGOS-2 — PostgreSQL Schema (pgvector enabled)
-- Runs on first container init via docker-entrypoint-initdb.d/
-- ==========================================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ==========================================================================
-- pending_emails — HITL State Queue
-- ==========================================================================
CREATE TABLE IF NOT EXISTS pending_emails (
    msg_id   TEXT PRIMARY KEY,
    payload  TEXT
);

-- ==========================================================================
-- tg_users — Telegram User Registry & Access Control
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tg_users (
    user_id          BIGINT PRIMARY KEY,
    username         TEXT,
    first_name       TEXT,
    last_name        TEXT,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK(status IN ('pending', 'approved', 'banned')),
    registered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at      TIMESTAMPTZ,
    approved_by      BIGINT,
    banned_at        TIMESTAMPTZ,
    ban_reason       TEXT,
    msg_count_today  INTEGER DEFAULT 0,
    msg_count_total  INTEGER DEFAULT 0,
    last_seen        TIMESTAMPTZ,
    last_daily_reset DATE DEFAULT CURRENT_DATE
);
CREATE INDEX IF NOT EXISTS idx_tg_users_status ON tg_users(status);

-- ==========================================================================
-- tg_user_profiles — Per-User Preferences
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tg_user_profiles (
    user_id        BIGINT PRIMARY KEY REFERENCES tg_users(user_id) ON DELETE CASCADE,
    display_name   TEXT,
    language       TEXT DEFAULT 'it',
    preferred_tone TEXT DEFAULT 'neutral',
    custom_prefs   TEXT DEFAULT '{}',
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ==========================================================================
-- tg_conversations — Sliding Window History
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tg_conversations (
    id           SERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES tg_users(user_id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content      TEXT NOT NULL,
    token_count  INTEGER,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tg_conv_user_ts ON tg_conversations(user_id, ts DESC);

-- ==========================================================================
-- tg_memory_vectors — Long-Term RAG Memory (pgvector)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tg_memory_vectors (
    id             SERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES tg_users(user_id) ON DELETE CASCADE,
    content        TEXT NOT NULL,
    embedding      vector(768) NOT NULL,
    category       TEXT DEFAULT 'general'
                   CHECK(category IN ('preference','fact','task','interest','general')),
    source_turn_id INTEGER,
    confidence     REAL DEFAULT 1.0,
    access_count   INTEGER DEFAULT 0,
    last_accessed  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tg_mem_user ON tg_memory_vectors(user_id);

-- HNSW index for fast approximate nearest-neighbor search
-- cosine distance operator: <=>
CREATE INDEX IF NOT EXISTS idx_tg_mem_hnsw ON tg_memory_vectors
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ==========================================================================
-- tg_tasks — Open Tasks & Follow-ups
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tg_tasks (
    id            SERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES tg_users(user_id) ON DELETE CASCADE,
    description   TEXT NOT NULL,
    due_at        TIMESTAMPTZ,
    status        TEXT DEFAULT 'open' CHECK(status IN ('open', 'done', 'cancelled')),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    completed_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tg_tasks_user_status ON tg_tasks(user_id, status);

-- ==========================================================================
-- tg_suspicious_memories — Anti-Poisoning Audit Log
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tg_suspicious_memories (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    content     TEXT NOT NULL,
    category    TEXT,
    risk_score  REAL,
    blocked_by  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ==========================================================================
-- tg_rate_limits — Fixed Window Rate Limiting
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tg_rate_limits (
    user_id       BIGINT NOT NULL,
    window_start  TEXT NOT NULL,
    hit_count     INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, window_start)
);
