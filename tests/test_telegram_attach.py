"""
Tests for POST /telegram/attach — Telegram file download proxy.
Uses httpx mocking (respx) to avoid real Telegram API calls.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DB_BACKEND"] = "sqlite"
os.environ["ARGOS_API_KEY"] = "test_key"
os.environ["ARGOS_PERMISSIVE_MODE"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = "fake_bot_token_123"
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")

import pytest

import src.upload as upload_module


@pytest.fixture(autouse=True)
def _reset_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(upload_module, "_registry", {})
    monkeypatch.setattr(upload_module, "_get_upload_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(upload_module, "_get_max_bytes", lambda: 20 * 1024 * 1024)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import sqlite3
    import unittest.mock as _mock

    fake_conn = sqlite3.connect(":memory:")
    fake_conn.row_factory = sqlite3.Row
    monkeypatch.setattr("src.db.connection.get_connection", lambda: fake_conn)
    monkeypatch.setattr("src.db.connection.DB_BACKEND", "sqlite")

    with _mock.patch("src.logging.otel.init_otel", return_value=None):
        with _mock.patch("src.logging.tracer.setup_tracer", return_value=None):
            from fastapi.testclient import TestClient

            from api.server import app

            yield TestClient(app, raise_server_exceptions=True)


# ── POST /telegram/attach ──────────────────────────────────────────────────


class TestTelegramAttach:
    def _make_request(self, client, file_id="abc123", filename="doc.pdf", user_id=42):
        return client.post(
            "/telegram/attach",
            json={"file_id": file_id, "filename": filename, "user_id": user_id},
            headers={"X-ARGOS-API-KEY": "test_key"},
        )

    def test_attach_without_api_key_returns_403(self, client, monkeypatch):
        import api.security as sec_module

        monkeypatch.setattr(sec_module, "_PERMISSIVE_MODE", False)
        monkeypatch.setattr(sec_module, "ARGOS_API_KEY", "test_key")
        res = client.post(
            "/telegram/attach",
            json={"file_id": "abc", "filename": "doc.pdf", "user_id": 1},
        )
        assert res.status_code == 403

    def test_attach_with_missing_bot_token_returns_500(self, client, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        res = self._make_request(client)
        assert res.status_code == 500
        assert "not configured" in res.json()["detail"].lower()

    def test_attach_telegram_getfile_failure_returns_502(self, client, monkeypatch):
        """Simulate Telegram returning a non-success for getFile."""
        from unittest.mock import AsyncMock, MagicMock, patch

        import httpx

        async def _mock_get(*args, **kwargs):
            resp = MagicMock()
            resp.is_success = False
            resp.status_code = 400
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = _mock_get

        with patch("api.routes.telegram.httpx.AsyncClient", return_value=mock_client):
            res = self._make_request(client)
        assert res.status_code == 502

    def test_attach_invalid_filename_extension_returns_422(self, client, monkeypatch):
        """Simulate Telegram returning a valid file but filename is .exe."""
        from unittest.mock import AsyncMock, MagicMock, patch

        import httpx

        fake_content = b"MZ payload"
        call_count = {"n": 0}

        async def _mock_get(url, **kwargs):
            resp = MagicMock()
            resp.is_success = True
            resp.status_code = 200
            resp.json.return_value = {"result": {"file_path": "files/file.exe"}}
            resp.content = fake_content
            resp.raise_for_status = MagicMock()
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = _mock_get

        with patch("api.routes.telegram.httpx.AsyncClient", return_value=mock_client):
            res = self._make_request(client, filename="virus.exe")
        assert res.status_code == 422

    def test_attach_valid_pdf_returns_upload_id(self, client, monkeypatch):
        """Full happy path: Telegram returns a PDF, we get an upload_id."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_pdf = b"%PDF-1.4 fake content"

        async def _mock_get(url, **kwargs):
            resp = MagicMock()
            resp.is_success = True
            resp.status_code = 200
            resp.json.return_value = {"result": {"file_path": "files/doc.pdf"}}
            resp.content = fake_pdf
            resp.raise_for_status = MagicMock()
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = _mock_get

        with patch("api.routes.telegram.httpx.AsyncClient", return_value=mock_client):
            res = self._make_request(client, filename="report.pdf")

        assert res.status_code == 200
        data = res.json()
        assert "upload_id" in data
        assert data["filename"] == "report.pdf"
        assert len(data["upload_id"]) == 36


# ── POST /telegram/chat with attachments ──────────────────────────────────


class TestTelegramChatWithAttachments:
    def test_chat_with_attachments_injects_context(self, client, monkeypatch):
        """Verify that attachments list is injected as system message."""
        from unittest.mock import MagicMock, patch

        # Pre-register an upload_id in the registry
        uid = upload_module.save_upload(
            user_id=42, filename="voice.ogg", content=b"OGG fake"
        )

        # Patch the Telegram agent and DB calls (local imports inside the route)
        with (
            patch(
                "src.telegram.db.db_get_user",
                return_value={"status": "approved", "msg_count_total": 1},
            ),
            patch(
                "src.telegram.db.db_get_profile", return_value={"display_name": "Test"}
            ),
            patch("src.telegram.db.db_get_conversation_window", return_value=[]),
            patch("src.telegram.memory.retrieve_relevant_memories", return_value=[]),
            patch("src.telegram.db.db_get_open_tasks", return_value=[]),
            patch("src.telegram.db.db_increment_msg_count"),
            patch("src.telegram.db.db_save_conversation_turn"),
            patch(
                "src.telegram.prompt.build_telegram_system_prompt", return_value="sys"
            ),
            patch("src.workflows_config.get_workflows_config") as mock_cfg,
        ):
            cfg = MagicMock()
            cfg.is_telegram_enabled = True
            cfg.telegram_max_input_length = 4000
            cfg.telegram_conversation_window = 10
            cfg.telegram_max_memories = 5
            cfg.telegram_rag_threshold = 0.5
            cfg.telegram_config = {}
            mock_cfg.return_value = cfg

            captured_messages = {}

            def _fake_think(messages):
                captured_messages["msgs"] = messages
                return "OK"

            with patch("api.routes.telegram.telegram_breaker") as mock_breaker:
                mock_breaker.call.side_effect = lambda fn, *a, **kw: fn(*a, **kw)

                with patch.object(
                    upload_module,
                    "resolve_upload_id",
                    wraps=upload_module.resolve_upload_id,
                ):
                    agent_mock = MagicMock()
                    agent_mock.think_with_context.side_effect = _fake_think

                    with patch(
                        "api.routes.telegram._get_telegram_agent",
                        return_value=agent_mock,
                    ):
                        res = client.post(
                            "/telegram/chat",
                            json={
                                "user_id": 42,
                                "chat_id": 42,
                                "text": "transcribe this",
                                "attachments": [uid],
                            },
                            headers={"X-ARGOS-API-KEY": "test_key"},
                        )

        assert res.status_code == 200
        # The messages list should contain an ATTACHMENTS system message
        msgs = captured_messages.get("msgs", [])
        attachment_msgs = [m for m in msgs if "ATTACHMENTS" in m.get("content", "")]
        assert len(attachment_msgs) == 1
        assert "transcribe_audio" in attachment_msgs[0]["content"]
