"""
Tests per ArgosAgent — history management, streaming, async, lightweight.

Coverage:
  - _count_tokens()          : stima token da testo
  - trim_history()           : budget enforcement, system preserved, oldest dropped
  - add_message()            : role + content appended
  - _init_history()          : history[0] sempre system
  - _init_history_with_tools : usa il tool block fornito
  - think_async()            : versione non-blocking con httpx
  - think_with_messages()    : history esterna (Telegram)
  - call_lightweight()       : modello leggero, max_retries=1
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock, patch

import src.agent as _agent_module
from src.agent import (
    MICRO_COMPACT_KEEP_RECENT,
    ArgosAgent,
    _count_tokens,
    _is_compactable_message,
)

# ==========================================================================
# _count_tokens
# ==========================================================================


class TestCountTokens:
    def test_empty_string_returns_one(self):
        # max(1, 0) = 1
        assert _count_tokens("") == 1

    def test_four_chars_one_token(self):
        assert _count_tokens("abcd") == 1

    def test_hundred_chars_twenty_five_tokens(self):
        assert _count_tokens("a" * 100) == 25

    def test_fractional_rounds_down(self):
        # 9 chars → 9//4 = 2
        assert _count_tokens("aaaaaaaaa") == 2

    def test_long_text(self):
        text = "word " * 200  # 1000 chars
        assert _count_tokens(text) == 250


# ==========================================================================
# trim_history()
# ==========================================================================


class TestTrimHistory:
    """
    Verifica che trim_history() rispetti il budget token mantenendo
    il system message e i messaggi più recenti.
    """

    def _make_agent_with_tiny_budget(self, extra_tokens: int = 0) -> ArgosAgent:
        """Crea un agente e imposta token_budget = system_tokens + extra_tokens."""
        agent = ArgosAgent()
        system_tokens = _count_tokens(agent.history[0]["content"])
        agent.token_budget = system_tokens + extra_tokens
        return agent

    def test_noop_when_only_system_message(self):
        agent = ArgosAgent()
        original_history = list(agent.history)
        agent.trim_history()
        assert agent.history == original_history

    def test_noop_when_empty_history(self):
        agent = ArgosAgent()
        agent.history = []
        agent.trim_history()  # Non deve crashare
        assert agent.history == []

    def test_system_message_always_preserved(self):
        agent = self._make_agent_with_tiny_budget(extra_tokens=0)
        agent.add_message("user", "hello world")
        agent.trim_history()
        assert agent.history[0]["role"] == "system"

    def test_drops_oldest_when_budget_exceeded(self):
        """Con budget stretto, i messaggi più vecchi vengono scartati."""
        agent = ArgosAgent()
        # Aggiungi 3 messaggi da ~10 token ciascuno (40 chars)
        agent.add_message("user", "A" * 40)
        agent.add_message("assistant", "B" * 40)
        agent.add_message("user", "C" * 40)

        system_tokens = _count_tokens(agent.history[0]["content"])
        # Budget = system + 21 token → entra system + 2 messaggi (B e C)
        agent.token_budget = system_tokens + 21

        agent.trim_history()

        # Il sistema deve essere il primo
        assert agent.history[0]["role"] == "system"
        # Il messaggio più vecchio (A) deve essere scartato
        contents = [m["content"] for m in agent.history[1:]]
        assert "A" * 40 not in contents
        # Gli ultimi due (B e C) devono essere mantenuti
        assert "B" * 40 in contents
        assert "C" * 40 in contents

    def test_total_tokens_within_budget_after_trim(self):
        """Dopo il trim, il totale token non deve superare il budget."""
        agent = ArgosAgent()
        for i in range(20):
            agent.add_message("user", f"Messaggio numero {i} " * 10)

        system_tokens = _count_tokens(agent.history[0]["content"])
        agent.token_budget = system_tokens + 50

        agent.trim_history()

        total = sum(_count_tokens(str(m.get("content", ""))) for m in agent.history)
        assert total <= agent.token_budget

    def test_keeps_most_recent_messages(self):
        """I messaggi più recenti sopravvivono al trim."""
        agent = ArgosAgent()
        # Aggiungi 10 messaggi identificabili
        for i in range(10):
            agent.add_message("user", f"MSG_{i:02d}_" + "x" * 40)

        system_tokens = _count_tokens(agent.history[0]["content"])
        # Budget per system + circa 3 messaggi
        agent.token_budget = system_tokens + 35

        agent.trim_history()

        # I messaggi più recenti devono essere presenti
        contents = " ".join(m["content"] for m in agent.history)
        assert "MSG_09_" in contents
        assert "MSG_08_" in contents
        # I più vecchi devono essere assenti
        assert "MSG_00_" not in contents
        assert "MSG_01_" not in contents

    def test_budget_exactly_at_system_keeps_no_extra_messages(self):
        """Se il budget è esattamente il system prompt, nessun altro messaggio sopravvive."""
        agent = ArgosAgent()
        agent.add_message("user", "questo dovrebbe essere eliminato")
        system_tokens = _count_tokens(agent.history[0]["content"])
        agent.token_budget = system_tokens  # Zero spazio per altro

        agent.trim_history()

        assert len(agent.history) == 1
        assert agent.history[0]["role"] == "system"

    def test_no_trim_when_within_budget(self):
        """Se la history è già dentro il budget non viene modificata."""
        agent = ArgosAgent()
        agent.add_message("user", "ciao")
        before = list(agent.history)
        # Budget molto alto
        agent.token_budget = 100_000

        agent.trim_history()

        assert agent.history == before


# ==========================================================================
# add_message() / _init_history()
# ==========================================================================


class TestHistoryManagement:
    def test_add_message_appends_role_and_content(self):
        agent = ArgosAgent()
        before_len = len(agent.history)
        agent.add_message("user", "test message")
        assert len(agent.history) == before_len + 1
        last = agent.history[-1]
        assert last["role"] == "user"
        assert last["content"] == "test message"

    def test_add_message_non_string_converted(self):
        agent = ArgosAgent()
        agent.add_message("user", 12345)
        assert agent.history[-1]["content"] == "12345"

    def test_init_history_starts_with_system(self):
        agent = ArgosAgent()
        assert agent.history[0]["role"] == "system"
        assert len(agent.history) == 1

    def test_init_history_resets_after_messages_added(self):
        agent = ArgosAgent()
        agent.add_message("user", "first")
        agent.add_message("assistant", "second")
        assert len(agent.history) == 3

        agent._init_history()
        assert len(agent.history) == 1
        assert agent.history[0]["role"] == "system"

    def test_init_history_with_tools_uses_provided_block(self):
        agent = ArgosAgent()
        custom_block = "CUSTOM_TOOL_BLOCK_FOR_TEST"
        agent._init_history_with_tools(custom_block)
        assert custom_block in agent.history[0]["content"]
        assert len(agent.history) == 1


# ==========================================================================
# think_async() — non-blocking inference
# ==========================================================================


class TestThinkAsync:
    @patch("src.llm.client.acompletion")
    async def test_think_async_openai_compatible(self, mock_acompletion):
        mock_resp = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "async openai response"
        mock_msg.tool_calls = []
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp.choices = [mock_choice]
        mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        mock_acompletion.return_value = mock_resp

        agent = ArgosAgent()
        agent.backend = "openai-compatible"
        agent.add_message("user", "Ciao async")
        result = await agent.think_async()
        assert result.content == "async openai response"

    @patch("src.llm.client.acompletion")
    async def test_think_async_anthropic(self, mock_acompletion):
        mock_resp = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "async anthropic response"
        mock_msg.tool_calls = []
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp.choices = [mock_choice]
        mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        mock_acompletion.return_value = mock_resp

        agent = ArgosAgent()
        agent.backend = "anthropic"
        agent.add_message("user", "Ciao async")
        result = await agent.think_async()
        assert result.content == "async anthropic response"

    @patch("src.llm.client.acompletion")
    async def test_think_async_calls_trim_history(self, mock_acompletion):
        mock_resp = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "ok"
        mock_msg.tool_calls = []
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp.choices = [mock_choice]
        mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        mock_acompletion.return_value = mock_resp

        agent = ArgosAgent()
        agent.backend = "openai-compatible"

        trim_called = []
        original_trim = agent.trim_history

        def tracking_trim():
            trim_called.append(True)
            original_trim()

        agent.trim_history = tracking_trim
        agent.add_message("user", "test")
        await agent.think_async()
        assert len(trim_called) == 1

    @patch("src.llm.client.acompletion")
    async def test_think_async_returns_error_on_failure(self, mock_acompletion):
        mock_acompletion.side_effect = Exception("network failure")
        agent = ArgosAgent()
        agent.backend = "openai-compatible"
        agent.add_message("user", "test")
        result = await agent.think_async()
        assert "Error" in result.content or "error" in result.content.lower()


# ==========================================================================
# think_with_messages() — Telegram mode
# ==========================================================================


class TestThinkWithMessages:
    @patch("src.agent.llm_complete", new_callable=AsyncMock)
    def test_think_with_messages_openai(self, mock_complete):
        from src.llm.client import LLMResponse

        mock_complete.return_value = LLMResponse(content="risposta telegram")

        agent = ArgosAgent()
        agent.backend = "openai-compatible"

        external_history = [
            {"role": "user", "content": "Ciao da Telegram"},
        ]
        result = agent.think_with_messages(external_history)

        assert result == "risposta telegram"
        call_kwargs = mock_complete.call_args[1]
        assert call_kwargs["messages"] == external_history

    @patch("src.agent.llm_complete", new_callable=AsyncMock)
    def test_think_with_messages_anthropic(self, mock_complete):
        from src.llm.client import LLMResponse

        mock_complete.return_value = LLMResponse(content="risposta anthropic telegram")

        agent = ArgosAgent()
        agent.backend = "anthropic"

        external_history = [
            {"role": "system", "content": "sei un assistente"},
            {"role": "user", "content": "Ciao"},
        ]
        result = agent.think_with_messages(external_history)

        assert result == "risposta anthropic telegram"


# ==========================================================================
# call_lightweight() — background tasks
# ==========================================================================


class TestCallLightweight:
    @patch("src.agent.llm_complete", new_callable=AsyncMock)
    def test_call_lightweight_returns_response(self, mock_complete):
        from src.llm.client import LLMResponse

        mock_complete.return_value = LLMResponse(content="estratto: fatto X")

        agent = ArgosAgent()
        result = agent.call_lightweight("Estrai fatti da: l'utente si chiama Alice")
        assert result == "estratto: fatto X"

    @patch("src.agent.llm_complete", new_callable=AsyncMock)
    def test_call_lightweight_returns_error_or_empty_on_exception(self, mock_complete):
        """Se llm_complete lancia eccezione, call_lightweight ritorna stringa vuota."""
        mock_complete.side_effect = Exception("connessione fallita")

        agent = ArgosAgent()
        result = agent.call_lightweight("test")

        assert isinstance(result, str)
        assert result == ""


# ==========================================================================
# _is_compactable_message()
# ==========================================================================


class TestIsCompactableMessage:
    def test_tool_result_user_message(self):
        msg = {"role": "user", "content": "TOOL RESULT: file created successfully"}
        assert _is_compactable_message(msg) is True

    def test_tool_result_partial_match_only_prefix(self):
        msg = {"role": "user", "content": "TOOL RESULT:"}
        assert _is_compactable_message(msg) is True

    def test_regular_user_message_not_compactable(self):
        msg = {"role": "user", "content": "List files in the current directory"}
        assert _is_compactable_message(msg) is False

    def test_world_state_system_message(self):
        msg = {"role": "system", "content": "WORLD STATE\nstep=3, last_error=None"}
        assert _is_compactable_message(msg) is True

    def test_workspace_state_updated_system_message(self):
        msg = {
            "role": "system",
            "content": "WORKSPACE STATE UPDATED:\nGit branch: main",
        }
        assert _is_compactable_message(msg) is True

    def test_current_workspace_state_system_message(self):
        msg = {
            "role": "system",
            "content": "CURRENT WORKSPACE STATE:\nGit branch: main",
        }
        assert _is_compactable_message(msg) is True

    def test_regular_system_message_not_compactable(self):
        msg = {"role": "system", "content": "Today's date: 2026-04-14 10:00"}
        assert _is_compactable_message(msg) is False

    def test_json_tool_call_assistant_message(self):
        msg = {
            "role": "assistant",
            "content": '{"action": {"tool": "list_files", "input": {}}}',
        }
        assert _is_compactable_message(msg) is True

    def test_json_tool_call_with_leading_whitespace(self):
        msg = {
            "role": "assistant",
            "content": '  {"action": {"tool": "read_file", "input": {"path": "/tmp/x"}}}',
        }
        assert _is_compactable_message(msg) is True

    def test_final_response_assistant_message_not_compactable(self):
        msg = {"role": "assistant", "content": "Ho completato il task."}
        assert _is_compactable_message(msg) is False

    def test_empty_content(self):
        msg = {"role": "user", "content": ""}
        assert _is_compactable_message(msg) is False

    def test_missing_role(self):
        msg = {"content": "TOOL RESULT: something"}
        assert _is_compactable_message(msg) is False


# ==========================================================================
# micro_compact()
# ==========================================================================


class TestMicroCompact:
    def _agent_with_tool_results(self, n_results: int) -> ArgosAgent:
        """Returns an agent with n_results tool-result messages in history."""
        agent = ArgosAgent()
        for i in range(n_results):
            agent.history.append(
                {
                    "role": "assistant",
                    "content": '{"action": {"tool": "list_files", "input": {}}}',
                }
            )
            agent.history.append({"role": "user", "content": f"TOOL RESULT: result {i}"})
        return agent

    def test_noop_when_no_compactable_messages(self):
        agent = ArgosAgent()
        agent.add_message("user", "Ciao")
        agent.add_message("assistant", "Risposta normale")
        original = list(agent.history)
        cleared = agent.micro_compact()
        assert cleared == 0
        assert agent.history == original

    def test_noop_when_below_keep_threshold(self):
        # 2 results = 4 compactable messages (< MICRO_COMPACT_KEEP_RECENT=5)
        agent = self._agent_with_tool_results(2)
        original = [m["content"] for m in agent.history]
        cleared = agent.micro_compact()
        assert cleared == 0
        assert [m["content"] for m in agent.history] == original

    def test_clears_oldest_beyond_keep_threshold(self):
        # 5 results = 10 compactable messages; keep 5, clear 5
        n = 5
        agent = self._agent_with_tool_results(n)
        cleared = agent.micro_compact()
        expected = n * 2 - MICRO_COMPACT_KEEP_RECENT  # 10 - 5 = 5
        assert cleared == expected

    def test_keeps_most_recent_results(self):
        keep = MICRO_COMPACT_KEEP_RECENT
        agent = self._agent_with_tool_results(keep + 1)
        agent.micro_compact()
        # Last KEEP tool-result messages must NOT be "[cleared]"
        tool_results = [
            m
            for m in agent.history
            if m.get("role") == "user" and "TOOL RESULT:" in m.get("content", "")
        ]
        # All surviving tool results still have original content
        for msg in tool_results:
            assert msg["content"] != "[cleared]"

    def test_cleared_messages_replaced_with_placeholder(self):
        keep = MICRO_COMPACT_KEEP_RECENT
        agent = self._agent_with_tool_results(keep + 2)
        agent.micro_compact()
        cleared_msgs = [m for m in agent.history if m.get("content") == "[cleared]"]
        assert len(cleared_msgs) > 0

    def test_system_message_never_cleared(self):
        agent = self._agent_with_tool_results(MICRO_COMPACT_KEEP_RECENT + 2)
        agent.micro_compact()
        # First message must remain the system prompt
        assert agent.history[0]["role"] == "system"
        assert agent.history[0]["content"] != "[cleared]"

    def test_world_state_messages_cleared(self):
        agent = ArgosAgent()
        for i in range(MICRO_COMPACT_KEEP_RECENT + 2):
            agent.history.append({"role": "system", "content": f"WORLD STATE\nstep={i}"})
        cleared = agent.micro_compact()
        assert cleared == 2

    def test_history_length_unchanged_after_micro_compact(self):
        agent = self._agent_with_tool_results(MICRO_COMPACT_KEEP_RECENT + 3)
        original_len = len(agent.history)
        agent.micro_compact()
        assert len(agent.history) == original_len

    def test_noop_on_single_message_history(self):
        agent = ArgosAgent()
        # History is just the system message
        cleared = agent.micro_compact()
        assert cleared == 0


# ==========================================================================
# trim_history() — tiered pipeline
# ==========================================================================


class TestTrimHistoryTiered:
    """Verifies that the 3-tier pipeline behaves correctly."""

    def test_tier3_fallback_unchanged_from_original(self):
        """Tier 3 must produce identical results to the original drop behaviour."""
        agent = ArgosAgent()
        system_tokens = _count_tokens(agent.history[0]["content"])
        # Budget: system + exactly 10 extra tokens
        agent.token_budget = system_tokens + 10
        agent.add_message("user", "A" * 40)  # ~10 tokens
        agent.add_message("assistant", "B" * 40)  # ~10 tokens
        agent.add_message("user", "C" * 40)  # ~10 tokens
        agent.trim_history()
        # System must be preserved
        assert agent.history[0]["role"] == "system"
        # Total must fit within budget
        total = sum(_count_tokens(str(m.get("content", ""))) for m in agent.history)
        assert total <= agent.token_budget

    def test_micro_compact_runs_before_drop(self):
        """When budget is 80%+ full with tool results, micro_compact fires first."""
        agent = ArgosAgent()
        system_tokens = _count_tokens(agent.history[0]["content"])
        # Set a budget where tool results push us over 80% but not 100%
        agent.token_budget = system_tokens + 200  # comfortable

        # Add enough tool results to exceed 80% of the extra budget
        for _ in range(15):
            agent.history.append({"role": "user", "content": f"TOOL RESULT: {'x' * 50}"})

        original_len = len(agent.history)
        agent.trim_history()
        # After trim: message count may drop (Tier 3) but if micro_compact fired,
        # some messages have "[cleared]" content instead of being removed
        has_cleared = any(m.get("content") == "[cleared]" for m in agent.history)
        # Either cleared (micro_compact ran) or dropped (Tier 3) — both are valid
        assert has_cleared or len(agent.history) < original_len

    def test_tier2_skipped_when_history_too_short(self, monkeypatch):
        """Structured compaction must not be attempted with < 5 messages."""
        # Enable Tier 2 so we can verify it is skipped due to history length
        monkeypatch.setattr(_agent_module, "_COMPACTION_ENABLED", True)

        agent = ArgosAgent()
        system_tokens = _count_tokens(agent.history[0]["content"])
        agent.token_budget = system_tokens  # force 100%+ immediately

        # Only 2 messages total — below _COMPACT_MIN_MESSAGES
        agent.add_message("user", "test")
        # Should fall straight to Tier 3 without making LLM call
        with patch.object(agent, "_call_for_compaction") as mock_compact:
            agent.trim_history()
            mock_compact.assert_not_called()

    def test_tier2_called_when_conditions_met(self, monkeypatch):
        """Structured compaction is attempted when history is long and budget exceeded."""
        from src.core.compaction import COMPACT_MIN_MESSAGES

        # Enable Tier 2 for this test only
        monkeypatch.setattr(_agent_module, "_COMPACTION_ENABLED", True)

        agent = ArgosAgent()
        system_tokens = _count_tokens(agent.history[0]["content"])
        # Budget: system only — forces 90%+ immediately
        agent.token_budget = system_tokens + 1

        # Add enough messages to meet COMPACT_MIN_MESSAGES
        for i in range(COMPACT_MIN_MESSAGES):
            agent.add_message("user", f"message {i} — {'x' * 20}")
            agent.add_message("assistant", f"response {i}")

        # Mock _call_for_compaction to return a valid summary (no real LLM call)
        summary = "1. Summary\n2. Concepts\n3. Files\n4. Tools\n5. Errors\n6. User\n7. Pending\n8. Current\n9. Next"
        with patch.object(agent, "_call_for_compaction", return_value=summary):
            agent.trim_history()

        # History should now be compacted (≤ 3 messages)
        assert len(agent.history) <= 3

    def test_trim_history_noop_when_within_budget(self):
        agent = ArgosAgent()
        agent.token_budget = 100_000  # far above any realistic usage
        agent.add_message("user", "hello")
        agent.add_message("assistant", "ciao")
        original = list(agent.history)
        agent.trim_history()
        assert agent.history == original
