"""
Shared pytest fixtures for the ARGOS-2 test suite.

patch_db is autouse so every test automatically runs against an isolated
in-memory SQLite database — no real DB required, no test pollution.

Dual-backend support: Tests can be parametrized to run against both SQLite
and PostgreSQL backends by using the db_backend fixture.
"""

import json as json_module
import logging
import os
import sys
import unittest.mock as mock


# Mock pythonjsonlogger before any imports that depend on it
class MockJsonFormatter(logging.Formatter):
    """Minimal JSON formatter for tests when pythonjsonlogger is not available."""

    def __init__(self, *args, rename_fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.rename_fields = rename_fields or {}

    def format(self, record: logging.LogRecord) -> str:
        log_dict = {
            "timestamp": self.formatTime(record, self.datefmt or "%Y-%m-%dT%H:%M:%SZ"),
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # Apply field renames
        renamed_dict = {}
        for key, value in log_dict.items():
            new_key = self.rename_fields.get(key, key)
            renamed_dict[new_key] = value

        # Add any extra fields from the record
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "taskName",
                "trace_id",
            }:
                renamed_dict[key] = value

        # Add trace_id if present
        if hasattr(record, "trace_id"):
            renamed_dict["trace_id"] = record.trace_id

        return json_module.dumps(renamed_dict)


mock_pythonjsonlogger = mock.MagicMock()
mock_pythonjsonlogger.json.JsonFormatter = MockJsonFormatter
sys.modules["pythonjsonlogger"] = mock_pythonjsonlogger
sys.modules["pythonjsonlogger.json"] = mock_pythonjsonlogger.json

os.environ["DB_BACKEND"] = "sqlite"

import sqlite3

import pytest

os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")


def _create_test_db() -> sqlite3.Connection:
    """Creates an in-memory SQLite database with the full project schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src",
        "db",
        "migrations",
        "001_telegram_module.py",
    )
    with open(migration_path) as f:
        content = f.read()
    start = content.index('MIGRATION_SQL = """') + len('MIGRATION_SQL = """')
    end = content.index('"""', start)
    conn.executescript(content[start:end])

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_suspicious_memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            content     TEXT NOT NULL,
            category    TEXT,
            risk_score  REAL,
            blocked_by  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_rate_limits (
            user_id       INTEGER NOT NULL,
            window_start  TEXT NOT NULL,
            hit_count     INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, window_start)
        )
    """)
    conn.commit()
    return conn


def pytest_generate_tests(metafunc):
    """
    Parametrize tests that use db_backend fixture to run against both
    SQLite and PostgreSQL backends (if available).

    For tests that explicitly request the db_backend fixture, this hook
    generates test variants for each backend.
    """
    if "db_backend" in metafunc.fixturenames:
        # Auto-parametrize: SQLite is always available, PostgreSQL is optional
        backends = ["sqlite"]

        # Try to detect if PostgreSQL is available
        postgres_available = _check_postgres_available()
        if postgres_available:
            backends.append("postgres")

        metafunc.parametrize("db_backend", backends)


def _check_postgres_available() -> bool:
    """Check if PostgreSQL test database is reachable.

    Returns True if POSTGRES_HOST and connection succeeds, False otherwise.
    Graceful degradation: if unavailable, only SQLite tests run.
    """
    postgres_host = os.environ.get("POSTGRES_HOST", "localhost")
    postgres_user = os.environ.get("POSTGRES_USER", "postgres")
    postgres_password = os.environ.get("POSTGRES_PASSWORD", "")
    postgres_db = os.environ.get("POSTGRES_DB", "agente_test")

    # If no password in env, assume PostgreSQL is not configured
    if not postgres_password:
        return False

    try:
        import psycopg

        conn_string = (
            f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}/{postgres_db}"
        )
        conn = psycopg.connect(conn_string, timeout=2)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture
def db_backend() -> str:
    """
    Backend identifier for tests that support dual-backend testing.

    Fixture is used with pytest_generate_tests to parametrize tests
    for both SQLite and PostgreSQL backends.

    Returns: "sqlite" or "postgres"
    """
    # This fixture is parametrized by pytest_generate_tests
    # The actual value is injected by pytest
    pass  # Parametrized by pytest_generate_tests hook


def _create_postgres_test_db(db_name: str):
    """Create a PostgreSQL test connection with schema initialized.

    Creates the connection and applies migrations for the test database.
    """
    try:
        import psycopg

        from src.db.migrations import run_postgres_migrations

        postgres_host = os.environ.get("POSTGRES_HOST", "localhost")
        postgres_user = os.environ.get("POSTGRES_USER", "postgres")
        postgres_password = os.environ.get("POSTGRES_PASSWORD")

        conn_string = f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}/{db_name}"
        conn = psycopg.connect(conn_string)

        # Apply migrations
        run_postgres_migrations(conn)

        return conn
    except Exception as e:
        pytest.skip(f"PostgreSQL not available: {e}")


@pytest.fixture
def test_db(db_backend) -> object:
    """
    Test database connection fixture supporting both SQLite and PostgreSQL.

    For tests using db_backend fixture, this provides an isolated database
    connection appropriate to the backend being tested.

    Returns:
        sqlite3.Connection or psycopg.Connection depending on db_backend parameter
    """
    if db_backend == "postgres":
        conn = _create_postgres_test_db("agente_test")
    else:
        # SQLite (default)
        conn = _create_test_db()

    yield conn

    try:
        conn.close()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def patch_db(monkeypatch):
    """
    Patches get_connection in all relevant modules to use an isolated
    in-memory SQLite database. Applied automatically to every test.
    """
    conn = _create_test_db()

    import src.core.rate_limit as rl_module
    import src.db.connection as conn_module
    import src.db.repository as repo_module

    monkeypatch.setattr(repo_module, "get_connection", lambda: conn)
    monkeypatch.setattr(rl_module, "get_connection", lambda: conn)
    monkeypatch.setattr(conn_module, "get_connection", lambda: conn)

    yield conn
    conn.close()
