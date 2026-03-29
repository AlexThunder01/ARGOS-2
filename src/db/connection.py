"""
ARGOS-2 — Thread-Local SQLite Connection Pool

Provides a single, reusable connection per thread, eliminating the overhead
of opening and closing connections on every query. Connections auto-configure
WAL mode and foreign_keys=ON.

Usage:
    from src.db.connection import get_connection
    conn = get_connection()
    conn.execute("SELECT ...")
    conn.commit()
    # Do NOT call conn.close() — the pool manages lifecycle.
"""
import os
import sqlite3
import threading
import atexit
import logging

logger = logging.getLogger(__name__)

DB_DIR = "/app/data" if os.environ.get("DOCKER_ENV") else "./data"
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "argos_state.db")

_local = threading.local()
_all_connections: list[sqlite3.Connection] = []
_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """Returns a thread-local SQLite connection, creating one if needed."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
        with _lock:
            _all_connections.append(conn)
        logger.debug("[DB Pool] New connection for thread %s", threading.current_thread().name)
    return conn


def close_all():
    """Closes all pooled connections. Called at process exit."""
    with _lock:
        for c in _all_connections:
            try:
                c.close()
            except Exception:
                pass
        _all_connections.clear()
    logger.info("[DB Pool] All connections closed.")


atexit.register(close_all)
