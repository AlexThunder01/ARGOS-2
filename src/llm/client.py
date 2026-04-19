"""
LiteLLM-based async LLM client for Argos.

Single responsibility: wrap LiteLLM acompletion/stream calls into clean
dataclasses. All retry, key rotation, and provider routing logic lives here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from litellm import acompletion
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger("argos")


@dataclass
class ToolCall:
    """A single native tool call returned by the LLM."""

    id: str
    name: str
    arguments: dict[str, object]


@dataclass
class LLMResponse:
    """Structured response from one LLM completion call."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _build_kwargs(
    model: str,
    messages: list[dict[str, object]],
    tools: list[dict[str, object]] | None,
    temperature: float,
    api_key: str | None,
    api_base: str | None,
    stream: bool = False,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["parallel_tool_calls"] = True
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    return kwargs


def _parse_tool_calls(raw_tool_calls: Any) -> list[ToolCall]:
    if not raw_tool_calls:
        return []
    result: list[ToolCall] = []
    for tc in raw_tool_calls:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except (json.JSONDecodeError, TypeError):
            args = {}
        result.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    return result


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def complete(
    messages: list[dict[str, object]],
    tools: list[dict[str, object]] | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    api_key: str | None = None,
    api_base: str | None = None,
) -> LLMResponse:
    """Single async LLM completion call via LiteLLM with automatic retry."""
    from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

    kwargs = _build_kwargs(
        model=model or LLM_MODEL,
        messages=messages,
        tools=tools,
        temperature=temperature,
        api_key=api_key or LLM_API_KEY or None,
        api_base=api_base or LLM_BASE_URL or None,
    )

    response = await acompletion(**kwargs)
    msg = response.choices[0].message
    usage = response.usage

    return LLMResponse(
        content=msg.content,
        tool_calls=_parse_tool_calls(msg.tool_calls),
        prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
    )


async def stream(
    messages: list[dict[str, object]],
    model: str | None = None,
    temperature: float = 0.0,
    api_key: str | None = None,
    api_base: str | None = None,
) -> AsyncGenerator[str, None]:
    """Streaming LLM call via LiteLLM. Yields text chunks."""
    from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

    kwargs = _build_kwargs(
        model=model or LLM_MODEL,
        messages=messages,
        tools=None,
        temperature=temperature,
        api_key=api_key or LLM_API_KEY or None,
        api_base=api_base or LLM_BASE_URL or None,
        stream=True,
    )

    response = await acompletion(**kwargs)
    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
