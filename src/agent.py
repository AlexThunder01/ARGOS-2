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

import httpx
import requests

from src.planner.planner import build_system_prompt_suffix

from .config import LLM_BACKEND, LLM_MODEL

if TYPE_CHECKING:
    from src.tools.spec import ToolRegistry

# Token budget applied by trim_history(). One token ≈ 4 chars (conservative estimate).
DEFAULT_TOKEN_BUDGET = int(os.getenv("MAX_HISTORY_TOKENS", "8000"))


def _count_tokens(text: str) -> int:
    """Estimates token count from raw text (4 chars ≈ 1 token)."""
    return max(1, len(text) // 4)


class ArgosAgent:
    """Primary autonomous agent class. Manages the system prompt, conversation
    history, and LLM backend dispatch for OpenAI-compatible and Anthropic providers."""

    def __init__(self, registry: Optional["ToolRegistry"] = None):
        self.backend = LLM_BACKEND
        self.model = LLM_MODEL
        self.token_budget = DEFAULT_TOKEN_BUDGET

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
        0. INITIATIVE: If the user asks you to "do something", "show what you can do", or gives you free rein without specifying a task, choose a useful and concrete action autonomously (e.g., create a demo file, check the weather, list files) and execute it immediately. Do NOT ask for clarification in this case.
        1. Execute ONLY EXACTLY what the user requests. If the user says "Click on X", click on X and STOP. Do NOT read the file, do NOT open it, do NOT perform any action not explicitly requested.
        2. Do NOT invent follow-up actions. Your task ends as soon as the tool finishes.
        3. 🛑 MANDATORY: You may invoke ONLY A SINGLE "tool" PER TURN. Generating multiple actions in the same response is STRICTLY FORBIDDEN.
        4. After generating ONE JSON action, stop and wait for the result before proceeding.
        5. If the user asks you to perform a physical action (e.g., create a file, click a button, interact with OS) but you DO NOT see the corresponding tool in your AVAILABLE TOOLS block below, you MUST clearly reply that you lack the required tools/permissions. DO NOT HALLUCINATE OR PRETEND that you executed the action.
        6. FILESYSTEM — EXPLORE BEFORE READING: If the user asks to read, open, or inspect a file without specifying an exact path, ALWAYS call `list_files` first to discover what files actually exist. NEVER invent or guess file paths. Every path you use in `read_file` or any other file tool MUST come from a prior `list_files` result in this conversation.
        7. FILE NOT FOUND — NO GUESSING: If any file operation returns "File not found" or "not found", do NOT retry with a different invented path. Call `list_files` on the relevant directory to discover real paths, then retry with a real one. Guessing a different path repeatedly is always wrong.

        """.format(os_system=os_system, user=user, home_dir=home_dir, desktop_path=desktop_path)

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

    def trim_history(self):
        """
        Maintains the conversation history within the token budget.
        Drops the oldest non-system messages until the history fits within token_budget.
        """
        if len(self.history) <= 1:
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
            else:
                break

        self.history = [system_msg] + list(reversed(kept))

    # ──────────────────────────────────────────────────────────────────────
    # Synchronous inference (CLI / Telegram)
    # ──────────────────────────────────────────────────────────────────────

    def think(self) -> str:
        """Executes one step of the agent's reasoning loop (blocking).
        Use think_async() when calling from an async context (FastAPI)."""
        self.trim_history()
        try:
            if self.backend == "anthropic":
                return self._call_anthropic(self.history, temperature=0.0)
            else:
                return self._call_openai_compatible(self.history, temperature=0.0)
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
                response = requests.post(url, headers=headers, json=payload, timeout=60)

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
                return choices[0]["message"]["content"]

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

        system_msg = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg += m["content"] + "\n"
            else:
                user_msgs.append(m)

        headers = {
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model_override or self.model,
            "system": system_msg.strip(),
            "messages": user_msgs,
            "max_tokens": 1024,
            "temperature": temperature,
        }

        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=60,
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
            return content_blocks[0]["text"]
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
        self.trim_history()
        try:
            if self.backend == "anthropic":
                return await self._call_anthropic_async(self.history, temperature=0.0)
            else:
                return await self._call_openai_compatible_async(
                    self.history, temperature=0.0
                )
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
                async with httpx.AsyncClient(timeout=60) as client:
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
                    logger.error(
                        "[LLM/async] OpenAI-compatible: empty 'choices' in response"
                    )
                    return "API Error: empty response from LLM."
                return choices[0]["message"]["content"]

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

        system_msg = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg += m["content"] + "\n"
            else:
                user_msgs.append(m)

        headers = {
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model_override or self.model,
            "system": system_msg.strip(),
            "messages": user_msgs,
            "max_tokens": 1024,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
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
            return content_blocks[0]["text"]
        except Exception as e:
            return f"Connection Error: {e}"

    # ──────────────────────────────────────────────────────────────────────
    # Streaming inference (sync generator — SSE / CLI)
    # ──────────────────────────────────────────────────────────────────────

    def think_stream(self) -> Generator[str, None, None]:
        """Yields text chunks as they arrive from the LLM (sync streaming)."""
        self.trim_history()
        try:
            if self.backend == "anthropic":
                yield from self._call_anthropic_stream(self.history, temperature=0.0)
            else:
                yield from self._call_openai_compatible_stream(
                    self.history, temperature=0.0
                )
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
                url, headers=headers, json=payload, timeout=120, stream=True
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

        system_msg = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg += m["content"] + "\n"
            else:
                user_msgs.append(m)

        headers = {
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model_override or self.model,
            "system": system_msg.strip(),
            "messages": user_msgs,
            "max_tokens": 1024,
            "temperature": temperature,
            "stream": True,
        }

        try:
            with requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=120,
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
