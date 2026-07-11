"""
Migration 004: Chat Titles + Message History

Adds:
- argos_chats.title — short auto-generated label for a chat (NULL until the
  first turn completes; see src.core.chats.generate_title_if_needed).
- argos_chat_messages — full transcript per chat, shared between CLI and
  Dashboard so resuming a chat in either interface shows the same history.

Idempotent: CREATE TABLE uses IF NOT EXISTS. SQLite's ALTER TABLE ADD COLUMN
has no IF NOT EXISTS clause, so that branch checks PRAGMA table_info first.
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
        cursor.execute("ALTER TABLE argos_chats ADD COLUMN IF NOT EXISTS title TEXT")
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS argos_chat_messages (
                id         SERIAL PRIMARY KEY,
                chat_id    INTEGER NOT NULL REFERENCES argos_chats(id),
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )"""
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_argos_chat_messages_chat_id "
            "ON argos_chat_messages(chat_id)"
        )
    else:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(argos_chats)")}
        if "title" not in columns:
            conn.execute("ALTER TABLE argos_chats ADD COLUMN title TEXT")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS argos_chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL REFERENCES argos_chats(id),
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_argos_chat_messages_chat_id "
            "ON argos_chat_messages(chat_id)"
        )

    conn.commit()
    if owns_conn:
        conn.close()
        print("✅ Migration 004_chat_messages completed successfully.")


if __name__ == "__main__":
    run()
