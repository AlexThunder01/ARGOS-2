"""
Integration tests for POST /api/upload and attachment injection in /run and /api/chat/stream.
Uses the same pattern as tests/api/test_api.py (TestClient + ARGOS_PERMISSIVE_MODE).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ["ARGOS_API_KEY"] = "test_key"
os.environ["ARGOS_PERMISSIVE_MODE"] = "false"
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")

import pytest

import src.upload as upload_module


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch, tmp_path):
    """Isolate upload storage between tests."""
    monkeypatch.setattr(upload_module, "_registry", {})
    monkeypatch.setattr(upload_module, "_get_upload_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(upload_module, "_get_max_bytes", lambda: 20 * 1024 * 1024)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """TestClient with patched DB and OTel disabled."""
    import sqlite3
    import unittest.mock as _mock

    fake_conn = sqlite3.connect(":memory:")
    fake_conn.row_factory = sqlite3.Row
    monkeypatch.setattr("src.db.connection.get_connection", lambda: fake_conn)
    monkeypatch.setattr("src.db.connection.DB_BACKEND", "sqlite")

    # Disable OTel
    with _mock.patch("src.logging.otel.init_otel", return_value=None):
        with _mock.patch("src.logging.tracer.setup_tracer", return_value=None):
            from fastapi.testclient import TestClient

            from api.server import app

            yield TestClient(app, raise_server_exceptions=True)


# ── POST /api/upload ───────────────────────────────────────────────────────


class TestUploadEndpoint:
    def test_upload_valid_pdf_returns_upload_id(self, client):
        res = client.post(
            "/api/upload",
            files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
            headers={"X-ARGOS-API-KEY": "test_key"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "upload_id" in data
        assert data["filename"] == "report.pdf"
        # upload_id should be a valid UUID
        assert len(data["upload_id"]) == 36

    def test_upload_without_api_key_returns_403(self, client, monkeypatch):
        import api.security as sec_module

        monkeypatch.setattr(sec_module, "_PERMISSIVE_MODE", False)
        monkeypatch.setattr(sec_module, "ARGOS_API_KEY", "test_key")
        res = client.post(
            "/api/upload",
            files={"file": ("report.pdf", b"%PDF", "application/pdf")},
        )
        assert res.status_code == 403

    def test_upload_invalid_extension_returns_422(self, client):
        res = client.post(
            "/api/upload",
            files={"file": ("virus.exe", b"MZ payload", "application/octet-stream")},
            headers={"X-ARGOS-API-KEY": "test_key"},
        )
        assert res.status_code == 422
        assert "not supported" in res.json()["detail"].lower()

    def test_upload_oversized_file_returns_422(self, client, monkeypatch):
        monkeypatch.setattr(upload_module, "_get_max_bytes", lambda: 10)
        res = client.post(
            "/api/upload",
            files={"file": ("data.csv", b"a" * 100, "text/csv")},
            headers={"X-ARGOS-API-KEY": "test_key"},
        )
        assert res.status_code == 422
        assert "large" in res.json()["detail"].lower()

    def test_upload_csv_returns_upload_id(self, client):
        res = client.post(
            "/api/upload",
            files={"file": ("data.csv", b"col1,col2\n1,2", "text/csv")},
            headers={"X-ARGOS-API-KEY": "test_key"},
        )
        assert res.status_code == 200
        assert "upload_id" in res.json()


# ── POST /run with attachments ─────────────────────────────────────────────


class TestRunWithAttachments:
    def _upload_file(self, client):
        res = client.post(
            "/api/upload",
            files={"file": ("note.txt", b"hello world", "text/plain")},
            headers={"X-ARGOS-API-KEY": "test_key"},
        )
        assert res.status_code == 200
        return res.json()["upload_id"]

    def _make_fake_result(self):
        from unittest.mock import AsyncMock, MagicMock

        from src.core.engine import TaskResult

        result = MagicMock(spec=TaskResult)
        result.response = "Done"
        result.success = True
        result.steps_executed = 0
        result.history = []
        return result

    def test_run_with_attachment_injects_context(self, client, monkeypatch):
        from unittest.mock import AsyncMock, patch

        upload_id = self._upload_file(client)
        captured_task = {}

        async def _fake_run_async(self_agent, task):
            captured_task["task"] = task
            return self._make_fake_result()

        with patch("src.core.engine.CoreAgent.run_task_async", _fake_run_async):
            res = client.post(
                "/run",
                json={"task": "analyze the file", "attachments": [upload_id]},
                headers={"X-ARGOS-API-KEY": "test_key"},
            )

        assert res.status_code == 200
        assert "ATTACHMENTS" in captured_task.get("task", "")
        assert "note.txt" in captured_task.get("task", "")

    def test_run_with_empty_attachments_is_clean(self, client, monkeypatch):
        from unittest.mock import patch

        captured_task = {}

        async def _fake_run_async(self_agent, task):
            captured_task["task"] = task
            return self._make_fake_result()

        with patch("src.core.engine.CoreAgent.run_task_async", _fake_run_async):
            res = client.post(
                "/run",
                json={"task": "just a task", "attachments": []},
                headers={"X-ARGOS-API-KEY": "test_key"},
            )

        assert res.status_code == 200
        assert "ATTACHMENTS" not in captured_task.get("task", "")
