"""
Test del Planner — verifica il parsing dell'output LLM secondo lo schema vincolato.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.planner.planner import parse_planner_response


def test_parse_new_schema_action():
    """Schema nuovo: {"thought": ..., "action": {...}, "confidence": ..., "done": false}"""
    raw = '{"thought": "Devo cercare su web", "action": {"tool": "web_search", "input": {"query": "meteo Roma"}}, "confidence": 0.9, "done": false}'
    d = parse_planner_response(raw)
    assert d.done is False
    assert d.tool == "web_search"
    assert d.tool_input == {"query": "meteo Roma"}
    assert d.confidence == 0.9
    assert d.thought == "Devo cercare su web"


def test_parse_new_schema_done():
    """Schema nuovo: risposta finale con done=true."""
    raw = '{"thought": "Ho finito", "response": "A Roma oggi c\'è sole.", "done": true}'
    d = parse_planner_response(raw)
    assert d.done is True
    assert d.response == "A Roma oggi c'è sole."
    assert d.tool is None


def test_parse_old_schema_compat():
    """Schema vecchio per retrocompatibilità: {"tool": ..., "input": ...}"""
    raw = '{"tool": "web_search", "input": {"query": "test"}}'
    d = parse_planner_response(raw)
    assert d.done is False
    assert d.tool == "web_search"
    assert d.tool_input == {"query": "test"}


def test_parse_plain_text_fallback():
    """Testo puro senza JSON → trattato come risposta finale."""
    raw = "Ciao! Oggi il meteo a Roma è soleggiato."
    d = parse_planner_response(raw)
    assert d.done is True
    assert "soleggiato" in d.response


def test_parse_malformed_json_fallback():
    """JSON troncato con tool riconoscibile → salvaged come azione (done=False)."""
    raw = '{"tool": "web_search", "input": {ROTTO'
    d = parse_planner_response(raw)
    # New behaviour: planner salvages the tool name via regex instead of giving up
    assert d.done is False
    assert d.tool == "web_search"


def test_parse_malformed_json_no_tool_fallback():
    """JSON troncato senza tool riconoscibile → fallback a testo (done=True)."""
    raw = '{"thought": "ragionamento interrotto'
    d = parse_planner_response(raw)
    assert d.done is True


def test_parse_confidence_default():
    """Se confidence è assente, default a 1.0."""
    raw = '{"thought": "ok", "action": {"tool": "system_stats", "input": null}, "done": false}'
    d = parse_planner_response(raw)
    assert d.confidence == 1.0


if __name__ == "__main__":
    test_parse_new_schema_action()
    test_parse_new_schema_done()
    test_parse_old_schema_compat()
    test_parse_plain_text_fallback()
    test_parse_malformed_json_fallback()
    test_parse_confidence_default()
    print("✅ Tutti i test Planner passati.")
