"""
Migration 003: Argos Chats Table

Adds argos_chats — CLI `--memory` multi-chat registry. Each row is an
isolated persistent-memory "chat": its numeric id is used as the user_id
passed to CoreAgent/mem0, so separate named conversations never mix each
other's facts the way a single shared $USER-derived id did.

Idempotent: uses IF NOT EXISTS.
"""

import os
import sqlite3


def run(conn=None):
    """Apply migration. Accepts an existing connection (runner mode) or
    opens the default SQLite DB directly when called as a standalone script."""
    owns_conn = conn is None
    if owns_conn:
        db_dir = "/app/data" if os.environ.get("DOCKER_ENV") else "./data"
        os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(os.path.join(db_dir, "argos_state.db"), timeout=10)

    conn_type_module = type(conn).__module__
    if "psycopg" in conn_type_module:
        cursor = conn.cursor()
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS argos_chats (
                id           SERIAL PRIMARY KEY,
                created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                last_used_at TIMESTAMP NOT NULL DEFAULT NOW()
            )"""
        )
    else:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS argos_chats (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                last_used_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )

    conn.commit()
    if owns_conn:
        conn.close()
        print("✅ Migration 003_argos_chats completed successfully.")


if __name__ == "__main__":
    run()
