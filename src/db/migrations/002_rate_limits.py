"""
Migration 002: Rate Limits Table
Adds tg_rate_limits for fixed-window rate limiting.
Idempotent: uses IF NOT EXISTS.
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


def run(conn=None):
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.executescript(MIGRATION_SQL)
        conn.commit()
        conn.close()
        print("✅ Migration 002_rate_limits completed successfully.")
    else:
        conn.executescript(MIGRATION_SQL)


if __name__ == "__main__":
    run()
