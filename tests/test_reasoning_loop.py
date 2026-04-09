"""
Tests per il CoreAgent reasoning loop e pipeline.

Coverage:
  - _reasoning_loop()        : done immediato, tool step, tool sconosciuto,
                               max steps, diminishing returns, pre-hook blocked,
                               tool failure
  - run_task_async()         : pipeline completa, TaskResult, SESSION hooks
  - _build_llm_context()     : data iniettata, memories, task come ultimo user msg,
                               history iniettata, git context
  - _authorize_tool()        : flusso end-to-end nel loop (denied → feedback LLM)
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.actions.base import ActionResult, ActionStatus
from src.core.engine import (
    DIMINISHING_STEPS,
    DIMINISHING_THRESHOLD,
    CoreAgent,
    TaskResult,
)
from src.hooks.registry import HOOK_REGISTRY, HookEvent
from src.tools.spec import ToolInput, ToolSpec
from src.world_model.state import WorldState


# ==========================================================================
# Helper — ToolSpec minimale sicuro (risk=none)
# ==========================================================================


class _EchoInput(ToolInput):
    pass


_SAFE_ECHO_SPEC = ToolSpec(
    name="test_echo",
    description="Echo tool for testing",
    input_schema=_EchoInput,
    executor=lambda inp: "echo ok",
    risk="none",
    category="system",
    icon="✅",
    label="Test Echo",
)

_RISKY_ECHO_SPEC = ToolSpec(
    name="test_risky",
    description="Risky tool for testing",
    input_schema=_EchoInput,
    executor=lambda inp: "risky ok",
    risk="high",
    category="system",
    icon="⚠️",
    label="Test Risky",
)


def _make_agent(**kwargs) -> CoreAgent:
    """Crea un CoreAgent minimal per i test del loop (no git, no memory)."""
    defaults = dict(memory_mode="off", inject_git_context=False)
    defaults.update(kwargs)
    agent = CoreAgent(**defaults)
    # Inietta i tool di test nel registry locale dell'agente
    agent._available_tools["test_echo"] = _SAFE_ECHO_SPEC
    agent._available_tools["test_risky"] = _RISKY_ECHO_SPEC
    return agent


def _done_response(text: str = "Fatto!") -> str:
    return json.dumps({"thought": "task complete", "response": text, "done": True})


def _tool_response(tool: str, inp: dict | None = None) -> str:
    return json.dumps(
        {
            "thought": f"uso {tool}",
            "action": {"tool": tool, "input": inp or {}},
            "confidence": 0.9,
            "done": False,
        }
    )


# ==========================================================================
# _reasoning_loop() — test unitari con think_async mockato
# ==========================================================================


def _make_tracer():
    """Crea un tracer mock che supporta il context manager."""
    tracer = MagicMock()
    span = MagicMock()
    span.__enter__ = MagicMock(return_value=span)
    span.__exit__ = MagicMock(return_value=False)
    tracer.start_as_current_span.return_value = span
    return tracer


def _run_loop(agent, task="test") -> tuple:
    """Esegue _reasoning_loop in modo sincrono e ritorna (response, records, success)."""

    async def _inner():
        state = WorldState()
        state.current_task = task
        tracer = _make_tracer()
        return await agent._reasoning_loop(task, state, tracer, MagicMock())

    return asyncio.run(_inner())


class TestReasoningLoop:
    def test_loop_done_immediately(self):
        """LLM restituisce done=true al primo step: nessun tool eseguito."""
        agent = _make_agent()
        with patch.object(
            agent._llm, "think_async", new_callable=AsyncMock
        ) as mock_think:
            mock_think.return_value = _done_response("Completato al volo.")
            response, records, success = _run_loop(agent)

        assert response == "Completato al volo."
        assert records == []
        assert success is True
        assert mock_think.call_count == 1

    def test_loop_single_tool_then_done(self):
        """Un tool step seguito da done=true → 1 step_record, success=True."""
        agent = _make_agent()
        success_result = ActionResult(status=ActionStatus.SUCCESS, message="echo ok")

        with (
            patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think,
            patch("src.core.engine.execute_with_retry", return_value=success_result),
        ):
            mock_think.side_effect = [
                _tool_response("test_echo"),
                _done_response("Tutto fatto."),
            ]
            response, records, success = _run_loop(agent)

        assert success is True
        assert response == "Tutto fatto."
        assert len(records) == 1
        assert records[0].tool == "test_echo"
        assert records[0].success is True

    def test_loop_unknown_tool_fails(self):
        """Tool non presente in _available_tools → loop_success=False."""
        agent = _make_agent()

        with patch.object(
            agent._llm, "think_async", new_callable=AsyncMock
        ) as mock_think:
            mock_think.return_value = _tool_response("strumento_inesistente")
            response, records, success = _run_loop(agent)

        assert success is False
        assert (
            "strumento_inesistente" in response
            or "Unknown" in response
            or "restricted" in response
        )

    def test_loop_max_steps_without_done(self):
        """Se l'LLM non dice mai done, il loop si ferma al max_steps."""
        agent = _make_agent(max_steps=3)
        success_result = ActionResult(status=ActionStatus.SUCCESS, message="ok")

        # La risposta deve essere >= DIMINISHING_THRESHOLD (120 chars) per evitare
        # che il check "diminishing returns" si attivi prima del max_steps.
        long_tool_json = json.dumps(
            {
                "thought": "Sto eseguendo il tool di test in modo continuativo come richiesto dall'utente, pensiero lungo per superare la soglia",
                "action": {"tool": "test_echo", "input": {}},
                "confidence": 0.9,
                "done": False,
            }
        )
        assert len(long_tool_json) >= DIMINISHING_THRESHOLD

        with (
            patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think,
            patch("src.core.engine.execute_with_retry", return_value=success_result),
        ):
            mock_think.return_value = long_tool_json
            response, records, success = _run_loop(agent)

        assert mock_think.call_count == 3
        assert len(records) == 3

    def test_loop_diminishing_returns_stops_early(self):
        """
        Se per DIMINISHING_STEPS step consecutivi la risposta è < DIMINISHING_THRESHOLD
        caratteri e done=False, il loop si interrompe.
        """
        agent = _make_agent(max_steps=10)
        success_result = ActionResult(status=ActionStatus.SUCCESS, message="ok")

        short_tool_json = json.dumps(
            {
                "thought": "x",
                "action": {"tool": "test_echo", "input": {}},
                "done": False,
            }
        )
        assert len(short_tool_json) < DIMINISHING_THRESHOLD

        with (
            patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think,
            patch("src.core.engine.execute_with_retry", return_value=success_result),
        ):
            mock_think.return_value = short_tool_json
            _run_loop(agent)

        assert mock_think.call_count <= DIMINISHING_STEPS + 1

    def test_loop_pre_hook_blocks_tool(self):
        """Un hook PRE_TOOL_USE che blocca deve interrompere il loop."""
        HOOK_REGISTRY.clear()
        HOOK_REGISTRY.register(
            HookEvent.PRE_TOOL_USE,
            lambda tool_name, tool_input: False,
            name="test_blocker",
        )
        agent = _make_agent()

        with patch.object(
            agent._llm, "think_async", new_callable=AsyncMock
        ) as mock_think:
            mock_think.return_value = _tool_response("test_echo")
            response, records, success = _run_loop(agent)

        HOOK_REGISTRY.clear()

        assert success is False
        assert "blocked" in response.lower() or "BLOCKED" in response

    def test_loop_auth_denied_require_confirmation(self):
        """In API mode (require_confirmation=True) i tool rischiosi sono bloccati."""
        agent = _make_agent(require_confirmation=True)

        with patch.object(
            agent._llm, "think_async", new_callable=AsyncMock
        ) as mock_think:
            mock_think.return_value = _tool_response("test_risky")
            response, records, success = _run_loop(agent)

        assert success is False
        assert "denied" in response.lower() or "Denied" in response

    def test_loop_auth_denied_injects_feedback_to_llm(self):
        """Quando un tool viene negato, 'ACTION DENIED BY USER' viene iniettato in history."""
        agent = _make_agent(require_confirmation=True)

        with patch.object(
            agent._llm, "think_async", new_callable=AsyncMock
        ) as mock_think:
            mock_think.return_value = _tool_response("test_risky")
            _run_loop(agent)

        history_contents = " ".join(m["content"] for m in agent._llm.history)
        assert "DENIED" in history_contents

    def test_loop_auth_callback_denied_injects_feedback(self):
        """Quando il callback nega, il feedback viene comunque iniettato."""
        callback = MagicMock(return_value=False)
        agent = _make_agent(confirmation_callback=callback)

        with patch.object(
            agent._llm, "think_async", new_callable=AsyncMock
        ) as mock_think:
            mock_think.return_value = _tool_response("test_risky")
            _, _, success = _run_loop(agent)

        assert success is False
        history_contents = " ".join(m["content"] for m in agent._llm.history)
        assert "DENIED" in history_contents

    def test_loop_tool_failure_sets_loop_success_false(self):
        """Se execute_with_retry ritorna FAILED, loop_success diventa False."""
        agent = _make_agent()
        fail_result = ActionResult(
            status=ActionStatus.FAILED, message="Error: file not found"
        )

        with (
            patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think,
            patch("src.core.engine.execute_with_retry", return_value=fail_result),
        ):
            mock_think.side_effect = [
                _tool_response("test_echo"),
                _done_response("Fallito."),
            ]
            response, records, success = _run_loop(agent)

        assert success is False
        assert records[0].success is False

    def test_loop_tool_result_injected_in_history(self):
        """Il risultato del tool deve essere aggiunto alla history come TOOL RESULT."""
        agent = _make_agent()
        success_result = ActionResult(
            status=ActionStatus.SUCCESS, message="risultato tool specifico"
        )

        with (
            patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think,
            patch("src.core.engine.execute_with_retry", return_value=success_result),
        ):
            mock_think.side_effect = [
                _tool_response("test_echo"),
                _done_response("Ok."),
            ]
            _run_loop(agent)

        history_contents = " ".join(m["content"] for m in agent._llm.history)
        assert "TOOL RESULT" in history_contents
        assert "risultato tool specifico" in history_contents


# ==========================================================================
# run_task_async() — pipeline completa
# ==========================================================================


class TestRunTaskAsync:
    def test_returns_task_result_on_success(self):
        async def run():
            agent = _make_agent()
            with patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think:
                mock_think.return_value = _done_response("Completato!")
                return await agent.run_task_async("fai qualcosa")

        result = asyncio.run(run())
        assert isinstance(result, TaskResult)
        assert result.success is True
        assert result.task == "fai qualcosa"
        assert result.response == "Completato!"

    def test_task_result_has_steps_executed(self):
        async def run():
            agent = _make_agent()
            success_result = ActionResult(status=ActionStatus.SUCCESS, message="ok")
            with (
                patch.object(
                    agent._llm, "think_async", new_callable=AsyncMock
                ) as mock_think,
                patch(
                    "src.core.engine.execute_with_retry", return_value=success_result
                ),
            ):
                mock_think.side_effect = [
                    _tool_response("test_echo"),
                    _done_response("Fatto."),
                ]
                return await agent.run_task_async("task con un tool")

        result = asyncio.run(run())
        assert result.steps_executed == 1
        assert len(result.history) == 1

    def test_task_result_memories_used_zero_when_off(self):
        async def run():
            agent = _make_agent(memory_mode="off")
            with patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think:
                mock_think.return_value = _done_response("ok")
                return await agent.run_task_async("test")

        result = asyncio.run(run())
        assert result.memories_used == 0

    def test_session_hooks_fire(self):
        """SESSION_START e SESSION_END devono essere chiamati."""
        HOOK_REGISTRY.clear()
        session_events = []
        HOOK_REGISTRY.register(
            HookEvent.SESSION_START,
            lambda **kw: session_events.append("start"),
            name="test_start",
        )
        HOOK_REGISTRY.register(
            HookEvent.SESSION_END,
            lambda **kw: session_events.append("end"),
            name="test_end",
        )

        async def run():
            agent = _make_agent()
            with patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think:
                mock_think.return_value = _done_response("ok")
                await agent.run_task_async("test hook")

        asyncio.run(run())
        HOOK_REGISTRY.clear()

        assert "start" in session_events
        assert "end" in session_events

    def test_git_context_cache_cleared_after_task(self):
        """_git_context_cache viene resettato a None dopo run_task_async."""

        async def run():
            agent = _make_agent()
            agent._git_context_cache = "branch: main"
            with patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think:
                mock_think.return_value = _done_response("ok")
                await agent.run_task_async("test")
            return agent._git_context_cache

        assert asyncio.run(run()) is None


# ==========================================================================
# _build_llm_context() — costruzione contesto LLM
# ==========================================================================


class TestBuildLlmContext:
    def _get_history_contents(self, agent: CoreAgent) -> str:
        return " ".join(m["content"] for m in agent._llm.history)

    def test_task_is_last_user_message(self):
        agent = _make_agent()
        agent._build_llm_context("task di test 123", relevant_memories=[])

        last_msg = agent._llm.history[-1]
        assert last_msg["role"] == "user"
        assert last_msg["content"] == "task di test 123"

    def test_date_is_injected(self):
        agent = _make_agent()
        agent._build_llm_context("fai qualcosa", relevant_memories=[])

        contents = self._get_history_contents(agent)
        # La data deve essere nel contesto
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        assert today in contents

    def test_memories_injected_when_present(self):
        agent = _make_agent()
        memories = [
            {"category": "fact", "content": "L'utente si chiama Alice"},
            {"category": "preference", "content": "Preferisce Python"},
        ]
        agent._build_llm_context("cosa sai di me?", relevant_memories=memories)

        contents = self._get_history_contents(agent)
        assert "Alice" in contents
        assert "Python" in contents

    def test_no_memory_block_when_memories_empty(self):
        agent = _make_agent()
        agent._build_llm_context("query", relevant_memories=[])

        contents = self._get_history_contents(agent)
        # Il blocco THINGS YOU KNOW non deve comparire senza memorie
        assert "THINGS YOU KNOW" not in contents

    def test_git_context_injected_when_present(self):
        agent = _make_agent()
        agent._git_context_cache = "Git branch: main\nChanged files:\nM src/foo.py"

        agent._build_llm_context("mostra stato", relevant_memories=[])

        contents = self._get_history_contents(agent)
        assert "main" in contents
        assert "src/foo.py" in contents

    def test_git_context_not_injected_when_none(self):
        agent = _make_agent()
        agent._git_context_cache = None

        agent._build_llm_context("task", relevant_memories=[])

        contents = self._get_history_contents(agent)
        assert "WORKSPACE STATE" not in contents

    def test_injected_history_prepended_before_task(self):
        agent = _make_agent()
        agent._injected_history = [
            {"role": "user", "content": "messaggio precedente"},
            {"role": "assistant", "content": "risposta precedente"},
        ]

        agent._build_llm_context("nuova task", relevant_memories=[])

        # L'history iniettata deve precedere il task
        user_msgs = [m for m in agent._llm.history if m["role"] == "user"]
        assert user_msgs[-2]["content"] == "messaggio precedente"
        assert user_msgs[-1]["content"] == "nuova task"

    def test_history_reinitialized_on_each_call(self):
        """_build_llm_context deve reinizializzare la history (non accumulate)."""
        agent = _make_agent()

        agent._build_llm_context("task 1", relevant_memories=[])
        len_after_first = len(agent._llm.history)

        agent._build_llm_context("task 2", relevant_memories=[])
        len_after_second = len(agent._llm.history)

        # La history deve avere circa la stessa lunghezza (non accumulare)
        assert abs(len_after_second - len_after_first) <= 1

    def test_memory_block_contains_category_labels(self):
        agent = _make_agent()
        memories = [
            {"category": "interest", "content": "Ama la musica jazz"},
        ]
        agent._build_llm_context("ciao", relevant_memories=memories)

        contents = self._get_history_contents(agent)
        assert "[interest]" in contents
        assert "jazz" in contents


# ==========================================================================
# _authorize_tool() — sicurezza nel loop (test end-to-end)
# ==========================================================================


class TestAuthorizationEndToEnd:
    def test_safe_tool_authorized_in_api_mode(self):
        agent = _make_agent(require_confirmation=True)
        assert agent._authorize_tool(_SAFE_ECHO_SPEC, {}) is True

    def test_risky_tool_blocked_in_api_mode(self):
        agent = _make_agent(require_confirmation=True)
        assert agent._authorize_tool(_RISKY_ECHO_SPEC, {}) is False

    def test_risky_tool_allowed_with_default_no_confirmation(self):
        agent = _make_agent()
        assert agent._authorize_tool(_RISKY_ECHO_SPEC, {}) is True

    def test_callback_yes_allows_risky_tool(self):
        agent = _make_agent(confirmation_callback=MagicMock(return_value=True))
        assert agent._authorize_tool(_RISKY_ECHO_SPEC, {}) is True

    def test_callback_no_blocks_risky_tool(self):
        agent = _make_agent(confirmation_callback=MagicMock(return_value=False))
        assert agent._authorize_tool(_RISKY_ECHO_SPEC, {}) is False

    def test_callback_called_with_tool_name_and_input(self):
        callback = MagicMock(return_value=True)
        agent = _make_agent(confirmation_callback=callback)
        agent._authorize_tool(_RISKY_ECHO_SPEC, {"key": "value"})
        callback.assert_called_once_with("test_risky", {"key": "value"})

    def test_unknown_tool_string_denied(self):
        agent = _make_agent()
        assert agent._authorize_tool("tool_che_non_esiste", {}) is False

    def test_tool_spec_by_name_string_resolves(self):
        """Passando il nome come stringa, deve trovare il tool nel registry."""
        agent = _make_agent()
        # web_search esiste nel REGISTRY globale ed è risk=none
        from src.tools.registry import REGISTRY

        web_search = REGISTRY.get("web_search")
        if web_search and not web_search.requires_confirmation():
            assert agent._authorize_tool("web_search", {}) is True
