"""
Unit tests for scripts/inject_n8n.py.

patch_workflow() is a pure function (no network I/O) — fully testable.
Credential creation helpers are tested by mocking requests.post.
"""

import copy
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure the project root is on the path so scripts/ can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# inject_n8n imports n8n_client at module level — stub it before importing
sys.modules.setdefault(
    "n8n_client",
    MagicMock(get_n8n_config=lambda: ("http://localhost:5678/api/v1", {})),
)

from scripts.inject_n8n import (  # noqa: E402
    create_gmail_credential,
    create_telegram_credential,
    patch_workflow,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def telegram_node():
    return {
        "name": "Send Notification",
        "type": "n8n-nodes-base.telegram",
        "parameters": {"chatId": "YOUR_TELEGRAM_CHAT_ID", "text": "hello"},
        "credentials": {"telegramApi": {"id": "OLD_ID", "name": "old name"}},
    }


@pytest.fixture
def gmail_node():
    return {
        "name": "Read Emails",
        "type": "n8n-nodes-base.gmailTrigger",
        "parameters": {},
        "credentials": {"gmailOAuth2": {"id": "OLD_GMAIL", "name": "Gmail account"}},
    }


@pytest.fixture
def basic_workflow(telegram_node, gmail_node):
    return {"name": "Test Workflow", "nodes": [telegram_node, gmail_node]}


# ---------------------------------------------------------------------------
# patch_workflow — credential injection
# ---------------------------------------------------------------------------


class TestPatchWorkflow:
    def test_telegram_credential_replaced(self, basic_workflow):
        patched = patch_workflow(basic_workflow, "TG_CRED_123", None, None)
        tg_node = next(n for n in patched["nodes"] if n["name"] == "Send Notification")
        assert tg_node["credentials"]["telegramApi"]["id"] == "TG_CRED_123"
        assert tg_node["credentials"]["telegramApi"]["name"] == "Telegram account"

    def test_gmail_credential_replaced(self, basic_workflow):
        patched = patch_workflow(basic_workflow, None, "GMAIL_CRED_456", None)
        gmail_node = next(n for n in patched["nodes"] if n["name"] == "Read Emails")
        assert gmail_node["credentials"]["gmailOAuth2"]["id"] == "GMAIL_CRED_456"

    def test_chat_id_injected(self, basic_workflow):
        patched = patch_workflow(basic_workflow, "TG", None, "123456789")
        tg_node = next(n for n in patched["nodes"] if n["name"] == "Send Notification")
        assert tg_node["parameters"]["chatId"] == "123456789"

    def test_chat_id_not_replaced_when_none(self, basic_workflow):
        patched = patch_workflow(basic_workflow, "TG", None, None)
        tg_node = next(n for n in patched["nodes"] if n["name"] == "Send Notification")
        assert tg_node["parameters"]["chatId"] == "YOUR_TELEGRAM_CHAT_ID"

    def test_original_workflow_not_mutated(self, basic_workflow):
        original = copy.deepcopy(basic_workflow)
        patch_workflow(basic_workflow, "NEW_ID", "GMAIL_ID", "99999")
        assert basic_workflow == original

    def test_chat_workflow_uses_chat_bot_credential(self, telegram_node):
        workflow = {"name": "05_telegram_chat", "nodes": [telegram_node]}
        patched = patch_workflow(
            workflow,
            telegram_cred_id="HITL_CRED",
            gmail_cred_id=None,
            telegram_chat_id=None,
            chat_bot_cred_id="CHAT_BOT_CRED",
            is_chat_workflow=True,
        )
        tg_node = patched["nodes"][0]
        assert tg_node["credentials"]["telegramApi"]["id"] == "CHAT_BOT_CRED"
        assert tg_node["credentials"]["telegramApi"]["name"] == "Telegram Chat Bot"

    def test_non_chat_workflow_uses_hitl_credential(self, telegram_node):
        workflow = {"name": "01_notifications", "nodes": [telegram_node]}
        patched = patch_workflow(
            workflow,
            telegram_cred_id="HITL_CRED",
            gmail_cred_id=None,
            telegram_chat_id=None,
            chat_bot_cred_id="CHAT_BOT_CRED",
            is_chat_workflow=False,
        )
        tg_node = patched["nodes"][0]
        assert tg_node["credentials"]["telegramApi"]["id"] == "HITL_CRED"

    def test_missing_credentials_key_added_for_telegram_trigger(self):
        node = {
            "name": "Trigger",
            "type": "n8n-nodes-base.telegramTrigger",
            "parameters": {},
        }
        workflow = {"name": "wf", "nodes": [node]}
        patched = patch_workflow(workflow, "TG_CRED", None, None)
        assert "credentials" in patched["nodes"][0]
        assert patched["nodes"][0]["credentials"]["telegramApi"]["id"] == "TG_CRED"

    def test_missing_credentials_key_added_for_gmail_trigger(self):
        node = {
            "name": "Gmail Trigger",
            "type": "n8n-nodes-base.gmailTrigger",
            "parameters": {},
        }
        workflow = {"name": "wf", "nodes": [node]}
        patched = patch_workflow(workflow, None, "GMAIL_CRED", None)
        assert patched["nodes"][0]["credentials"]["gmailOAuth2"]["id"] == "GMAIL_CRED"

    def test_no_credentials_passed_leaves_nodes_unchanged(self, basic_workflow):
        patched = patch_workflow(basic_workflow, None, None, None)
        tg_node = next(n for n in patched["nodes"] if n["name"] == "Send Notification")
        assert tg_node["credentials"]["telegramApi"]["id"] == "OLD_ID"


# ---------------------------------------------------------------------------
# create_telegram_credential — HTTP call mocking
# ---------------------------------------------------------------------------


class TestCreateTelegramCredential:
    def test_returns_id_on_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": "abc123"}

        with patch("scripts.inject_n8n.requests.post", return_value=mock_resp):
            result = create_telegram_credential("http://n8n/api/v1", {}, "BOT_TOKEN")

        assert result == "abc123"

    def test_returns_none_on_failure(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"

        with patch("scripts.inject_n8n.requests.post", return_value=mock_resp):
            result = create_telegram_credential("http://n8n/api/v1", {}, "BAD_TOKEN")

        assert result is None

    def test_id_extracted_from_nested_data_key(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": "nested_id_99"}}

        with patch("scripts.inject_n8n.requests.post", return_value=mock_resp):
            result = create_telegram_credential("http://n8n/api/v1", {}, "TOKEN")

        assert result == "nested_id_99"


# ---------------------------------------------------------------------------
# create_gmail_credential — HTTP call mocking
# ---------------------------------------------------------------------------


class TestCreateGmailCredential:
    def test_returns_id_on_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "gmail_xyz"}

        with patch("scripts.inject_n8n.requests.post", return_value=mock_resp):
            result = create_gmail_credential(
                "http://n8n/api/v1", {}, "CLIENT_ID", "SECRET"
            )

        assert result == "gmail_xyz"

    def test_returns_none_on_failure(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch("scripts.inject_n8n.requests.post", return_value=mock_resp):
            result = create_gmail_credential("http://n8n/api/v1", {}, "ID", "SECRET")

        assert result is None
