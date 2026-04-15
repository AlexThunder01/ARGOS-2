"""
Migration runner for SQLite backend.
Discovers and applies pending migrations in order, tracking applied ones
in a `schema_migrations` table. Idempotent: safe to call on every startup.

PostgreSQL schema is managed via docker-entrypoint-initdb.d (unchanged).
"""

import importlib
import logging
import os
import re
import sqlite3

logger = logging.getLogger("argos")

_MIGRATIONS_DIR = os.path.dirname(__file__)
_MIGRATION_RE = re.compile(r"^(\d+)_[a-z0-9_]+\.py$")


def _ensure_tracking_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version   INTEGER PRIMARY KEY,
            name      TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.commit()


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def run_sqlite_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations to *conn* in version order."""
    _ensure_tracking_table(conn)
    applied = _applied_versions(conn)

    candidates = []
    for fname in os.listdir(_MIGRATIONS_DIR):
        m = _MIGRATION_RE.match(fname)
        if m:
            candidates.append((int(m.group(1)), fname[:-3]))  # (version, module_name)
    candidates.sort()

    for version, module_name in candidates:
        if version in applied:
            continue
        logger.info(f"[DB] Applying migration {module_name} …")
        mod = importlib.import_module(f"src.db.migrations.{module_name}")
        mod.run(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (version, module_name),
        )
        conn.commit()
        logger.info(f"[DB] Migration {module_name} applied.")
