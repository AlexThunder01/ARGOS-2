"""Tests for src/llm/client.py — LiteLLM wrapper."""
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.llm.client import LLMResponse, ToolCall, complete


@pytest.mark.asyncio
async def test_complete_text_response():
    """complete() returns LLMResponse with content when model replies with text."""
    mock_msg = MagicMock()
    mock_msg.content = "Hello from LLM"
    mock_msg.tool_calls = None

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_response.usage = mock_usage

    with patch("src.llm.client.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await complete([{"role": "user", "content": "Hi"}])

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello from LLM"
    assert result.tool_calls == []
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5


@pytest.mark.asyncio
async def test_complete_single_tool_call():
    """complete() parses a single tool call from the LiteLLM response."""
    mock_tc = MagicMock()
    mock_tc.id = "call_abc123"
    mock_tc.function.name = "list_files"
    mock_tc.function.arguments = json.dumps({"path": "/tmp"})

    mock_msg = MagicMock()
    mock_msg.content = None
    mock_msg.tool_calls = [mock_tc]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_response.usage = MagicMock(prompt_tokens=20, completion_tokens=10)

    with patch("src.llm.client.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await complete(
            [{"role": "user", "content": "list /tmp"}],
            tools=[{"type": "function", "function": {"name": "list_files", "parameters": {}}}],
        )

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert isinstance(tc, ToolCall)
    assert tc.id == "call_abc123"
    assert tc.name == "list_files"
    assert tc.arguments == {"path": "/tmp"}


@pytest.mark.asyncio
async def test_complete_parallel_tool_calls():
    """complete() parses multiple parallel tool calls."""
    def _make_tc(call_id, name, args):
        tc = MagicMock()
        tc.id = call_id
        tc.function.name = name
        tc.function.arguments = json.dumps(args)
        return tc

    mock_msg = MagicMock()
    mock_msg.content = None
    mock_msg.tool_calls = [
        _make_tc("call_1", "list_files", {"path": "."}),
        _make_tc("call_2", "get_weather", {"city": "Rome"}),
    ]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_response.usage = MagicMock(prompt_tokens=30, completion_tokens=15)

    with patch("src.llm.client.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await complete([{"role": "user", "content": "weather and files"}])

    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].name == "list_files"
    assert result.tool_calls[1].name == "get_weather"


@pytest.mark.asyncio
async def test_complete_empty_tool_call_arguments():
    """complete() handles tool calls with empty or null arguments gracefully."""
    mock_tc = MagicMock()
    mock_tc.id = "call_empty"
    mock_tc.function.name = "system_stats"
    mock_tc.function.arguments = None

    mock_msg = MagicMock()
    mock_msg.content = None
    mock_msg.tool_calls = [mock_tc]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_response.usage = MagicMock(prompt_tokens=5, completion_tokens=3)

    with patch("src.llm.client.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await complete([{"role": "user", "content": "stats"}])

    assert result.tool_calls[0].arguments == {}
