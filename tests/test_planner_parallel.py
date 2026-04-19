"""Tests for parse_litellm_response() — parallel tool call parsing."""

import json

from src.llm.client import LLMResponse, ToolCall
from src.planner.planner import parse_litellm_response


def test_parse_single_tool_call():
    response = LLMResponse(
        content=None,
        tool_calls=[ToolCall(id="call_1", name="list_files", arguments={"path": "."})],
    )
    decisions = parse_litellm_response(response)
    assert len(decisions) == 1
    assert decisions[0].tool == "list_files"
    assert decisions[0].tool_input == {"path": "."}
    assert decisions[0].done is False


def test_parse_parallel_tool_calls():
    response = LLMResponse(
        content=None,
        tool_calls=[
            ToolCall(id="call_1", name="list_files", arguments={"path": "."}),
            ToolCall(id="call_2", name="web_search", arguments={"query": "argos agent"}),
        ],
    )
    decisions = parse_litellm_response(response)
    assert len(decisions) == 2
    assert decisions[0].tool == "list_files"
    assert decisions[1].tool == "web_search"


def test_parse_final_answer():
    response = LLMResponse(content="The answer is 42.", tool_calls=[])
    decisions = parse_litellm_response(response)
    assert len(decisions) == 1
    assert decisions[0].done is True
    assert decisions[0].response == "The answer is 42."
    assert decisions[0].tool is None


def test_parse_empty_response():
    """Empty content and no tool calls → treated as final answer."""
    response = LLMResponse(content=None, tool_calls=[])
    decisions = parse_litellm_response(response)
    assert len(decisions) == 1
    assert decisions[0].done is True


def test_parse_content_with_json_fallback():
    """If content looks like legacy JSON planner format, it still works."""
    legacy_json = json.dumps(
        {
            "thought": "I need to list files",
            "action": {"tool": "list_files", "input": {"path": "/tmp"}},
            "done": False,
        }
    )
    response = LLMResponse(content=legacy_json, tool_calls=[])
    decisions = parse_litellm_response(response)
    assert decisions[0].tool == "list_files"
    assert decisions[0].done is False
