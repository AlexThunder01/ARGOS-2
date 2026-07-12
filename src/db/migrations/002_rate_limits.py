"""
Migration 002: Rate Limits Table
Adds tg_rate_limits for fixed-window rate limiting.
Idempotent: uses IF NOT EXISTS.

Dual-backend: same table/columns on SQLite and PostgreSQL — only user_id's
type differs (BIGINT on Postgres, to match tg_users in migration 001).
"""

import os
import sqlite3

DB_DIR = "/app/data" if os.environ.get("DOCKER_ENV") else "./data"
DB_PATH = os.path.join(DB_DIR, "argos_state.db")

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS tg_rate_limits (
    user_id      INTEGER NOT NULL,
    window_start TEXT NOT NULL,
    hit_count    INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, window_start)
);
"""

POSTGRES_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS tg_rate_limits (
    user_id      BIGINT NOT NULL,
    window_start TEXT NOT NULL,
    hit_count    INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, window_start)
);
"""


def run(conn=None):
    owns_conn = conn is None
    if owns_conn:
        conn = sqlite3.connect(DB_PATH, timeout=10)

    conn_type_module = type(conn).__module__
    if "psycopg" in conn_type_module:
        cursor = conn.cursor()
        cursor.execute(POSTGRES_MIGRATION_SQL)
    else:
        conn.executescript(MIGRATION_SQL)

    conn.commit()
    if owns_conn:
        conn.close()
        print("✅ Migration 002_rate_limits completed successfully.")


if __name__ == "__main__":
    run()
