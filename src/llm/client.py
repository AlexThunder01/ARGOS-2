"""
LiteLLM-based async LLM client for Argos.

Single responsibility: wrap LiteLLM acompletion/stream calls into clean
dataclasses. All retry, key rotation, and provider routing logic lives here.
"""

from __future__ import annotations

import json
import logging
import re
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

from src.resilience.circuit_breaker import CircuitBreaker

logger = logging.getLogger("argos")

# Sits above the per-call tenacity retry below: each call to complete() already
# retries internally (3 attempts), so a "failure" here means a whole retry
# sequence was exhausted. After enough of those, fail fast instead of tying up
# the API's worker (uvicorn runs with --workers 1) retrying a provider that's
# clearly down.
_llm_breaker: CircuitBreaker | None = None


def _get_llm_breaker() -> CircuitBreaker:
    global _llm_breaker
    if _llm_breaker is None:
        from src.config import CIRCUIT_BREAKER_FAILURE_THRESHOLD, CIRCUIT_BREAKER_TIMEOUT_SECONDS

        _llm_breaker = CircuitBreaker(
            failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            timeout_seconds=CIRCUIT_BREAKER_TIMEOUT_SECONDS,
        )
    return _llm_breaker


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL)


def _strip_think(text: str | None) -> str | None:
    """Remove <think>...</think> blocks emitted by reasoning models (Qwen3, DeepSeek-R1, etc.).
    Also strips unclosed <think> blocks caused by context truncation."""
    from src.config import LLM_STRIP_THINK_TAGS

    if not text or not LLM_STRIP_THINK_TAGS:
        return text
    text = _THINK_RE.sub("", text)
    # If a <think> block was opened but never closed (truncated response), drop everything from it
    text = _THINK_OPEN_RE.sub("", text)
    return text.strip() or None


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
    chat_template: str | None = None,
) -> dict[str, object]:
    # LiteLLM always strips the leading "openai/" provider prefix before sending
    # the model name to a custom api_base. To preserve names that already contain
    # a slash (e.g. "openai/gpt-oss-120b" or "meta-llama/llama-4-scout"), we
    # prepend "openai/" unconditionally — LiteLLM strips it, the endpoint receives
    # the correct full name. This also adds the required prefix for bare names.
    if api_base:
        model = f"openai/{model}"

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
    if chat_template:
        kwargs["extra_body"] = {"chat_template": chat_template}
    from src.config import LLM_STOP_TOKENS

    if LLM_STOP_TOKENS:
        kwargs["stop"] = LLM_STOP_TOKENS
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


def _looks_like_tunnel(api_base: str | None) -> bool:
    """Heuristic: reverse-proxy endpoints with ~100s header timeout need streaming."""
    if not api_base:
        return False
    return any(host in api_base for host in ("trycloudflare.com", "ngrok", "loca.lt"))


async def _collect_stream(kwargs: dict[str, object]) -> LLMResponse:
    """Stream internally and collect chunks into LLMResponse.

    Used when a reverse proxy (e.g. Cloudflare tunnel) would time out before the
    first byte of a non-streaming response. Streaming keeps the connection alive.
    """
    kwargs = {**kwargs, "stream": True}
    response = await acompletion(**kwargs)

    content_parts: list[str] = []
    tool_call_buffers: dict[int, dict[str, str]] = {}
    prompt_tokens = 0
    completion_tokens = 0

    async for chunk in response:
        choice = chunk.choices[0]
        delta = choice.delta

        if delta and delta.content:
            content_parts.append(delta.content)

        if delta and delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_call_buffers:
                    tool_call_buffers[idx] = {"id": "", "name": "", "arguments": ""}
                buf = tool_call_buffers[idx]
                if tc_delta.id:
                    buf["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        buf["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        buf["arguments"] += tc_delta.function.arguments

        if getattr(chunk, "usage", None):
            prompt_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0

        if chunk.choices[0].finish_reason:
            break

    tool_calls: list[ToolCall] = []
    for idx in sorted(tool_call_buffers):
        buf = tool_call_buffers[idx]
        try:
            args = json.loads(buf["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(id=buf["id"], name=buf["name"], arguments=args))

    return LLMResponse(
        content=_strip_think("".join(content_parts)) or None,
        tool_calls=tool_calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


async def complete(
    messages: list[dict[str, object]],
    tools: list[dict[str, object]] | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    api_key: str | None = None,
    api_base: str | None = None,
) -> LLMResponse:
    """Single async LLM completion call via LiteLLM, with retry and circuit breaker."""
    return await _get_llm_breaker().async_call(
        _complete_impl,
        messages,
        tools=tools,
        model=model,
        temperature=temperature,
        api_key=api_key,
        api_base=api_base,
    )


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _complete_impl(
    messages: list[dict[str, object]],
    tools: list[dict[str, object]] | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    api_key: str | None = None,
    api_base: str | None = None,
) -> LLMResponse:
    """Retried implementation behind complete()'s circuit breaker."""
    from src.config import (
        LLM_API_KEY,
        LLM_BASE_URL,
        LLM_CHAT_TEMPLATE,
        LLM_FORCE_COLLECT_STREAM,
        LLM_MODEL,
    )

    resolved_base = api_base or LLM_BASE_URL or None
    kwargs = _build_kwargs(
        model=model or LLM_MODEL,
        messages=messages,
        tools=tools,
        temperature=temperature,
        api_key=api_key or LLM_API_KEY or None,
        api_base=resolved_base,
        chat_template=LLM_CHAT_TEMPLATE or None,
    )

    # Force streaming when the endpoint is behind a reverse proxy with a header timeout
    # (Cloudflare quick tunnels ~100s, ngrok similar). Streaming keeps the connection
    # alive until the response is fully generated, then we re-pack to LLMResponse.
    if LLM_CHAT_TEMPLATE or LLM_FORCE_COLLECT_STREAM or _looks_like_tunnel(resolved_base):
        return await _collect_stream(kwargs)

    response = await acompletion(**kwargs)
    msg = response.choices[0].message
    usage = response.usage

    return LLMResponse(
        content=_strip_think(msg.content),
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
    from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_CHAT_TEMPLATE, LLM_MODEL

    kwargs = _build_kwargs(
        model=model or LLM_MODEL,
        messages=messages,
        tools=None,
        temperature=temperature,
        api_key=api_key or LLM_API_KEY or None,
        api_base=api_base or LLM_BASE_URL or None,
        stream=True,
        chat_template=LLM_CHAT_TEMPLATE or None,
    )

    response = await acompletion(**kwargs)
    in_think = False
    buf = ""
    from src.config import LLM_STRIP_THINK_TAGS

    async for chunk in response:
        delta = chunk.choices[0].delta
        if not (delta and delta.content):
            continue
        text = delta.content
        if not LLM_STRIP_THINK_TAGS:
            yield text
            continue
        # Filter <think>...</think> across chunk boundaries
        buf += text
        while buf:
            if in_think:
                end = buf.find("</think>")
                if end == -1:
                    buf = ""
                    break
                buf = buf[end + len("</think>") :].lstrip()
                in_think = False
            else:
                start = buf.find("<think>")
                if start == -1:
                    if buf.endswith("<") or "<thin" in buf[-6:] or "<think" in buf[-7:]:
                        # potential partial opening tag — hold the tail
                        tail_idx = max(buf.rfind("<"), 0)
                        if tail_idx < len(buf):
                            yield buf[:tail_idx]
                            buf = buf[tail_idx:]
                        break
                    yield buf
                    buf = ""
                    break
                if start > 0:
                    yield buf[:start]
                buf = buf[start + len("<think>") :]
                in_think = True
    if buf and not in_think:
        yield buf
