"""
Migration runner for SQLite and PostgreSQL backends.
Discovers and applies pending migrations in order, tracking applied ones
in a `schema_migrations` table. Idempotent: safe to call on every startup.
"""

import importlib
import logging
import os
import re
import sqlite3

logger = logging.getLogger("argos")

_MIGRATIONS_DIR = os.path.dirname(__file__)
_MIGRATION_RE = re.compile(r"^(\d+)_[a-z0-9_]+\.py$")


def _ensure_tracking_table(conn) -> None:
    """Create schema_migrations table for tracking applied migrations.

    Supports both SQLite and PostgreSQL connections.
    Works with both sqlite3.Connection and psycopg Connection objects.
    """
    conn_type_module = type(conn).__module__

    if "psycopg" in conn_type_module:
        # PostgreSQL (psycopg) connection
        sql = """CREATE TABLE IF NOT EXISTS schema_migrations (
            version   INTEGER PRIMARY KEY,
            name      TEXT NOT NULL,
            applied_at TIMESTAMP NOT NULL DEFAULT now()
        )"""
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()
    else:
        # SQLite connection
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version   INTEGER PRIMARY KEY,
                name      TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        conn.commit()


def _applied_versions(conn) -> set[int]:
    """Get set of migration versions already applied to the database.

    Supports both SQLite and PostgreSQL connections.
    """
    conn_type_module = type(conn).__module__

    if "psycopg" in conn_type_module:
        # PostgreSQL (psycopg) connection
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cursor.fetchall()}
    else:
        # SQLite connection
        return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def run_sqlite_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations to SQLite connection in version order."""
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


def run_postgres_migrations(conn) -> None:
    """Apply all pending migrations to PostgreSQL connection in version order.

    Mirrors run_sqlite_migrations but uses psycopg API for PostgreSQL.
    Connection type is inferred from the connection object.
    """
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

        # Insert into tracking table using psycopg API
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
            (version, module_name),
        )
        conn.commit()
        logger.info(f"[DB] Migration {module_name} applied.")


def run_migrations(conn) -> None:
    """Public dispatcher: apply all pending migrations based on connection type.

    Automatically detects backend (SQLite vs PostgreSQL) from connection type
    and calls the appropriate migration runner.

    Args:
        conn: Either sqlite3.Connection or psycopg.Connection

    Raises:
        Exception: If any migration fails (fail-fast behavior)
    """
    conn_type_module = type(conn).__module__

    if "psycopg" in conn_type_module:
        # PostgreSQL (psycopg) connection
        run_postgres_migrations(conn)
    else:
        # SQLite connection
        run_sqlite_migrations(conn)
