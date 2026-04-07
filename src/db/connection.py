"""
ARGOS-2 — Dual-Backend Database Connection Pool.

Supports two backends controlled by DB_BACKEND env var:
  - 'postgres' (default): psycopg connection pool for PostgreSQL + pgvector.
  - 'sqlite': Thread-local SQLite pool for local dev without Docker.

Usage:
    from src.db.connection import get_connection
    conn = get_connection()

For async FastAPI usage, see init_async_pool() / get_async_pool().
"""

import atexit
import logging
import os
import sqlite3
import threading

logger = logging.getLogger(__name__)

DB_BACKEND = os.environ.get("DB_BACKEND", "postgres")


# ==========================================================================
# SQLite Backend (local dev fallback)
# ==========================================================================

DB_DIR = "/app/data" if os.environ.get("DOCKER_ENV") else "./data"
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "argos_state.db")

_local = threading.local()
_all_sqlite_connections: list[sqlite3.Connection] = []
_sqlite_lock = threading.Lock()


def _get_sqlite_connection() -> sqlite3.Connection:
    """Returns a thread-local SQLite connection."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
        with _sqlite_lock:
            _all_sqlite_connections.append(conn)
        logger.debug(
            "[DB Pool/SQLite] New connection for thread %s",
            threading.current_thread().name,
        )
    return conn


def _close_sqlite_all():
    with _sqlite_lock:
        for c in _all_sqlite_connections:
            try:
                c.close()
            except Exception:
                pass
        _all_sqlite_connections.clear()
    logger.info("[DB Pool/SQLite] All connections closed.")


atexit.register(_close_sqlite_all)


# ==========================================================================
# PostgreSQL Backend (production)
# ==========================================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://argos:argos_secret@localhost:5432/argos"
)

_pg_pool = None
_pg_lock = threading.Lock()


def _get_pg_connection():
    """Returns a psycopg connection from the synchronous pool."""
    global _pg_pool
    if _pg_pool is None:
        with _pg_lock:
            if _pg_pool is None:
                import psycopg_pool

                _pg_pool = psycopg_pool.ConnectionPool(
                    DATABASE_URL,
                    min_size=2,
                    max_size=10,
                    kwargs={"autocommit": False, "row_factory": _dict_row_factory},
                )
                logger.info("[DB Pool/PG] Synchronous pool initialized.")
    return _pg_pool.getconn()


def return_pg_connection(conn):
    """Returns a connection to the pool."""
    if _pg_pool is not None:
        _pg_pool.putconn(conn)


def _dict_row_factory(cursor):
    """psycopg row factory that returns dicts with column names as keys."""
    from psycopg.rows import dict_row

    return dict_row(cursor)


def _close_pg_pool():
    global _pg_pool
    if _pg_pool is not None:
        _pg_pool.close()
        logger.info("[DB Pool/PG] Pool closed.")


atexit.register(_close_pg_pool)


# ==========================================================================
# Async Pool (initialized in FastAPI lifespan, stored in app.state)
# ==========================================================================


async def init_async_pool():
    """Creates an async connection pool. Call in FastAPI lifespan() hook."""
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        DATABASE_URL,
        min_size=2,
        max_size=10,
        kwargs={"autocommit": False, "row_factory": dict_row},
    )
    await pool.open()
    logger.info("[DB Pool/PG] Async pool initialized.")
    return pool


async def close_async_pool(pool):
    """Closes the async pool. Call in FastAPI lifespan() shutdown."""
    if pool is not None:
        await pool.close()
        logger.info("[DB Pool/PG] Async pool closed.")


# ==========================================================================
# Public Interface — Backend-Agnostic
# ==========================================================================


def get_connection():
    """
    Returns a database connection based on DB_BACKEND.

    For SQLite: returns a sqlite3.Connection (thread-local, auto-managed).
    For Postgres: returns a psycopg.Connection (must call return_pg_connection() when done,
                  or use as context manager).
    """
    if DB_BACKEND == "sqlite":
        return _get_sqlite_connection()
    else:
        return _get_pg_connection()


def close_all():
    """Closes all pooled connections for both backends."""
    _close_sqlite_all()
    _close_pg_pool()


def ph(query: str) -> str:
    """
    Converts ?-style placeholders to %s for PostgreSQL, leaves them
    unchanged for SQLite.  Single source of truth — import this instead
    of defining a local _ph() in each module.
    """
    return query.replace("?", "%s") if DB_BACKEND == "postgres" else query
