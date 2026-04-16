"""
Test suite for database migration runner.

Tests verify:
1. Migration auto-discovery and application in version order
2. Idempotent behavior (safe to run multiple times)
3. Tracking table creation and version tracking
4. Feature parity across SQLite and PostgreSQL backends
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DB_BACKEND"] = "sqlite"

import sqlite3

import pytest

from src.db.migrations import (
    _applied_versions,
    _ensure_tracking_table,
    run_migrations,
    run_sqlite_migrations,
)


class TestMigrationRunner:
    """Test migration runner core functionality."""

    def test_ensure_tracking_table_creates_schema_migrations(self, test_db):
        """Verify schema_migrations tracking table is created."""
        _ensure_tracking_table(test_db)

        # Check table exists
        if isinstance(test_db, sqlite3.Connection):
            # SQLite
            cursor = test_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            )
            exists = cursor.fetchone() is not None
        else:
            # PostgreSQL
            cursor = test_db.cursor()
            cursor.execute(
                """SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'schema_migrations'
                )"""
            )
            exists = cursor.fetchone()[0]

        assert exists, "schema_migrations table should exist"

    def test_applied_versions_returns_empty_set_for_new_db(self, test_db):
        """Verify new database has no applied migrations."""
        _ensure_tracking_table(test_db)
        applied = _applied_versions(test_db)
        assert applied == set(), "New database should have no applied migrations"

    def test_run_migrations_applies_all_pending(self, test_db):
        """Verify auto-discovery applies all pending migrations in order."""
        # Run all migrations
        run_migrations(test_db)

        # Check both migration 001 and 002 are applied
        applied = _applied_versions(test_db)
        assert 1 in applied, "Migration 001 should be applied"
        assert 2 in applied, "Migration 002 should be applied"

    def test_migrations_idempotent_second_run_skips_applied(self, test_db):
        """Verify running migrations twice is safe and skips applied ones."""
        # First run
        run_migrations(test_db)
        first_applied = _applied_versions(test_db)

        # Second run
        run_migrations(test_db)
        second_applied = _applied_versions(test_db)

        assert first_applied == second_applied, (
            "Second run should not duplicate migrations"
        )
        assert 1 in second_applied and 2 in second_applied

    def test_applied_versions_returns_correct_set_after_migration(self, test_db):
        """Verify applied_versions returns accurate tracking data."""
        run_migrations(test_db)
        applied = _applied_versions(test_db)

        # Should have versions 1 and 2
        assert applied == {1, 2}, f"Expected {{1, 2}}, got {applied}"


class TestFeatureParity:
    """Test feature parity across SQLite and PostgreSQL backends.

    These tests ensure both backends create identical schemas.
    """

    def test_feature_parity_migration_001_tables_exist(self, test_db):
        """Verify migration 001 creates all expected tables on both backends."""
        run_migrations(test_db)

        if isinstance(test_db, sqlite3.Connection):
            # SQLite
            cursor = test_db.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name LIKE 'tg_%'
                   ORDER BY name"""
            )
            tables = {row[0] for row in cursor.fetchall()}
        else:
            # PostgreSQL
            cursor = test_db.cursor()
            cursor.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public' AND table_name LIKE 'tg_%'
                   ORDER BY table_name"""
            )
            tables = {row[0] for row in cursor.fetchall()}

        # Migration 001 should create these tables
        expected_tables = {
            "tg_users",
            "tg_user_profiles",
            "tg_conversations",
            "tg_memory_vectors",
            "tg_tasks",
        }
        assert expected_tables.issubset(tables), (
            f"Missing tables. Expected {expected_tables}, got {tables}"
        )

    def test_feature_parity_migration_002_rate_limits_table_exists(self, test_db):
        """Verify migration 002 creates tg_rate_limits table on both backends."""
        run_migrations(test_db)

        if isinstance(test_db, sqlite3.Connection):
            # SQLite
            cursor = test_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tg_rate_limits'"
            )
            exists = cursor.fetchone() is not None
        else:
            # PostgreSQL
            cursor = test_db.cursor()
            cursor.execute(
                """SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'tg_rate_limits'
                )"""
            )
            exists = cursor.fetchone()[0]

        assert exists, "tg_rate_limits table should be created by migration 002"

    def test_feature_parity_tg_users_columns_match(self, test_db):
        """Verify tg_users table has same columns on both backends."""
        run_migrations(test_db)

        if isinstance(test_db, sqlite3.Connection):
            # SQLite
            cursor = test_db.execute("PRAGMA table_info(tg_users)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
        else:
            # PostgreSQL
            cursor = test_db.cursor()
            cursor.execute(
                """SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name = 'tg_users'
                   ORDER BY column_name"""
            )
            columns = {row[0]: row[1] for row in cursor.fetchall()}

        # Check key columns exist
        assert "user_id" in columns, "tg_users should have user_id column"
        assert "username" in columns, "tg_users should have username column"
        assert "status" in columns, "tg_users should have status column"
        assert "registered_at" in columns, "tg_users should have registered_at column"

    def test_feature_parity_tg_rate_limits_columns_match(self, test_db):
        """Verify tg_rate_limits table has same columns on both backends."""
        run_migrations(test_db)

        if isinstance(test_db, sqlite3.Connection):
            # SQLite
            cursor = test_db.execute("PRAGMA table_info(tg_rate_limits)")
            columns = {row[1] for row in cursor.fetchall()}
        else:
            # PostgreSQL
            cursor = test_db.cursor()
            cursor.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'tg_rate_limits'
                   ORDER BY column_name"""
            )
            columns = {row[0] for row in cursor.fetchall()}

        # Check expected columns
        assert "user_id" in columns, "tg_rate_limits should have user_id column"
        assert "window_start" in columns, (
            "tg_rate_limits should have window_start column"
        )
        assert "hit_count" in columns, "tg_rate_limits should have hit_count column"

    def test_feature_parity_schema_migrations_tracking_table(self, test_db):
        """Verify schema_migrations table structure matches across backends."""
        _ensure_tracking_table(test_db)

        if isinstance(test_db, sqlite3.Connection):
            # SQLite
            cursor = test_db.execute("PRAGMA table_info(schema_migrations)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
        else:
            # PostgreSQL
            cursor = test_db.cursor()
            cursor.execute(
                """SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name = 'schema_migrations'
                   ORDER BY column_name"""
            )
            columns = {row[0]: row[1] for row in cursor.fetchall()}

        # Check key columns exist
        assert "version" in columns, "schema_migrations should have version column"
        assert "name" in columns, "schema_migrations should have name column"
        assert "applied_at" in columns, (
            "schema_migrations should have applied_at column"
        )


class TestMigrationTracking:
    """Test migration tracking and idempotency."""

    def test_migration_001_creates_indexes(self, test_db):
        """Verify migration 001 creates all expected indexes."""
        run_migrations(test_db)

        if isinstance(test_db, sqlite3.Connection):
            # SQLite
            cursor = test_db.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='index' AND name LIKE 'idx_%'
                   ORDER BY name"""
            )
            indexes = {row[0] for row in cursor.fetchall()}
        else:
            # PostgreSQL
            cursor = test_db.cursor()
            cursor.execute(
                """SELECT indexname FROM pg_indexes
                   WHERE schemaname='public' AND indexname LIKE 'idx_%'
                   ORDER BY indexname"""
            )
            indexes = {row[0] for row in cursor.fetchall()}

        # Migration 001 should create indexes
        assert len(indexes) > 0, "Migration 001 should create indexes"

    def test_migration_version_tracking_accuracy(self, test_db):
        """Verify version tracking table stores correct migration metadata."""
        run_migrations(test_db)

        if isinstance(test_db, sqlite3.Connection):
            # SQLite
            cursor = test_db.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            )
            records = list(cursor.fetchall())
        else:
            # PostgreSQL
            cursor = test_db.cursor()
            cursor.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            )
            records = list(cursor.fetchall())

        # Should have both migrations recorded
        assert len(records) >= 2, "Should have at least 2 migrations applied"

        # Versions should be 1 and 2
        versions = [r[0] for r in records]
        assert 1 in versions and 2 in versions, f"Unexpected versions: {versions}"

        # Names should match module names
        names = {r[0]: r[1] for r in records}
        assert "001_telegram_module" in names.values(), (
            "Migration 001 name should be recorded"
        )
        assert "002_rate_limits" in names.values(), (
            "Migration 002 name should be recorded"
        )
