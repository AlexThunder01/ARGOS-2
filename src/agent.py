"""
ARGOS Core Agent — LLM-driven cognitive loop with model-agnostic multi-backend support.

This module encapsulates the agent's system prompt, conversational memory management,
and provider-specific API integration logic with automatic key rotation for rate-limit
resilience.

Changes from v1:
- System prompt AVAILABLE TOOLS section generated from ToolRegistry (single source of truth).
- trim_history() enforces a real token budget instead of a raw message count.
- think_stream() yields tokens progressively for end-to-end streaming.
"""

import os
import platform
import time
from typing import TYPE_CHECKING, Generator, Optional

import requests

from src.planner.planner import build_system_prompt_suffix

from .config import LLM_BACKEND, LLM_MODEL

if TYPE_CHECKING:
    from src.tools.spec import ToolRegistry

# Token budget applied by trim_history(). One token ≈ 4 chars (conservative estimate).
# The full context window is larger; this budget keeps inference fast and predictable.
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

        # --- System Context Detection ---
        user = os.environ.get("USER", "user")
        os_system = platform.system()
        home_dir = os.path.expanduser("~")

        # Resolve registry lazily to avoid circular imports at module level
        if registry is None:
            from src.tools.registry import REGISTRY

            registry = REGISTRY
        self._registry = registry

        # Core System Prompt — static context section (no tools listed here)
        static_context = """
        You are ARGOS, an intelligent and precise virtual assistant.
        PRIMARY LANGUAGE: Italian. Always respond in Italian by default, UNLESS the user speaks to you in another language — in that case, respond in their language.

        - Operating System: {os_system}
        - Current User: {user}
        - Home Directory: {home_dir}
        - When creating files on the desktop, use ONLY the correct path for the host OS (e.g., /home/{user}/Desktop on Linux).
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
        1. Execute ONLY EXACTLY what the user requests. If the user says "Click on X", click on X and STOP. Do NOT read the file, do NOT open it, do NOT perform any action not explicitly requested.
        2. Do NOT invent follow-up actions. Your task ends as soon as the tool finishes.
        3. 🛑 MANDATORY: You may invoke ONLY A SINGLE "tool" PER TURN. Generating multiple actions in the same response is STRICTLY FORBIDDEN.
        4. After generating ONE JSON action, stop and wait for the result before proceeding.

        """.format(os_system=os_system, user=user, home_dir=home_dir)

        # Build full system prompt: static context + tools from registry + response format
        self.system_prompt = (
            static_context
            + "\n"
            + self._registry.build_prompt_block()
            + "\n\n"
            + build_system_prompt_suffix()
        )

        self._init_history()

    def _init_history(self):
        """Resets the conversation history to the initial system prompt."""
        self.history = [{"role": "system", "content": self.system_prompt}]

    def add_message(self, role: str, content: str):
        """Appends a new message to the memory buffer."""
        self.history.append({"role": role, "content": str(content)})

    def trim_history(self):
        """
        Maintains the conversation history within the token budget.

        Instead of cutting by raw message count (which fails on large tool outputs),
        we estimate token usage and drop the oldest non-system messages until the
        history fits within token_budget.
        """
        if len(self.history) <= 1:
            return

        system_msg = self.history[0]
        system_tokens = _count_tokens(system_msg["content"])

        # Walk from oldest to newest, keeping messages that fit
        recent = self.history[1:]
        total = system_tokens

        # Count tokens from the end (keep newest)
        kept = []
        for msg in reversed(recent):
            msg_tokens = _count_tokens(str(msg.get("content", "")))
            if total + msg_tokens <= self.token_budget:
                kept.append(msg)
                total += msg_tokens
            else:
                # Budget exhausted — drop this and all older messages
                break

        self.history = [system_msg] + list(reversed(kept))

    # ──────────────────────────────────────────────────────────────────────
    # Synchronous inference
    # ──────────────────────────────────────────────────────────────────────

    def think(self) -> str:
        """Executes one step of the agent's reasoning loop (blocking)."""
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
        retries: int = 0,
        model_override: str = None,
        max_retries: int = 3,
    ) -> str:
        """
        Executes an OpenAI-compatible API call with dual-key rotation on rate limits.

        Args:
            max_retries: Override the retry cap. Use 1 for background/lightweight
                         queries that should fail fast without blocking the user.
        """
        from .config import LLM_API_KEY, LLM_API_KEY_2, LLM_BASE_URL

        current_key = (
            LLM_API_KEY_2 if (retries % 2 != 0 and LLM_API_KEY_2) else LLM_API_KEY
        )
        headers = {"Content-Type": "application/json"}
        if current_key:
            headers["Authorization"] = f"Bearer {current_key}"

        payload = {
            "model": model_override or self.model,
            "messages": messages,
            "temperature": temperature,
        }

        try:
            url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=60)

            if response.status_code == 429:
                if retries < max_retries:
                    if retries % 2 == 0 and LLM_API_KEY_2:
                        print("⏳ Rate Limit (Key 1). Rotating instantly to Key 2...")
                        return self._call_openai_compatible(
                            messages, temperature, retries + 1, model_override, max_retries
                        )
                    else:
                        wait_time = 5 * (retries + 1)
                        print(f"⏳ Rate Limit reached. Waiting {wait_time}s...")
                        time.sleep(wait_time)
                        return self._call_openai_compatible(
                            messages, temperature, retries + 1, model_override, max_retries
                        )
                else:
                    return "Error: Rate Limit exceeded."

            if response.status_code != 200:
                print(f"❌ LLM ERROR: {response.text}")
                return "API Error."

            return response.json()["choices"][0]["message"]["content"]

        except Exception as e:
            return f"Connection Error: {e}"

    def _call_anthropic(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        model_override: str = None,
    ) -> str:
        """Executes an Anthropic API call."""
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
                print(f"❌ ANTHROPIC ERROR: {response.text}")
                return "API Error."
            return response.json()["content"][0]["text"]
        except Exception as e:
            return f"Connection Error: {e}"

    # ──────────────────────────────────────────────────────────────────────
    # Streaming inference
    # ──────────────────────────────────────────────────────────────────────

    def think_stream(self) -> Generator[str, None, None]:
        """
        Streaming version of think(). Yields text chunks as they arrive from the LLM.

        Usage:
            for chunk in agent.think_stream():
                print(chunk, end="", flush=True)
        """
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
        """
        Streaming OpenAI-compatible call. Parses SSE chunks and yields text deltas.
        """
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
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
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
        """
        Streaming Anthropic call. Parses SSE events and yields text deltas.
        """
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
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
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
        """Executes a single LLM inference with an externally-provided message history.
        Used by the Telegram chat module where each user has their own context."""
        if self.backend == "anthropic":
            return self._call_anthropic(messages, temperature=0.3)
        else:
            return self._call_openai_compatible(messages, temperature=0.3)

    def call_lightweight(self, prompt: str) -> str:
        """
        Calls a lightweight model for background structured extraction tasks
        (memory extraction, classifiers).

        Uses max_retries=1: background queries fail fast without blocking the user.
        If the lightweight call fails, the caller should handle gracefully (e.g. skip extraction).
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
                    max_retries=1,  # Fail fast: non bloccare su background tasks
                )
        except Exception:
            return ""
