"""
Session Memory for Argos.

Maintains a lightweight markdown file (.argos_session_memory.md) that tracks
the current working state of the ongoing session. Updated periodically in the
background (every N tool calls) so that structured compaction can anchor its
summary to real task state, and so the LLM never loses track of what it was
doing across multiple run_task() calls in the same server session.

Analogous to Claude Code's SessionMemory service (sessionMemory.ts).
"""

import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("argos")

# How many tool calls between session memory updates.
# Override via ARGOS_SESSION_MEMORY_UPDATE_EVERY env var.
_UPDATE_EVERY_N: int = int(os.getenv("ARGOS_SESSION_MEMORY_UPDATE_EVERY", "5"))

# Default file path — stored in CWD so it is ephemeral per-project.
# Override via ARGOS_SESSION_MEMORY_PATH env var.
_DEFAULT_PATH: str = os.getenv("ARGOS_SESSION_MEMORY_PATH", ".argos_session_memory.md")

SESSION_MEMORY_PROMPT = """\
You are the session working-memory extraction agent.
Analyze the conversation above and write a brief working-memory note (max 300 words).

This note will be injected into future LLM contexts so the agent never loses track.
Focus ONLY on:
- What the user wants to accomplish right now
- What has been tried, what worked, what failed
- Current state of in-progress work (files open, last action taken)
- The single most important next step

Be terse. Prefer bullet points. No preamble or meta-commentary.
Write only the memory content — nothing else."""


class SessionMemory:
    """
    Manages the session working-memory file.

    Lifecycle:
        record_tool_call()   — called after every tool execution in the reasoning loop
        should_update()      — returns True every UPDATE_EVERY_N calls
        update(history, fn)  — extracts working state from history, writes to file
        load()               — returns current memory content (empty string if none)
        clear()              — deletes the file and resets state (e.g. on /clear)
    """

    def __init__(self, memory_path: Path | None = None):
        self._path: Path = Path(memory_path) if memory_path else Path(_DEFAULT_PATH)
        self._tool_call_count: int = 0
        self._last_content: str = ""

    # ── Counters ──────────────────────────────────────────────────────────

    def record_tool_call(self) -> None:
        """Increments the internal tool-call counter."""
        self._tool_call_count += 1

    def should_update(self) -> bool:
        """Returns True when the update threshold has been crossed."""
        return self._tool_call_count > 0 and self._tool_call_count % _UPDATE_EVERY_N == 0

    # ── Read / Write ──────────────────────────────────────────────────────

    def update(self, history: list[dict], llm_call_fn: Callable[[list[dict]], str]) -> None:
        """
        Extracts current working state from `history` via `llm_call_fn` and
        writes it to the session memory file.

        Designed to be called in a background thread — errors are swallowed
        so the main reasoning loop is never disrupted.
        """
        if len(history) <= 2:
            return
        try:
            messages = list(history) + [{"role": "user", "content": SESSION_MEMORY_PROMPT}]
            content = llm_call_fn(messages)
            if not content or content.startswith(
                ("API Error", "Connection Error", "LLM Error", "Error:")
            ):
                logger.debug("[SessionMemory] LLM call returned error — skipping update")
                return

            self._last_content = content.strip()
            self._path.write_text(
                f"<!-- Session memory — {datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n"
                f"{self._last_content}\n",
                encoding="utf-8",
            )
            logger.debug(
                f"[SessionMemory] Updated ({len(self._last_content)} chars, "
                f"tool_calls={self._tool_call_count})"
            )
        except Exception as e:
            logger.debug(f"[SessionMemory] Update failed: {e}")

    def load(self) -> str:
        """
        Returns the current session memory content.
        Reads from the in-memory cache first; falls back to disk.
        Returns empty string if no memory is available.
        """
        if self._last_content:
            return self._last_content
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8")
                # Strip the HTML comment header added by update()
                lines = [ln for ln in raw.splitlines() if not ln.startswith("<!--")]
                self._last_content = "\n".join(lines).strip()
                return self._last_content
        except Exception as e:
            logger.debug(f"[SessionMemory] Load failed: {e}")
        return ""

    def clear(self) -> None:
        """Clears the in-memory cache and deletes the file (e.g. on /clear)."""
        self._last_content = ""
        self._tool_call_count = 0
        try:
            if self._path.exists():
                self._path.unlink()
                logger.debug("[SessionMemory] Cleared")
        except Exception as e:
            logger.debug(f"[SessionMemory] Clear failed: {e}")
