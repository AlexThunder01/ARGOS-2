"""
ARGOS Core Agent — LLM-driven cognitive loop with model-agnostic multi-backend support.

This module encapsulates the agent's system prompt, conversational memory management,
and provider-specific API integration logic with automatic key rotation for rate-limit
resilience.

Changes:
- System prompt AVAILABLE TOOLS section generated from ToolRegistry (single source of truth).
- trim_history() enforces a real token budget instead of a raw message count.
- think_stream() yields tokens progressively for end-to-end streaming.
- think_async() / _call_*_async() use httpx.AsyncClient — non-blocking in FastAPI.
- call_lightweight() uses max_retries=1 (fail-fast for background tasks).
"""

import asyncio
import logging
import os
import platform
import time
from typing import TYPE_CHECKING, AsyncGenerator, Generator, Optional

logger = logging.getLogger("argos")

import re

import httpx
import requests

from src.planner.planner import build_system_prompt_suffix

# Qwen-3 (and similar thinking models) wrap internal reasoning inside
# <think>...</think> tags. These MUST be stripped before the text reaches
# the planner or gets displayed to the user.
# Two patterns: closed tags and unclosed tags (model truncated mid-thought).
_THINK_CLOSED_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    """Removes <think>...</think> blocks emitted by thinking models (e.g. Qwen-3).

    Handles two cases:
    1. Properly closed: <think>reasoning</think> actual response
    2. Unclosed (truncated): <think>reasoning that never closes...
    """
    # First pass: remove properly closed <think>...</think> pairs
    text = _THINK_CLOSED_RE.sub("", text)
    # Second pass: remove unclosed <think> (model truncated mid-thought)
    text = _THINK_OPEN_RE.sub("", text)
    return text.strip()


def _stream_filter_think(
    gen: "Generator[str, None, None]",
) -> "Generator[str, None, None]":
    """Filters <think>...</think> blocks from a streaming text generator.

    Buffers incoming chunks to detect tag boundaries that may span multiple
    chunks. Text outside think blocks is yielded immediately once safe.
    """
    buffer = ""
    in_think = False
    # Minimum chars to hold back to catch a partial opening/closing tag
    _OPEN_TAG = "<think>"
    _CLOSE_TAG = "</think>"
    _HOLD = max(len(_OPEN_TAG), len(_CLOSE_TAG)) - 1

    for chunk in gen:
        buffer += chunk
        while True:
            if not in_think:
                pos = buffer.find(_OPEN_TAG)
                if pos == -1:
                    safe = buffer[:-_HOLD] if len(buffer) > _HOLD else ""
                    if safe:
                        yield safe
                        buffer = buffer[len(safe) :]
                    break
                if pos > 0:
                    yield buffer[:pos]
                buffer = buffer[pos + len(_OPEN_TAG) :]
                in_think = True
            else:
                pos = buffer.find(_CLOSE_TAG)
                if pos == -1:
                    buffer = buffer[-_HOLD:] if len(buffer) > _HOLD else buffer
                    break
                buffer = buffer[pos + len(_CLOSE_TAG) :]
                in_think = False

    if buffer and not in_think:
        yield buffer


from src.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpen

from .config import (
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_TIMEOUT_SECONDS,
    LLM_BACKEND,
    LLM_MODEL,
)

if TYPE_CHECKING:
    from src.tools.spec import ToolRegistry

# Token budget applied by trim_history(). One token ≈ 4 chars (conservative estimate).
DEFAULT_TOKEN_BUDGET = int(os.getenv("MAX_HISTORY_TOKENS", "8000"))

# Micro-compaction: number of recent compactable messages to preserve.
# Override via ARGOS_MICRO_COMPACT_KEEP env var.
MICRO_COMPACT_KEEP_RECENT: int = int(os.getenv("ARGOS_MICRO_COMPACT_KEEP", "5"))

# Minimum history length (including system message) before attempting structured
# compaction. Below this threshold the LLM summary call is not worth it.
_COMPACT_MIN_MESSAGES: int = 5

# Structured compaction is opt-in to avoid unexpected LLM calls in environments
# where the API key is configured but tests should remain deterministic.
# Set ARGOS_ENABLE_COMPACTION=1 in production .env to activate Tier 2.
_COMPACTION_ENABLED: bool = os.getenv("ARGOS_ENABLE_COMPACTION", "0") == "1"

# Content markers that identify compactable (clearable) messages.
_TOOL_RESULT_PREFIX = "TOOL RESULT:"
_WORLD_STATE_MARKERS = (
    "WORLD STATE",
    "WORKSPACE STATE UPDATED",
    "CURRENT WORKSPACE STATE",
)


def _is_compactable_message(msg: dict) -> bool:
    """Returns True if this message can be cleared during micro-compaction.

    Compactable messages carry transient execution data (tool outputs, git context
    snapshots, raw JSON tool calls) whose token cost far exceeds their long-term
    value. The most recent MICRO_COMPACT_KEEP_RECENT are preserved; older ones
    are replaced with "[cleared]".
    """
    role = msg.get("role", "")
    content = str(msg.get("content", ""))
    if role == "user" and content.startswith(_TOOL_RESULT_PREFIX):
        return True
    if role == "system" and any(marker in content for marker in _WORLD_STATE_MARKERS):
        return True
    if role == "assistant" and content.strip().startswith('{"action":'):
        return True
    return False


# Time-based micro-compact: if the gap since the last LLM call exceeds this
# threshold, the server-side prompt cache has likely expired. A pre-emptive
# micro-compact runs before the next call to avoid a full cache-miss on a large
# context. Override via ARGOS_MC_TTL_MINUTES env var.
_TIME_BASED_MC_TTL_S: int = int(os.getenv("ARGOS_MC_TTL_MINUTES", "60")) * 60

# LLM HTTP timeout — increase for slow local/tunneled models (e.g. Ollama on Kaggle).
# Override via LLM_TIMEOUT_S env var.
_LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT_S", "300"))

# Anthropic max_tokens — increase for complex responses (file gen, long analysis).
# Override via ANTHROPIC_MAX_TOKENS env var.
_ANTHROPIC_MAX_TOKENS: int = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))


def _count_tokens(text: str) -> int:
    """Estimates token count. CJK characters count as ~1 token each; other text ~4 chars/token."""
    cjk = sum(
        1
        for ch in text
        if (
            "\u1100" <= ch <= "\u11ff"  # Hangul Jamo
            or "\u3040" <= ch <= "\u30ff"  # Hiragana / Katakana
            or "\u3400" <= ch <= "\u4dbf"  # CJK Extension A
            or "\u4e00" <= ch <= "\u9fff"  # CJK Unified Ideographs
            or "\uac00" <= ch <= "\ud7af"  # Hangul Syllables
        )
    )
    return max(1, cjk + (len(text) - cjk) // 4)


def _split_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Splits history into Anthropic-format system string + user/assistant messages."""
    system_parts: list[str] = []
    user_msgs: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        else:
            user_msgs.append(m)
    return "\n".join(system_parts).strip(), user_msgs


# --- Circuit Breaker (Resilience) ---
_llm_circuit_breaker = CircuitBreaker(
    failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    timeout_seconds=CIRCUIT_BREAKER_TIMEOUT_SECONDS,
)


class ArgosAgent:
    """Primary autonomous agent class. Manages the system prompt, conversation
    history, and LLM backend dispatch for OpenAI-compatible and Anthropic providers."""

    def __init__(self, registry: Optional["ToolRegistry"] = None):
        self.backend = LLM_BACKEND
        self.model = LLM_MODEL
        self.token_budget = DEFAULT_TOKEN_BUDGET

        # Time-based micro-compact: monotonic timestamp of the last LLM call.
        # 0.0 means no call has been made yet in this session.
        self._last_llm_call_time: float = 0.0

        # Counts how many times Tier-2 structured compaction ran.
        # engine.py reads this to detect compaction and trigger post-compact cleanup.
        self._compact_count: int = 0

        user = os.environ.get("USER", "user")
        os_system = platform.system()
        home_dir = os.path.expanduser("~")

        from src.tools.helpers import _get_desktop_path

        desktop_path = _get_desktop_path()

        if registry is None:
            from src.tools.registry import REGISTRY

            registry = REGISTRY
        self._registry = registry

        static_context = """
        You are ARGOS, an intelligent and precise virtual assistant.
        PRIMARY LANGUAGE: Italian. Always respond in Italian by default, UNLESS the user speaks to you in another language — in that case, respond in their language.

        - Operating System: {os_system}
        - Current User: {user}
        - Home Directory: {home_dir}
        - When creating files on the desktop, use ONLY this exact path: {desktop_path}
        - NEVER use Windows-style paths (C:/...) when running on Linux.

        RESPONSE STYLE:
        1. Be EXTREMELY concise and natural. No robotic phrasing.
        2. After performing an action (e.g., a click), respond only with "Done." or similar. Do NOT repeat verbose mechanical descriptions like "A left click was executed on...".
        3. Present information conversationally, as a real person would. If asked for news, summarize briefly without formal bullet lists.
        4. Never append "How can I help you further?" at the end. Stop after your response.
        5. Execute ONLY the requested action.
        6. NEVER split write actions: if you need to type text and press Enter, do it in a SINGLE tool call using "press_enter": true.
        7. If a visual action fails, ask the user to reposition the window or retry.

        FUNDAMENTAL RULES:
        0. INITIATIVE: Take autonomous action ONLY when the user explicitly asks you to "show what you can do", "fammi vedere cosa sai fare", "dimostrami qualcosa", or a clearly equivalent phrase inviting a demo. Greetings, small talk, and generic messages ("ciao", "come stai", "chi sei") are NOT an invitation to act — respond conversationally. Never take initiative based on ambiguous input.
        1. Execute ONLY EXACTLY what the user requests. If the user says "Click on X", click on X and STOP. Do NOT read the file, do NOT open it, do NOT perform any action not explicitly requested.
        2. Do NOT invent follow-up actions. Your task ends as soon as the tool finishes.
        3. 🛑 MANDATORY: You may invoke ONLY A SINGLE "tool" PER TURN. Generating multiple actions in the same response is STRICTLY FORBIDDEN.
        4. After generating ONE JSON action, stop and wait for the result before proceeding.
        5. If the user asks you to perform a physical action (e.g., create a file, click a button, interact with OS) but you DO NOT see the corresponding tool in your AVAILABLE TOOLS block below, you MUST clearly reply that you lack the required tools/permissions. DO NOT HALLUCINATE OR PRETEND that you executed the action.
        6. FILESYSTEM — EXPLORE BEFORE READING: If the user asks to read, open, or inspect a file without specifying an exact path, ALWAYS call `list_files` first to discover what files actually exist. NEVER invent or guess file paths. Every path you use in `read_file` or any other file tool MUST come from a prior `list_files` result in this conversation.
        7. FILE NOT FOUND — NO GUESSING: If any file operation returns "File not found" or "not found", do NOT retry with a different invented path. Call `list_files` on the relevant directory to discover real paths, then retry with a real one. Guessing a different path repeatedly is always wrong.

        """.format(
            os_system=os_system, user=user, home_dir=home_dir, desktop_path=desktop_path
        )

        self._static_context = static_context
        self._prompt_suffix = "\n\n" + build_system_prompt_suffix()

        self._init_history()

    def _init_history_with_tools(self, tool_block: str):
        """Resets history using a specific tool block (enables per-task Tool RAG)."""
        self.system_prompt = (
            self._static_context + "\n" + tool_block + self._prompt_suffix
        )
        self.history = [{"role": "system", "content": self.system_prompt}]

    def _init_history(self):
        """Resets the conversation history to the initial system prompt (all tools)."""
        self._init_history_with_tools(self._registry.build_prompt_block())

    def add_message(self, role: str, content: str):
        """Appends a new message to the memory buffer."""
        self.history.append({"role": role.lower(), "content": str(content)})

    def _check_time_based_mc(self) -> None:
        """Pre-emptive micro-compact when the server-side prompt cache TTL has expired.

        If more than _TIME_BASED_MC_TTL_S seconds have passed since the last LLM
        call, the server-side cache is almost certainly gone. Running micro-compact
        before the next call avoids paying a full cache-miss penalty on a large,
        stale context.  Resets _last_llm_call_time so the check does not fire twice.
        """
        if self._last_llm_call_time <= 0:
            return
        gap = time.monotonic() - self._last_llm_call_time
        if gap > _TIME_BASED_MC_TTL_S:
            cleared = self.micro_compact()
            logger.info(
                f"[TimeBasedMC] Cache TTL exceeded ({gap / 60:.0f}m idle) "
                f"— pre-emptive micro-compact cleared {cleared} messages."
            )
            # Reset so we don't fire again immediately on the next call
            self._last_llm_call_time = 0.0

    def micro_compact(self) -> int:
        """
        Tier-1 context management: clears the content of old tool results,
        WorldState snapshots, and raw JSON tool calls — keeping only the most
        recent MICRO_COMPACT_KEEP_RECENT of each.

        No LLM call is made. The message list length is unchanged; only the
        *content* of old compactable messages is replaced with "[cleared]".

        Returns:
            Number of messages whose content was cleared.
        """
        if len(self.history) <= 1:
            return 0

        compactable_indices = [
            i
            for i, msg in enumerate(self.history[1:], start=1)
            if _is_compactable_message(msg)
        ]

        # Keep the most recent MICRO_COMPACT_KEEP_RECENT; clear everything older.
        if len(compactable_indices) <= MICRO_COMPACT_KEEP_RECENT:
            return 0

        to_clear = compactable_indices[:-MICRO_COMPACT_KEEP_RECENT]
        for i in to_clear:
            self.history[i] = {**self.history[i], "content": "[cleared]"}

        logger.debug(
            f"[MicroCompact] Cleared {len(to_clear)} old messages "
            f"(kept {MICRO_COMPACT_KEEP_RECENT} recent)"
        )
        return len(to_clear)

    def _call_for_compaction(self, messages: list[dict]) -> str:
        """Lightweight LLM call used exclusively by structured compaction (Tier 2).

        Uses the lightweight model with max_retries=1 so a slow/unavailable
        service fails fast and falls through to Tier 3 without blocking long.
        """
        from .config import LLM_LIGHTWEIGHT_MODEL

        if self.backend == "anthropic":
            return self._call_anthropic(
                messages,
                temperature=0.0,
                model_override=LLM_LIGHTWEIGHT_MODEL,
            )
        return self._call_openai_compatible(
            messages,
            temperature=0.0,
            model_override=LLM_LIGHTWEIGHT_MODEL,
            max_retries=1,
        )

    def trim_history(self):
        """
        Three-tier context management pipeline.

        Tier 1 — Micro-compaction (>80% budget, no LLM call):
            Clears content of old tool results, WorldState snapshots, and JSON
            tool calls. Preserves the most recent MICRO_COMPACT_KEEP_RECENT.

        Tier 2 — Structured compaction (>90% budget, LLM call, ≥5 messages):
            Calls the lightweight LLM to summarise the conversation into a
            structured 9-section summary. The summary replaces all history.
            Falls back transparently if the LLM call fails.

        Tier 3 — Drop (>100% budget, no LLM call, original behaviour):
            Drops the oldest non-system messages until the budget is satisfied.
        """
        if len(self.history) <= 1:
            return

        total = sum(_count_tokens(str(m.get("content", ""))) for m in self.history)

        # ── Tier 1: Micro-compaction ──────────────────────────────────────
        if total > self.token_budget * 0.8:
            self.micro_compact()
            total = sum(_count_tokens(str(m.get("content", ""))) for m in self.history)

        # ── Tier 2: Structured compaction ─────────────────────────────────
        if (
            _COMPACTION_ENABLED
            and total > self.token_budget * 0.9
            and len(self.history) >= _COMPACT_MIN_MESSAGES
        ):
            try:
                from src.core.compaction import compact_conversation

                new_history = compact_conversation(
                    self.history, self._call_for_compaction
                )
                if len(new_history) < len(self.history):
                    self.history = new_history
                    self._compact_count += 1
                    logger.info(
                        f"[TrimHistory] Structured compaction #{self._compact_count}: "
                        f"{len(new_history)} messages remain"
                    )
                    return
            except Exception as e:
                logger.warning(f"[TrimHistory] Compaction unavailable: {e}")

        # ── Tier 3: Drop oldest (original behaviour) ──────────────────────
        if total <= self.token_budget:
            return

        system_msg = self.history[0]
        system_tokens = _count_tokens(system_msg["content"])
        recent = self.history[1:]
        total = system_tokens
        kept = []

        for msg in reversed(recent):
            msg_tokens = _count_tokens(str(msg.get("content", "")))
            if total + msg_tokens <= self.token_budget:
                kept.append(msg)
                total += msg_tokens

        self.history = [system_msg] + list(reversed(kept))

    # ──────────────────────────────────────────────────────────────────────
    # Synchronous inference (CLI / Telegram)
    # ──────────────────────────────────────────────────────────────────────

    def think(self) -> str:
        """Executes one step of the agent's reasoning loop (blocking).
        Use think_async() when calling from an async context (FastAPI)."""
        self._check_time_based_mc()
        self.trim_history()
        try:
            if self.backend == "anthropic":
                result = _llm_circuit_breaker.call(
                    self._call_anthropic, self.history, temperature=0.0
                )
            else:
                result = _llm_circuit_breaker.call(
                    self._call_openai_compatible, self.history, temperature=0.0
                )
            self._last_llm_call_time = time.monotonic()
            return result
        except CircuitBreakerOpen as e:
            logger.error(f"[LLM] Circuit breaker open; LLM unavailable: {e}")
            raise
        except Exception as e:
            return f"LLM Error: {e}"

    def _call_openai_compatible(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        model_override: str = None,
        max_retries: int = 3,
    ) -> str:
        """Sync OpenAI-compatible call with dual-key rotation on rate limits."""
        from .config import LLM_API_KEY, LLM_API_KEY_2, LLM_BASE_URL

        available_keys = [k for k in [LLM_API_KEY, LLM_API_KEY_2] if k]
        url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
        payload = {
            "model": model_override or self.model,
            "messages": messages,
            "temperature": temperature,
        }

        exhausted: set[str] = set()
        current_key = available_keys[0] if available_keys else None

        for attempt in range(max_retries + 1):
            headers = {"Content-Type": "application/json"}
            if current_key:
                headers["Authorization"] = f"Bearer {current_key}"

            try:
                response = requests.post(
                    url, headers=headers, json=payload, timeout=_LLM_TIMEOUT
                )

                if response.status_code == 429:
                    if current_key:
                        exhausted.add(current_key)
                    remaining = [k for k in available_keys if k not in exhausted]
                    if remaining and attempt < max_retries:
                        logger.warning("[LLM] Rate Limit. Rotating to next key...")
                        current_key = remaining[0]
                        continue
                    elif attempt < max_retries:
                        wait_time = 5 * (attempt + 1)
                        exhausted.clear()
                        logger.warning(
                            f"[LLM] All keys rate-limited. Waiting {wait_time}s..."
                        )
                        time.sleep(wait_time)
                        current_key = available_keys[0] if available_keys else None
                        continue
                    return "Error: Rate Limit exceeded."

                if response.status_code != 200:
                    logger.error(
                        f"[LLM] OpenAI-compatible error {response.status_code}: {response.text[:200]}"
                    )
                    return "API Error."

                choices = response.json().get("choices", [])
                if not choices:
                    logger.error("[LLM] OpenAI-compatible: empty 'choices' in response")
                    return "API Error: empty response from LLM."
                return _strip_think_tags(choices[0]["message"]["content"])

            except Exception as e:
                return f"Connection Error: {e}"

        return "Error: Rate Limit exceeded."

    def _call_anthropic(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        model_override: str = None,
    ) -> str:
        """Sync Anthropic API call."""
        from .config import LLM_API_KEY

        system_msg, user_msgs = _split_anthropic_messages(messages)

        headers = {
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model_override or self.model,
            "system": system_msg,
            "messages": user_msgs,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "temperature": temperature,
        }

        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=_LLM_TIMEOUT,
            )
            if response.status_code != 200:
                logger.error(
                    f"[LLM] Anthropic error {response.status_code}: {response.text[:200]}"
                )
                return "API Error."
            content_blocks = response.json().get("content", [])
            if not content_blocks:
                logger.error("[LLM] Anthropic: empty 'content' in response")
                return "API Error: empty response from LLM."
            return _strip_think_tags(content_blocks[0]["text"])
        except Exception as e:
            return f"Connection Error: {e}"

    # ──────────────────────────────────────────────────────────────────────
    # Async inference (FastAPI — non-blocking)
    # ──────────────────────────────────────────────────────────────────────

    async def think_async(self) -> str:
        """
        Non-blocking version of think(). Uses httpx.AsyncClient.
        Does not block the FastAPI event loop under concurrent load.
        """
        self._check_time_based_mc()
        self.trim_history()
        try:
            if self.backend == "anthropic":
                result = await _llm_circuit_breaker.async_call(
                    self._call_anthropic_async, self.history, temperature=0.0
                )
            else:
                result = await _llm_circuit_breaker.async_call(
                    self._call_openai_compatible_async, self.history, temperature=0.0
                )
            self._last_llm_call_time = time.monotonic()
            return result
        except CircuitBreakerOpen as e:
            logger.error(f"[LLM] Circuit breaker open; LLM unavailable: {e}")
            raise
        except Exception as e:
            return f"LLM Error: {e}"

    async def _call_openai_compatible_async(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        model_override: str = None,
        max_retries: int = 3,
    ) -> str:
        """Async OpenAI-compatible call with key rotation on rate limits."""
        from .config import LLM_API_KEY, LLM_API_KEY_2, LLM_BASE_URL

        url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
        payload = {
            "model": model_override or self.model,
            "messages": messages,
            "temperature": temperature,
        }

        available_keys = [k for k in [LLM_API_KEY, LLM_API_KEY_2] if k]
        exhausted: set[str] = set()
        current_key = available_keys[0] if available_keys else None

        for attempt in range(max_retries + 1):
            headers = {"Content-Type": "application/json"}
            if current_key:
                headers["Authorization"] = f"Bearer {current_key}"

            try:
                async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
                    resp = await client.post(url, headers=headers, json=payload)

                if resp.status_code == 429:
                    logger.warning(
                        f"[LLM/async] 429 received (attempt={attempt}): {resp.text[:300]}"
                    )
                    if current_key:
                        exhausted.add(current_key)
                    remaining = [k for k in available_keys if k not in exhausted]
                    if remaining and attempt < max_retries:
                        logger.warning(
                            "[LLM/async] Rate Limit. Rotating to next key..."
                        )
                        current_key = remaining[0]
                        continue
                    elif attempt < max_retries:
                        wait = 5 * (attempt + 1)
                        exhausted.clear()
                        logger.warning(
                            f"[LLM/async] All keys rate-limited. Waiting {wait}s..."
                        )
                        await asyncio.sleep(wait)
                        current_key = available_keys[0] if available_keys else None
                        continue
                    return "Error: Rate Limit exceeded."

                if resp.status_code != 200:
                    logger.error(
                        f"[LLM/async] OpenAI-compatible error {resp.status_code}: {resp.text[:200]}"
                    )
                    return "API Error."

                choices = resp.json().get("choices", [])
                if not choices:
                    # Some providers (e.g. OpenRouter free tier) occasionally return
                    # empty choices transiently — retry before giving up
                    if attempt < max_retries:
                        logger.warning(
                            f"[LLM/async] Empty choices on attempt {attempt + 1} — retrying..."
                        )
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    logger.error(
                        "[LLM/async] OpenAI-compatible: empty 'choices' in response"
                    )
                    return "API Error: empty response from LLM."
                return _strip_think_tags(choices[0]["message"]["content"])

            except httpx.TimeoutException:
                if attempt < max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                return "Connection Error: timeout"
            except Exception as e:
                return f"Connection Error: {e}"

        return "Error: Rate Limit exceeded."

    async def _call_anthropic_async(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        model_override: str = None,
    ) -> str:
        """Async Anthropic API call."""
        from .config import LLM_API_KEY

        system_msg, user_msgs = _split_anthropic_messages(messages)

        headers = {
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model_override or self.model,
            "system": system_msg,
            "messages": user_msgs,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                )
            if resp.status_code != 200:
                logger.error(
                    f"[LLM/async] Anthropic error {resp.status_code}: {resp.text[:200]}"
                )
                return "API Error."
            content_blocks = resp.json().get("content", [])
            if not content_blocks:
                logger.error("[LLM/async] Anthropic: empty 'content' in response")
                return "API Error: empty response from LLM."
            return _strip_think_tags(content_blocks[0]["text"])
        except Exception as e:
            return f"Connection Error: {e}"

    # ──────────────────────────────────────────────────────────────────────
    # Streaming inference (sync generator — SSE / CLI)
    # ──────────────────────────────────────────────────────────────────────

    def think_stream(self) -> Generator[str, None, None]:
        """Yields text chunks as they arrive from the LLM (sync streaming).
        <think>...</think> blocks are filtered in real-time before yielding."""
        self._check_time_based_mc()
        self.trim_history()
        self._last_llm_call_time = time.monotonic()
        try:
            if self.backend == "anthropic":
                raw = self._call_anthropic_stream(self.history, temperature=0.0)
            else:
                raw = self._call_openai_compatible_stream(self.history, temperature=0.0)
            yield from _stream_filter_think(raw)
        except Exception as e:
            yield f"LLM Error: {e}"

    def _call_openai_compatible_stream(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        model_override: str = None,
    ) -> Generator[str, None, None]:
        """Streaming OpenAI-compatible call. Parses SSE chunks and yields text deltas."""
        import json as _json

        from .config import LLM_API_KEY, LLM_BASE_URL

        headers = {"Content-Type": "application/json"}
        if LLM_API_KEY:
            headers["Authorization"] = f"Bearer {LLM_API_KEY}"

        payload = {
            "model": model_override or self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        try:
            url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
            with requests.post(
                url, headers=headers, json=payload, timeout=_LLM_TIMEOUT, stream=True
            ) as resp:
                if resp.status_code != 200:
                    yield f"API Error: HTTP {resp.status_code}"
                    return

                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line = (
                        raw_line.decode("utf-8")
                        if isinstance(raw_line, bytes)
                        else raw_line
                    )
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data)
                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            yield delta
                    except _json.JSONDecodeError:
                        continue
        except Exception as e:
            yield f"Connection Error: {e}"

    def _call_anthropic_stream(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        model_override: str = None,
    ) -> Generator[str, None, None]:
        """Streaming Anthropic call. Parses SSE events and yields text deltas."""
        import json as _json

        from .config import LLM_API_KEY

        system_msg, user_msgs = _split_anthropic_messages(messages)

        headers = {
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model_override or self.model,
            "system": system_msg,
            "messages": user_msgs,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "temperature": temperature,
            "stream": True,
        }

        try:
            with requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=_LLM_TIMEOUT,
                stream=True,
            ) as resp:
                if resp.status_code != 200:
                    yield f"API Error: HTTP {resp.status_code}"
                    return

                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line = (
                        raw_line.decode("utf-8")
                        if isinstance(raw_line, bytes)
                        else raw_line
                    )
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    try:
                        event = _json.loads(data)
                        if event.get("type") == "content_block_delta":
                            text = event.get("delta", {}).get("text", "")
                            if text:
                                yield text
                    except _json.JSONDecodeError:
                        continue
        except Exception as e:
            yield f"Connection Error: {e}"

    # ──────────────────────────────────────────────────────────────────────
    # External History Methods (Telegram Chat Module)
    # ──────────────────────────────────────────────────────────────────────

    def think_with_messages(self, messages: list[dict]) -> str:
        """Sync inference with externally-provided history (Telegram)."""
        if self.backend == "anthropic":
            return self._call_anthropic(messages, temperature=0.3)
        else:
            return self._call_openai_compatible(messages, temperature=0.3)

    def call_lightweight(self, prompt: str) -> str:
        """
        Sync lightweight model call for background tasks (memory extraction).
        max_retries=1: fails fast, does not block the agent on background work.
        """
        from .config import LLM_LIGHTWEIGHT_MODEL

        try:
            if self.backend == "anthropic":
                return self._call_anthropic(
                    [{"role": "user", "content": prompt}],
                    temperature=0.0,
                    model_override=LLM_LIGHTWEIGHT_MODEL,
                )
            else:
                return self._call_openai_compatible(
                    [{"role": "user", "content": prompt}],
                    temperature=0.0,
                    model_override=LLM_LIGHTWEIGHT_MODEL,
                    max_retries=1,
                )
        except Exception:
            return ""
