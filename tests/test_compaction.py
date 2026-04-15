"""
Tests for src/core/compaction.py — compact_conversation().

Coverage:
  - compact_conversation()  : returns compacted history on success
  - compact_conversation()  : strips <analysis> scratchpad block
  - compact_conversation()  : falls back to original history on LLM error
  - compact_conversation()  : falls back when LLM returns empty string
  - compact_conversation()  : noop when history is below COMPACT_MIN_MESSAGES
  - compact_conversation()  : always preserves the system message as history[0]
  - compact_conversation()  : handles <summary> wrapper tags from model output
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src.core.compaction import COMPACT_MIN_MESSAGES, compact_conversation

# ==========================================================================
# Fixtures
# ==========================================================================


def _make_history(n_extra: int) -> list[dict]:
    """Returns a history with a system message and n_extra user/assistant pairs."""
    history = [{"role": "system", "content": "You are ARGOS."}]
    for i in range(n_extra):
        history.append({"role": "user", "content": f"User message {i}"})
        history.append({"role": "assistant", "content": f"Assistant response {i}"})
    return history


GOOD_SUMMARY = """\
1. Primary Request and Intent: List files
2. Key Technical Concepts: filesystem
3. Files and Code Sections: /tmp/test.txt
4. Tool Results and Actions: list_files: ['test.txt']
5. Errors and Fixes: none
6. User Messages: "List files"
7. Pending Tasks: none
8. Current Work: listing files
9. Next Step: done
"""

SUMMARY_WITH_ANALYSIS = f"""\
<analysis>
This is the private reasoning block. It should be stripped.
</analysis>
{GOOD_SUMMARY}
"""

SUMMARY_WITH_TAGS = f"<summary>\n{GOOD_SUMMARY}\n</summary>"

SUMMARY_WITH_BOTH = (
    f"<analysis>\nreasoning\n</analysis>\n<summary>\n{GOOD_SUMMARY}\n</summary>"
)


# ==========================================================================
# compact_conversation()
# ==========================================================================


class TestCompactConversation:
    def test_returns_compacted_history_on_success(self):
        history = _make_history(n_extra=4)  # 9 messages total ≥ COMPACT_MIN_MESSAGES
        result = compact_conversation(history, lambda msgs: GOOD_SUMMARY)
        # Compacted: system + summary_user + ack_assistant = 3 messages
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"

    def test_system_message_preserved_as_first(self):
        history = _make_history(n_extra=4)
        result = compact_conversation(history, lambda msgs: GOOD_SUMMARY)
        assert result[0] == history[0]

    def test_summary_injected_as_user_message(self):
        history = _make_history(n_extra=4)
        result = compact_conversation(history, lambda msgs: GOOD_SUMMARY)
        assert "CONVERSATION SUMMARY" in result[1]["content"]
        assert "Primary Request" in result[1]["content"]

    def test_analysis_block_stripped(self):
        history = _make_history(n_extra=4)
        result = compact_conversation(history, lambda msgs: SUMMARY_WITH_ANALYSIS)
        assert "<analysis>" not in result[1]["content"]
        assert "private reasoning" not in result[1]["content"]
        assert "Primary Request" in result[1]["content"]

    def test_summary_wrapper_tags_stripped(self):
        history = _make_history(n_extra=4)
        result = compact_conversation(history, lambda msgs: SUMMARY_WITH_TAGS)
        assert "<summary>" not in result[1]["content"]
        assert "</summary>" not in result[1]["content"]
        assert "Primary Request" in result[1]["content"]

    def test_both_analysis_and_summary_tags_stripped(self):
        history = _make_history(n_extra=4)
        result = compact_conversation(history, lambda msgs: SUMMARY_WITH_BOTH)
        assert "<analysis>" not in result[1]["content"]
        assert "<summary>" not in result[1]["content"]
        assert "Primary Request" in result[1]["content"]

    def test_fallback_on_llm_api_error(self):
        history = _make_history(n_extra=4)
        result = compact_conversation(history, lambda msgs: "API Error.")
        assert result is history  # same object — no copy

    def test_fallback_on_connection_error(self):
        history = _make_history(n_extra=4)
        result = compact_conversation(history, lambda msgs: "Connection Error: timeout")
        assert result is history

    def test_fallback_on_empty_response(self):
        history = _make_history(n_extra=4)
        result = compact_conversation(history, lambda msgs: "")
        assert result is history

    def test_fallback_on_analysis_only_response(self):
        """If model returns only <analysis> with no summary, result is empty — fallback."""
        history = _make_history(n_extra=4)
        analysis_only = "<analysis>just reasoning, no summary</analysis>"
        result = compact_conversation(history, lambda msgs: analysis_only)
        assert result is history

    def test_fallback_on_llm_exception(self):
        history = _make_history(n_extra=4)

        def raising_fn(msgs):
            raise RuntimeError("network failure")

        result = compact_conversation(history, raising_fn)
        assert result is history

    def test_noop_below_compact_min_messages(self):
        """History shorter than COMPACT_MIN_MESSAGES must be returned unchanged."""
        history = _make_history(n_extra=1)  # 3 messages: system + 2
        assert len(history) < COMPACT_MIN_MESSAGES
        result = compact_conversation(history, lambda msgs: GOOD_SUMMARY)
        assert result is history

    def test_exactly_at_min_messages_is_compacted(self):
        """History with exactly COMPACT_MIN_MESSAGES should be compacted."""
        # Need exactly COMPACT_MIN_MESSAGES messages total
        n_extra = (COMPACT_MIN_MESSAGES - 1) // 2
        history = _make_history(n_extra=n_extra)
        # Pad to exact threshold if needed
        while len(history) < COMPACT_MIN_MESSAGES:
            history.append({"role": "user", "content": "extra"})
        assert len(history) >= COMPACT_MIN_MESSAGES
        result = compact_conversation(history, lambda msgs: GOOD_SUMMARY)
        assert len(result) == 3

    def test_llm_receives_compact_prompt_as_last_message(self):
        """The prompt message injected to the LLM must ask for a summary."""
        history = _make_history(n_extra=4)
        captured = []

        def capturing_fn(msgs):
            captured.extend(msgs)
            return GOOD_SUMMARY

        compact_conversation(history, capturing_fn)
        last_msg = captured[-1]
        assert last_msg["role"] == "user"
        assert "summary" in last_msg["content"].lower()

    def test_compacted_history_smaller_than_original(self):
        history = _make_history(n_extra=10)
        result = compact_conversation(history, lambda msgs: GOOD_SUMMARY)
        assert len(result) < len(history)
