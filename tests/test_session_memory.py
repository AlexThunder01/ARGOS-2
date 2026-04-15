"""
Tests for src/core/session_memory.py — SessionMemory.

Coverage:
  - record_tool_call()   : increments the internal counter
  - should_update()      : fires every UPDATE_EVERY_N calls, not before
  - update()             : writes memory file when LLM call succeeds
  - update()             : skips write on LLM error response
  - update()             : skips write when history is too short
  - load()               : reads from in-memory cache first
  - load()               : falls back to disk file when cache is empty
  - load()               : returns empty string when no file exists
  - load()               : strips HTML comment header added by update()
  - clear()              : resets counter + cache + deletes file
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.session_memory import _UPDATE_EVERY_N, SessionMemory

# ==========================================================================
# Fixtures
# ==========================================================================


@pytest.fixture
def tmp_memory(tmp_path) -> SessionMemory:
    """Returns a SessionMemory backed by a temporary file."""
    return SessionMemory(memory_path=tmp_path / "session.md")


def _make_history(n: int = 5) -> list[dict]:
    history = [{"role": "system", "content": "You are ARGOS."}]
    for i in range(n):
        history.append({"role": "user", "content": f"User message {i}"})
        history.append({"role": "assistant", "content": f"Response {i}"})
    return history


# ==========================================================================
# record_tool_call() + should_update()
# ==========================================================================


class TestToolCallCounter:
    def test_should_update_false_before_any_calls(self, tmp_memory):
        assert tmp_memory.should_update() is False

    def test_should_update_false_below_threshold(self, tmp_memory):
        for _ in range(_UPDATE_EVERY_N - 1):
            tmp_memory.record_tool_call()
        assert tmp_memory.should_update() is False

    def test_should_update_true_at_threshold(self, tmp_memory):
        for _ in range(_UPDATE_EVERY_N):
            tmp_memory.record_tool_call()
        assert tmp_memory.should_update() is True

    def test_should_update_true_at_multiple_of_threshold(self, tmp_memory):
        for _ in range(_UPDATE_EVERY_N * 3):
            tmp_memory.record_tool_call()
        assert tmp_memory.should_update() is True

    def test_should_update_false_one_past_threshold(self, tmp_memory):
        for _ in range(_UPDATE_EVERY_N + 1):
            tmp_memory.record_tool_call()
        assert tmp_memory.should_update() is False

    def test_counter_increments_monotonically(self, tmp_memory):
        for i in range(1, 6):
            tmp_memory.record_tool_call()
            assert tmp_memory._tool_call_count == i


# ==========================================================================
# update()
# ==========================================================================


class TestUpdate:
    def test_writes_file_on_success(self, tmp_memory):
        llm_fn = MagicMock(return_value="- Current task: list files\n- Next: done")
        tmp_memory.update(_make_history(), llm_fn)
        assert tmp_memory._path.exists()

    def test_file_contains_llm_content(self, tmp_memory):
        content = "- Working on: reading config.yaml"
        llm_fn = MagicMock(return_value=content)
        tmp_memory.update(_make_history(), llm_fn)
        written = tmp_memory._path.read_text()
        assert content in written

    def test_file_has_timestamp_comment(self, tmp_memory):
        llm_fn = MagicMock(return_value="memory content")
        tmp_memory.update(_make_history(), llm_fn)
        written = tmp_memory._path.read_text()
        assert written.startswith("<!-- Session memory")

    def test_updates_in_memory_cache(self, tmp_memory):
        content = "task: send email"
        llm_fn = MagicMock(return_value=content)
        tmp_memory.update(_make_history(), llm_fn)
        assert tmp_memory._last_content == content

    def test_skips_write_on_api_error(self, tmp_memory):
        llm_fn = MagicMock(return_value="API Error.")
        tmp_memory.update(_make_history(), llm_fn)
        assert not tmp_memory._path.exists()
        assert tmp_memory._last_content == ""

    def test_skips_write_on_connection_error(self, tmp_memory):
        llm_fn = MagicMock(return_value="Connection Error: timeout")
        tmp_memory.update(_make_history(), llm_fn)
        assert not tmp_memory._path.exists()

    def test_skips_write_on_empty_response(self, tmp_memory):
        llm_fn = MagicMock(return_value="")
        tmp_memory.update(_make_history(), llm_fn)
        assert not tmp_memory._path.exists()

    def test_skips_when_history_too_short(self, tmp_memory):
        short_history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        llm_fn = MagicMock(return_value="memory")
        tmp_memory.update(short_history, llm_fn)
        llm_fn.assert_not_called()

    def test_does_not_crash_on_llm_exception(self, tmp_memory):
        def raising_fn(msgs):
            raise RuntimeError("network failure")

        tmp_memory.update(_make_history(), raising_fn)  # must not raise


# ==========================================================================
# load()
# ==========================================================================


class TestLoad:
    def test_returns_empty_string_when_no_file(self, tmp_memory):
        result = tmp_memory.load()
        assert result == ""

    def test_returns_cache_without_disk_read(self, tmp_memory):
        tmp_memory._last_content = "cached content"
        result = tmp_memory.load()
        assert result == "cached content"

    def test_reads_from_disk_when_cache_empty(self, tmp_memory):
        tmp_memory._path.write_text(
            "<!-- Session memory — 2026-04-14 10:00 -->\ndisk content\n"
        )
        result = tmp_memory.load()
        assert "disk content" in result

    def test_strips_html_comment_header(self, tmp_memory):
        tmp_memory._path.write_text(
            "<!-- Session memory — 2026-04-14 10:00 -->\nactual memory\n"
        )
        result = tmp_memory.load()
        assert "<!--" not in result
        assert "actual memory" in result

    def test_full_roundtrip_update_then_load(self, tmp_memory):
        content = "- task: create file\n- next: verify"
        llm_fn = MagicMock(return_value=content)
        tmp_memory.update(_make_history(), llm_fn)
        # Reset cache to force disk read
        tmp_memory._last_content = ""
        result = tmp_memory.load()
        assert content in result

    def test_returns_empty_on_unreadable_file(self, tmp_memory, monkeypatch):
        tmp_memory._path.write_text("content")
        monkeypatch.setattr(
            "src.core.session_memory.Path.read_text",
            lambda *a, **kw: (_ for _ in ()).throw(PermissionError("denied")),
        )
        result = tmp_memory.load()
        assert result == ""


# ==========================================================================
# clear()
# ==========================================================================


class TestClear:
    def test_clear_resets_counter(self, tmp_memory):
        tmp_memory._tool_call_count = 10
        tmp_memory.clear()
        assert tmp_memory._tool_call_count == 0

    def test_clear_resets_cache(self, tmp_memory):
        tmp_memory._last_content = "some memory"
        tmp_memory.clear()
        assert tmp_memory._last_content == ""

    def test_clear_deletes_file(self, tmp_memory):
        tmp_memory._path.write_text("memory content")
        assert tmp_memory._path.exists()
        tmp_memory.clear()
        assert not tmp_memory._path.exists()

    def test_clear_noop_when_no_file(self, tmp_memory):
        # Should not raise even if file doesn't exist
        tmp_memory.clear()
        assert tmp_memory._last_content == ""

    def test_load_returns_empty_after_clear(self, tmp_memory):
        llm_fn = MagicMock(return_value="memory content")
        tmp_memory.update(_make_history(), llm_fn)
        tmp_memory.clear()
        result = tmp_memory.load()
        assert result == ""
