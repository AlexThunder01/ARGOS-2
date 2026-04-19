"""
ARGOS Core Agent — LLM-driven cognitive loop with LiteLLM-based multi-backend support.

This module encapsulates the agent's system prompt, conversational memory management,
and provider-agnostic LLM integration via LiteLLM (automatic retry, key rotation, provider routing).

Architecture:
- System prompt AVAILABLE TOOLS section generated from ToolRegistry (single source of truth).
- trim_history() enforces a real token budget instead of a raw message count.
- think_async() returns LLMResponse with tool_calls or content via LiteLLM.
- think_stream() yields tokens progressively for end-to-end streaming via LiteLLM.
- think_with_messages() and call_lightweight() use asyncio.run() for sync contexts (Telegram).
"""

import asyncio
import logging
import os
import platform
import time
from typing import TYPE_CHECKING, AsyncGenerator, Optional

logger = logging.getLogger("argos")

from src.llm.client import LLMResponse
from src.llm.client import complete as llm_complete
from src.llm.client import stream as llm_stream
from src.planner.planner import build_system_prompt_suffix

from .config import (
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

        Uses the lightweight model for fast compaction.
        """
        from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_LIGHTWEIGHT_MODEL

        try:
            response = asyncio.run(
                llm_complete(
                    messages=messages,
                    model=LLM_LIGHTWEIGHT_MODEL,
                    temperature=0.0,
                    api_key=LLM_API_KEY or None,
                    api_base=LLM_BASE_URL or None,
                )
            )
            return response.content or ""
        except Exception as e:
            logger.error(f"[LLM] Compaction call failed: {e}")
            return ""

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
        """Sync wrapper for CLI use. Returns text content of the LLM response."""
        response = asyncio.run(self.think_async())
        return response.content or ""

    # ──────────────────────────────────────────────────────────────────────
    # Async inference (FastAPI — non-blocking)
    # ──────────────────────────────────────────────────────────────────────

    async def think_async(self) -> LLMResponse:
        """Single LLM reasoning step — non-blocking. Returns LLMResponse with tool_calls or content."""
        self._check_time_based_mc()
        self.trim_history()
        self._last_llm_call_time = time.monotonic()

        from src.config import LLM_API_KEY, LLM_BASE_URL
        from src.tools.registry import REGISTRY

        tools = REGISTRY.as_openai_tools()

        try:
            return await llm_complete(
                messages=self.history,
                tools=tools if tools else None,
                model=self.model,
                temperature=0.0,
                api_key=LLM_API_KEY or None,
                api_base=LLM_BASE_URL or None,
            )
        except Exception as e:
            logger.error(f"[LLM] think_async failed: {e}")
            return LLMResponse(content=f"LLM Error: {e}", tool_calls=[])

    # ──────────────────────────────────────────────────────────────────────
    # Streaming inference (sync generator — SSE / CLI)
    # ──────────────────────────────────────────────────────────────────────

    async def think_stream(self):
        """Streaming LLM call. Async generator yielding text chunks."""
        self._check_time_based_mc()
        self.trim_history()
        self._last_llm_call_time = time.monotonic()

        from src.config import LLM_API_KEY, LLM_BASE_URL

        async for chunk in llm_stream(
            messages=self.history,
            model=self.model,
            temperature=0.0,
            api_key=LLM_API_KEY or None,
            api_base=LLM_BASE_URL or None,
        ):
            yield chunk

    # ──────────────────────────────────────────────────────────────────────
    # External History Methods (Telegram Chat Module)
    # ──────────────────────────────────────────────────────────────────────

    def think_with_messages(self, messages: list[dict]) -> str:
        """Sync inference with externally-provided history (Telegram)."""
        from src.config import LLM_API_KEY, LLM_BASE_URL

        try:
            response = asyncio.run(
                llm_complete(
                    messages=messages,
                    model=self.model,
                    temperature=0.3,
                    api_key=LLM_API_KEY or None,
                    api_base=LLM_BASE_URL or None,
                )
            )
            return response.content or ""
        except Exception as e:
            logger.error(f"[LLM] think_with_messages failed: {e}")
            return ""

    def call_lightweight(self, prompt: str) -> str:
        """
        Sync lightweight model call for background tasks (memory extraction).
        Fails fast with LiteLLM's retry strategy.
        """
        from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_LIGHTWEIGHT_MODEL

        try:
            response = asyncio.run(
                llm_complete(
                    messages=[{"role": "user", "content": prompt}],
                    model=LLM_LIGHTWEIGHT_MODEL,
                    temperature=0.0,
                    api_key=LLM_API_KEY or None,
                    api_base=LLM_BASE_URL or None,
                )
            )
            return response.content or ""
        except Exception:
            return ""
