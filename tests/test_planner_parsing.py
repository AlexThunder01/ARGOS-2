"""
Unit test per parse_planner_response() e extract_json().

Coverage:
  - Formato canonico azione (done=False, tool + input)
  - Formato canonico risposta finale (done=True, response)
  - JSON immerso in testo verbose (chain-of-thought + JSON + testo dopo)
  - Fallback plain-text → done=True senza crash
  - Risposta vuota / solo whitespace → done=True senza crash
  - JSON valido senza tool nell'action → degradato a done=True
  - JSON troncato (timeout LLM mid-token) → fallback senza crash
  - confidence fuori range [0,1] → clampato, no crash
  - confidence non numerica (stringa) → fallback a 1.0, no crash
  - Tool name con caratteri speciali → non crasha, tool sconosciuto
  - Formato legacy {"tool": ..., "input": ...} (senza "action") → compat
  - response presente insieme a done=false → trattato come done=True
  - JSON null, array, numero → fallback a plain-text
  - extract_json() isolata: testo normale, JSON immerso, troncato, nidificato
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src.planner.planner import PlannerDecision, parse_planner_response
from src.utils import extract_json


# ==========================================================================
# extract_json() — utility standalone
# ==========================================================================


class TestExtractJson:
    def test_clean_json_object(self):
        text = '{"key": "value", "num": 42}'
        result = extract_json(text)
        assert result == {"key": "value", "num": 42}

    def test_json_embedded_in_text(self):
        text = 'Prima del JSON {"found": true} e testo dopo'
        result = extract_json(text)
        assert result == {"found": True}

    def test_nested_json(self):
        text = '{"outer": {"inner": "val"}, "x": 1}'
        result = extract_json(text)
        assert result["outer"]["inner"] == "val"

    def test_no_json_returns_none(self):
        assert extract_json("testo senza parentesi") is None
        assert extract_json("") is None
        assert extract_json("   ") is None

    def test_truncated_json_returns_none(self):
        """JSON troncato: le parentesi non si chiudono → None (no crash)."""
        assert extract_json('{"key": "val') is None
        assert extract_json('{"a": {"b":') is None

    def test_array_not_matched(self):
        """extract_json cerca solo oggetti {}, non array []."""
        result = extract_json('["a", "b"]')
        assert result is None

    def test_invalid_json_syntax_returns_none(self):
        """Parentesi bilanciate ma JSON non valido → None."""
        result = extract_json("{chiave: valore}")
        assert result is None

    def test_first_object_returned_when_multiple(self):
        """Se ci sono più oggetti, viene estratto solo il primo."""
        text = '{"first": 1} {"second": 2}'
        result = extract_json(text)
        assert result == {"first": 1}

    def test_non_string_input_coerced(self):
        """Input non-stringa viene convertito via str()."""
        result = extract_json(42)
        assert result is None  # "42" non contiene "{"


# ==========================================================================
# parse_planner_response() — formato canonico
# ==========================================================================


class TestPlannerCanonicalFormats:
    def test_action_format(self):
        """Formato canonico azione: done=False con tool + input."""
        raw = json.dumps({
            "thought": "cerco informazioni",
            "action": {"tool": "web_search", "input": {"query": "meteo Roma"}},
            "confidence": 0.85,
            "done": False,
        })
        d = parse_planner_response(raw)

        assert d.done is False
        assert d.tool == "web_search"
        assert d.tool_input == {"query": "meteo Roma"}
        assert d.confidence == 0.85
        assert d.thought == "cerco informazioni"
        assert d.response is None

    def test_done_format(self):
        """Formato canonico risposta finale: done=True con response."""
        raw = json.dumps({
            "thought": "task completato",
            "response": "Ecco la risposta finale.",
            "done": True,
        })
        d = parse_planner_response(raw)

        assert d.done is True
        assert d.response == "Ecco la risposta finale."
        assert d.tool is None
        assert d.tool_input is None

    def test_raw_field_preserved(self):
        """Il campo raw deve contenere l'input originale inalterato."""
        raw = '{"thought":"x","response":"y","done":true}'
        d = parse_planner_response(raw)
        assert d.raw == raw


# ==========================================================================
# parse_planner_response() — JSON immerso in testo
# ==========================================================================


class TestPlannerEmbeddedJson:
    def test_json_after_preamble(self):
        """JSON preceduto da testo chain-of-thought."""
        raw = 'Analizzo la situazione...\n{"thought":"ok","response":"Fatto.","done":true}'
        d = parse_planner_response(raw)
        assert d.done is True
        assert d.response == "Fatto."

    def test_json_before_trailing_text(self):
        """JSON seguito da testo dopo la chiusura della parentesi."""
        raw = '{"thought":"ok","response":"Risposta.","done":true}\nTesto dopo ignorato.'
        d = parse_planner_response(raw)
        assert d.done is True
        assert d.response == "Risposta."

    def test_json_surrounded_by_text(self):
        """JSON in mezzo a testo prima e dopo."""
        raw = 'Ragionamento: devo farlo. {"thought":"ok","response":"OK","done":true} Fine.'
        d = parse_planner_response(raw)
        assert d.done is True
        assert d.response == "OK"


# ==========================================================================
# parse_planner_response() — fallback plain-text
# ==========================================================================


class TestPlannerPlainTextFallback:
    def test_plain_text_becomes_done_response(self):
        """Testo libero senza JSON → done=True, response=testo."""
        raw = "Non ho trovato strumenti adatti a questa richiesta."
        d = parse_planner_response(raw)
        assert d.done is True
        assert d.response == raw

    def test_empty_string_no_crash(self):
        """Risposta vuota → done=True senza eccezioni."""
        d = parse_planner_response("")
        assert d is not None
        assert d.done is True

    def test_whitespace_only_no_crash(self):
        """Solo whitespace → done=True senza eccezioni."""
        d = parse_planner_response("   \n\t  ")
        assert d is not None
        assert d.done is True

    def test_json_null_fallback(self):
        """'null' non è un oggetto JSON → fallback plain-text."""
        d = parse_planner_response("null")
        assert d.done is True

    def test_json_array_fallback(self):
        """Array JSON → extract_json ritorna None → fallback plain-text."""
        d = parse_planner_response('["a", "b"]')
        assert d.done is True

    def test_json_number_fallback(self):
        """Numero JSON → nessun '{' → fallback plain-text."""
        d = parse_planner_response("42")
        assert d.done is True


# ==========================================================================
# parse_planner_response() — casi limite strutturali
# ==========================================================================


class TestPlannerEdgeCases:
    def test_truncated_json_no_crash(self):
        """JSON troncato a metà (timeout LLM) → no crash, done=True."""
        truncated = '{"thought":"analizzo","action":{"tool":"web_search","in'
        d = parse_planner_response(truncated)
        assert d is not None
        assert d.done is True

    def test_action_without_tool_field(self):
        """action senza 'tool' → nessun tool name → degradato a done=True."""
        raw = json.dumps({
            "thought": "x",
            "action": {"input": {"query": "test"}},
            "confidence": 0.9,
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.done is True
        assert d.tool is None

    def test_empty_action_dict(self):
        """action={} (senza tool né input) → done=True."""
        raw = json.dumps({
            "thought": "y",
            "action": {},
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.done is True

    def test_done_false_with_response_field(self):
        """Se 'response' è presente, viene trattato come done=True indipendentemente da done."""
        raw = json.dumps({
            "thought": "z",
            "response": "Testo di risposta.",
            "done": False,  # contraddittorio ma deve essere gestito
        })
        d = parse_planner_response(raw)
        # La presenza di "response" prevale → done=True
        assert d.done is True
        assert d.response == "Testo di risposta."

    def test_missing_thought_field(self):
        """Manca 'thought' → usa stringa vuota, no crash."""
        raw = json.dumps({
            "action": {"tool": "web_search", "input": {"query": "test"}},
            "confidence": 0.7,
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d is not None
        assert d.thought == ""

    def test_tool_input_is_none(self):
        """input esplicitamente null → tool_input è None, no crash."""
        raw = json.dumps({
            "thought": "w",
            "action": {"tool": "list_files", "input": None},
            "confidence": 0.9,
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.tool == "list_files"
        assert d.tool_input is None

    def test_deeply_nested_action(self):
        """Input con dizionario annidato → no crash, preservato."""
        raw = json.dumps({
            "thought": "v",
            "action": {
                "tool": "create_file",
                "input": {"path": "/tmp/test.py", "content": "x = 1\n"},
            },
            "confidence": 0.95,
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.tool == "create_file"
        assert d.tool_input["path"] == "/tmp/test.py"


# ==========================================================================
# parse_planner_response() — confidence
# ==========================================================================


class TestPlannerConfidence:
    def test_confidence_within_range(self):
        raw = json.dumps({
            "thought": "x",
            "action": {"tool": "web_search", "input": {"query": "q"}},
            "confidence": 0.75,
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.confidence == 0.75

    def test_confidence_above_1_clamped(self):
        """confidence > 1.0 → clampato a 1.0."""
        raw = json.dumps({
            "thought": "x",
            "action": {"tool": "web_search", "input": {"query": "q"}},
            "confidence": 5.0,
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.confidence == 1.0

    def test_confidence_below_0_clamped(self):
        """confidence < 0.0 → clampato a 0.0."""
        raw = json.dumps({
            "thought": "x",
            "action": {"tool": "web_search", "input": {"query": "q"}},
            "confidence": -0.5,
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.confidence == 0.0

    def test_confidence_string_falls_back_to_1(self):
        """confidence come stringa non numerica → fallback a 1.0, no crash."""
        raw = json.dumps({
            "thought": "x",
            "action": {"tool": "web_search", "input": {"query": "q"}},
            "confidence": "high",
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.confidence == 1.0

    def test_confidence_missing_defaults_to_1(self):
        """confidence assente → 1.0 di default."""
        raw = json.dumps({
            "thought": "x",
            "action": {"tool": "web_search", "input": {"query": "q"}},
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.confidence == 1.0

    def test_confidence_zero_exact(self):
        """confidence esattamente 0.0 → preservato."""
        raw = json.dumps({
            "thought": "x",
            "action": {"tool": "web_search", "input": {"query": "q"}},
            "confidence": 0.0,
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.confidence == 0.0


# ==========================================================================
# parse_planner_response() — tool name con caratteri speciali
# ==========================================================================


class TestPlannerMaliciousToolNames:
    @pytest.mark.parametrize("malicious_name", [
        "../../../etc/passwd",
        "'; DROP TABLE tools; --",
        "web_search\x00hidden",
        "",
        "a" * 500,
    ])
    def test_malicious_tool_name_no_crash(self, malicious_name):
        """Tool name con caratteri speciali non deve causare crash nel parser."""
        raw = json.dumps({
            "thought": "x",
            "action": {"tool": malicious_name, "input": {}},
            "confidence": 0.9,
            "done": False,
        })
        d = parse_planner_response(raw)
        # Il parser non deve crashare. Il loop rejecting è responsabilità del CoreAgent.
        assert d is not None


# ==========================================================================
# parse_planner_response() — formato legacy (retrocompatibilità)
# ==========================================================================


class TestPlannerLegacyFormat:
    def test_legacy_top_level_tool_field(self):
        """Vecchio formato {"tool": ..., "input": ...} senza "action" wrapper."""
        raw = json.dumps({
            "thought": "uso il vecchio formato",
            "tool": "web_search",
            "input": {"query": "legacy test"},
            "confidence": 0.8,
            "done": False,
        })
        d = parse_planner_response(raw)
        assert d.tool == "web_search"
        assert d.tool_input == {"query": "legacy test"}
        assert d.done is False

    def test_legacy_format_with_done_true(self):
        """Vecchio formato con done=true → risposta finale."""
        raw = json.dumps({
            "thought": "finito",
            "response": "Completato!",
            "done": True,
        })
        d = parse_planner_response(raw)
        assert d.done is True
        assert d.response == "Completato!"


# ==========================================================================
# Regressione: TOOL RESULT deve essere iniettato come ruolo "user"
# ==========================================================================


class TestToolResultRoleRegression:
    """
    Verifica che il CoreAgent inietti il risultato del tool come messaggio
    con ruolo "user" (non "assistant"). Un'inversione di ruolo rompe il loop
    perché l'LLM si "vede" rispondere a se stesso.
    """

    def test_tool_result_injected_as_user_role(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from src.actions.base import ActionResult, ActionStatus
        from src.core.engine import CoreAgent
        from src.tools.spec import ToolInput, ToolSpec
        from src.world_model.state import WorldState

        class _EchoInput(ToolInput):
            pass

        echo_spec = ToolSpec(
            name="test_echo_reg",
            description="Echo",
            input_schema=_EchoInput,
            executor=lambda inp: "echo ok",
            risk="none",
            category="system",
            icon="✅",
            label="Echo",
        )

        agent = CoreAgent(memory_mode="off", inject_git_context=False)
        agent._available_tools["test_echo_reg"] = echo_spec

        tool_response = json.dumps({
            "thought": "uso echo",
            "action": {"tool": "test_echo_reg", "input": {}},
            "confidence": 0.9,
            "done": False,
        })
        done_response = json.dumps({
            "thought": "fatto",
            "response": "OK",
            "done": True,
        })

        success_result = ActionResult(status=ActionStatus.SUCCESS, message="risultato_echo")

        async def run():
            from src.world_model.state import WorldState
            from unittest.mock import MagicMock
            tracer = MagicMock()
            span = MagicMock()
            span.__enter__ = MagicMock(return_value=span)
            span.__exit__ = MagicMock(return_value=False)
            tracer.start_as_current_span.return_value = span

            state = WorldState()
            state.current_task = "test"

            with (
                patch.object(agent._llm, "think_async", new_callable=AsyncMock) as mock_think,
                patch("src.core.engine.execute_with_retry", return_value=success_result),
            ):
                mock_think.side_effect = [tool_response, done_response]
                await agent._reasoning_loop("test", state, tracer, MagicMock())

        asyncio.run(run())

        tool_result_msgs = [
            m for m in agent._llm.history
            if "TOOL RESULT" in m.get("content", "")
        ]
        assert len(tool_result_msgs) >= 1, "Nessun TOOL RESULT iniettato in history"
        for msg in tool_result_msgs:
            assert msg["role"] == "user", (
                f"TOOL RESULT deve avere role='user', trovato '{msg['role']}'"
            )
        assert any("risultato_echo" in m["content"] for m in tool_result_msgs)


# ==========================================================================
# Regressione: system prompt non duplicato dopo trim
# ==========================================================================


class TestSystemPromptNotDuplicated:
    def test_system_prompt_single_after_multiple_builds(self):
        """
        Chiamare _build_llm_context N volte non deve duplicare il system prompt.
        Anche con token budget molto basso (trim aggressivo), deve rimanerne uno solo.
        """
        from src.core.engine import CoreAgent

        agent = CoreAgent(memory_mode="off", inject_git_context=False)
        agent._llm.token_budget = 200  # budget basso → trim aggressivo

        for i in range(5):
            agent._build_llm_context(f"task numero {i}", relevant_memories=[])
            agent._llm.trim_history()

        system_msgs = [m for m in agent._llm.history if m["role"] == "system"]
        assert len(system_msgs) == 1, (
            f"System prompt duplicato: {len(system_msgs)} occorrenze trovate"
        )
