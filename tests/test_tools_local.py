"""
Test dei Tool Locali — Verifica che il TOOLS dict sia completo
e che le funzioni non-GUI (filesystem, search, stats) funzionino correttamente.

Tutti i test sono pytest-compatible (funzioni prefissate con test_).
Le chiamate di rete sono mocked per evitare flaky test nella CI.
"""
import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from src.tools import TOOLS


# ==========================================================================
# Tool Registry
# ==========================================================================

EXPECTED_TOOLS = [
    "finance_price", "crypto_price", "web_search", "system_stats",
    "list_files", "read_file", "create_file", "modify_file",
    "rename_file", "delete_file", "launch_app", "keyboard_type",
    "visual_click", "describe_screen", "create_directory", "delete_directory"
]


def test_tools_dict_complete():
    """All 16 expected tools must be registered."""
    assert len(TOOLS) == 16
    for name in EXPECTED_TOOLS:
        assert name in TOOLS, f"Missing tool: {name}"


def test_all_tools_are_callable():
    """Every registered tool must be a callable function."""
    for name, fn in TOOLS.items():
        assert callable(fn), f"Tool '{name}' is not callable"


# ==========================================================================
# System Stats (no network needed)
# ==========================================================================

def test_system_stats():
    result = TOOLS["system_stats"]({})
    assert "CPU" in result
    assert "RAM" in result


# ==========================================================================
# Filesystem Tools (isolated temp directory)
# ==========================================================================

class TestFilesystemTools:

    def test_create_read_modify_delete_lifecycle(self, tmp_path):
        test_file = str(tmp_path / "test_argos.txt")

        # Create
        result = TOOLS["create_file"]({"path": test_file, "content": "Hello World"})
        assert "Created" in result

        # Read
        result = TOOLS["read_file"]({"path": test_file})
        assert "Hello World" in result

        # Modify (overwrite)
        result = TOOLS["modify_file"]({"path": test_file, "content": "Updated", "mode": "write"})
        assert "Modified" in result

        # Delete
        result = TOOLS["delete_file"]({"path": test_file})
        assert "Deleted" in result

    def test_create_and_delete_directory(self, tmp_path):
        test_dir = str(tmp_path / "test_dir")
        result = TOOLS["create_directory"]({"path": test_dir})
        assert "created" in result.lower()

        result = TOOLS["delete_directory"]({"path": test_dir})
        assert "deleted" in result.lower()

    def test_list_files_home(self):
        result = TOOLS["list_files"]({"path": os.path.expanduser("~")})
        assert "📂" in result

    def test_read_nonexistent_file(self):
        result = TOOLS["read_file"]({"path": "/tmp/this_file_does_not_exist_argos.txt"})
        assert "not found" in result.lower()

    def test_rename_file(self, tmp_path):
        old = str(tmp_path / "old.txt")
        new = str(tmp_path / "new.txt")
        with open(old, "w") as f:
            f.write("test")
        result = TOOLS["rename_file"]({"old_path": old, "new_path": new})
        assert "Renamed" in result


# ==========================================================================
# Network Tools (mocked for CI stability)
# ==========================================================================

class TestNetworkToolsMocked:

    @patch("src.tools.finance.requests.get")
    def test_crypto_price_mocked(self, mock_get):
        mock_get.return_value.json.return_value = {"bitcoin": {"eur": 45000.50}}
        result = TOOLS["crypto_price"]({"coin": "bitcoin"})
        assert "45" in result or "€" in result

    @patch("src.tools.web.DDGS", create=True)
    def test_web_search_mocked(self, mock_ddgs_cls):
        mock_instance = MagicMock()
        mock_instance.text.return_value = [
            {"title": "Test Result", "body": "This is a test."}
        ]
        mock_ddgs_cls.return_value = mock_instance

        # We need to patch at the import location inside the function
        with patch("ddgs.DDGS", mock_ddgs_cls):
            result = TOOLS["web_search"]({"query": "test"})
            assert "Test Result" in result or "test" in result.lower()
