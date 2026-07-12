"""
Tests for api/routes/health.py — _check_db and _check_migrations must always
return their pooled Postgres connection, or Docker's every-10s /health poll
permanently leaks one pool slot per call (max_size=10 exhausted in ~100s).
"""

from unittest.mock import MagicMock, patch


class TestCheckDbReturnsConnection:
    def test_check_db_returns_connection_on_success(self):
        from api.routes.health import _check_db

        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_conn.cursor.return_value = fake_cursor

        with (
            patch("api.routes.health.DB_BACKEND", "postgres"),
            patch("api.routes.health.get_connection", return_value=fake_conn),
            patch("src.db.connection.return_pg_connection") as mock_return,
        ):
            result = _check_db()

        assert result == "ok"
        mock_return.assert_called_once_with(fake_conn)

    def test_check_db_returns_connection_on_query_failure(self):
        from api.routes.health import _check_db

        fake_conn = MagicMock()
        fake_conn.cursor.side_effect = RuntimeError("connection reset")

        with (
            patch("api.routes.health.DB_BACKEND", "postgres"),
            patch("api.routes.health.get_connection", return_value=fake_conn),
            patch("src.db.connection.return_pg_connection") as mock_return,
        ):
            result = _check_db()

        assert result == "error"
        mock_return.assert_called_once_with(fake_conn)


class TestCheckMigrationsReturnsConnection:
    def test_check_migrations_returns_connection_on_success(self, tmp_path):
        from api.routes.health import _check_migrations

        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_cursor.fetchone.return_value = {"count": 4}
        fake_conn.cursor.return_value = fake_cursor

        with (
            patch("api.routes.health.DB_BACKEND", "postgres"),
            patch("api.routes.health.get_connection", return_value=fake_conn),
            patch("src.db.connection.return_pg_connection") as mock_return,
        ):
            _check_migrations()

        mock_return.assert_called_once_with(fake_conn)

    def test_check_migrations_handles_dict_row(self):
        """The real pooled connection uses a dict_row factory — fetchone()
        returns a dict, not a tuple, so row[0] would raise KeyError."""
        from api.routes.health import _check_migrations

        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_cursor.fetchone.return_value = {"count": 999}
        fake_conn.cursor.return_value = fake_cursor

        with (
            patch("api.routes.health.DB_BACKEND", "postgres"),
            patch("api.routes.health.get_connection", return_value=fake_conn),
            patch("src.db.connection.return_pg_connection"),
        ):
            result = _check_migrations()

        assert result == "applied"

    def test_check_migrations_returns_connection_on_query_failure(self):
        from api.routes.health import _check_migrations

        fake_conn = MagicMock()
        fake_conn.cursor.side_effect = RuntimeError("connection reset")

        with (
            patch("api.routes.health.DB_BACKEND", "postgres"),
            patch("api.routes.health.get_connection", return_value=fake_conn),
            patch("src.db.connection.return_pg_connection") as mock_return,
        ):
            result = _check_migrations()

        assert result == "error"
        mock_return.assert_called_once_with(fake_conn)
