"""
ARGOS-2 Core — Unified Cognitive Engine.

CoreAgent is the single brain shared by all interfaces (CLI, API, Telegram).
It orchestrates: LLM reasoning → Planning → Tool execution → Memory → Security.

New in this version:
- Hook system: PreToolUse/PostToolUse/PostToolUseFailure hooks fire around every tool call.
- Diminishing returns detection: loop stops early if LLM responses shrink for 3 steps.
- Permission audit trail: every authorize_tool decision is logged to JSONL.
- Context memoization: git status injected once per session, not rebuilt every step.
- Session hooks: SESSION_START / SESSION_END fire at task boundaries.

Usage:
    from src.core import CoreAgent

    agent = CoreAgent(memory_mode="persistent", user_id=12345)
    result = agent.run_task("List files in the current directory")
"""

import hashlib
import json
import logging
import os
import subprocess
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Generator, Optional, Set

from src.agent import ArgosAgent
from src.core.memory import EXTRACT_MIN_LENGTH
from src.executor.executor import execute_with_retry
from src.hooks.registry import HOOK_REGISTRY, HookEvent
from src.logging.otel import get_tracer
from src.logging.tracer import log_decision, log_step
from src.planner.planner import parse_planner_response
from src.tools.registry import REGISTRY
from src.tools.spec import ToolSpec
from src.world_model.state import WorldState

logger = logging.getLogger("argos")

# ── Diminishing returns constants ──────────────────────────────────────────
# If LLM response length drops below this for DIMINISHING_STEPS consecutive
# steps, we consider the loop to be spinning and stop early.
DIMINISHING_THRESHOLD = 120   # characters
DIMINISHING_STEPS = 3

# ── Permission audit log ───────────────────────────────────────────────────
_AUDIT_PATH = Path(os.getenv("ARGOS_PERMISSION_AUDIT", "logs/argos_permissions.jsonl"))


def _log_permission_decision(
    tool_name: str,
    tool_input: dict,
    decision: str,         # "allowed" | "denied_auto" | "denied_user" | "denied_hook"
    risk: str,
    source: str,           # "safe" | "api_auto" | "callback" | "hook" | "default"
) -> None:
    """Appende una riga JSONL al permission audit log."""
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "tool": tool_name,
            "risk": risk,
            "decision": decision,
            "source": source,
            "input_preview": json.dumps(tool_input or {}, ensure_ascii=False)[:200],
        }
        with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[PermissionAudit] Write failed: {e}")


# ── Context memoization ────────────────────────────────────────────────────

def _get_git_context(max_chars: int = 500) -> Optional[str]:
    """Returns a compact git status string, or None if not in a git repo."""
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
        status = subprocess.check_output(
            ["git", "status", "--short"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
        result = f"Git branch: {branch}"
        if status:
            result += f"\nChanged files:\n{status}"
        return result[:max_chars]
    except Exception:
        return None


# ==========================================================================
# Data Models
# ==========================================================================


@dataclass
class StepRecord:
    """Record of a single tool execution step."""

    step: int
    tool: str
    tool_input: dict
    result: str
    success: bool
    timestamp: str = ""


@dataclass
class TaskResult:
    """Final outcome of a CoreAgent.run_task() invocation."""

    success: bool
    task: str
    response: str
    steps_executed: int
    history: list[StepRecord] = field(default_factory=list)
    memories_used: int = 0


# ==========================================================================
# Memory Mode Enum
# ==========================================================================

MEMORY_MODES = ("off", "session", "persistent")

# ── TF-IDF for session memory ──────────────────────────────────────────────
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


def _tfidf_similarity(query: str, documents: list[str]) -> list[float]:
    if not _SKLEARN_AVAILABLE or not documents:
        return [0.0] * len(documents)
    try:
        corpus = documents + [query]
        vec = TfidfVectorizer(min_df=1).fit_transform(corpus)
        scores = sklearn_cosine(vec[-1], vec[:-1]).flatten()
        return scores.tolist()
    except Exception:
        return [0.0] * len(documents)


# ==========================================================================
# CoreAgent — The Unified Brain
# ==========================================================================


class CoreAgent:
    """
    The single cognitive engine for ARGOS-2.

    Args:
        memory_mode: 'off' (stateless), 'session' (RAM-only), 'persistent' (SQLite DB).
        user_id: Numeric user identifier. Defaults to sha256 hash of $USER.
        max_steps: Maximum tool execution steps per task.
        require_confirmation: If True, dangerous tools are auto-blocked (API mode).
        confirmation_callback: Optional function(tool_name, tool_input) -> bool.
                               Used by CLI to prompt the user for authorization.
        allowed_tools: If set, only these tool names are exposed to the LLM.
        inject_git_context: If True, injects git branch/status into context once per task.
    """

    def __init__(
        self,
        memory_mode: str = "off",
        user_id: Optional[int] = None,
        max_steps: int = 10,
        require_confirmation: bool = False,
        confirmation_callback: Optional[Callable] = None,
        allowed_tools: Optional[Set[str]] = None,
        inject_git_context: bool = True,
    ):
        if memory_mode not in MEMORY_MODES:
            raise ValueError(
                f"Invalid memory_mode '{memory_mode}'. Must be one of {MEMORY_MODES}"
            )

        self.memory_mode = memory_mode
        self.max_steps = max_steps
        self.require_confirmation = require_confirmation
        self.confirmation_callback = confirmation_callback
        self.inject_git_context = inject_git_context

        # Build filtered or full ToolSpec registry
        active_registry = (
            REGISTRY.filter(allowed_tools) if allowed_tools is not None else REGISTRY
        )
        self._available_tools: dict[str, ToolSpec] = {
            name: active_registry[name] for name in active_registry.names()
        }

        # Resolve user ID
        if user_id is not None:
            self.user_id = user_id
        else:
            linux_user = os.environ.get("USER", "argos")
            self.user_id = (
                int(hashlib.sha256(linux_user.encode()).hexdigest()[:16], 16) % (2**31)
            )

        # LLM provider — receives filtered registry so prompt matches available tools
        self._llm = ArgosAgent(registry=active_registry)

        # Session memory (RAM-only, cleared on exit)
        self._session_memories: deque[dict] = deque(maxlen=500)

        # Context cache: computed once per task, cleared between tasks
        self._git_context_cache: Optional[str] = None

        logger.info(
            f"[CoreAgent] Initialized | memory={memory_mode} | "
            f"user_id={self.user_id} | backend={self._llm.backend} | "
            f"model={self._llm.model} | tools={len(self._available_tools)}/{len(REGISTRY)}"
        )

    # --- Public Properties ---

    @property
    def backend(self) -> str:
        return self._llm.backend

    @property
    def model(self) -> str:
        return self._llm.model

    # ==========================================================================
    # Main Entry Point
    # ==========================================================================

    def run_task(self, task: str) -> TaskResult:
        """
        Executes a natural language task through the full cognitive pipeline:
        1. SESSION_START hook
        2. Context memoization (git status injected once)
        3. Retrieve relevant memories (if enabled)
        4. LLM reasoning loop with:
           - PreToolUse hooks (can block execution)
           - PostToolUse / PostToolUseFailure hooks
           - Diminishing returns early stop
        5. Extract new memories (if enabled)
        6. SESSION_END hook

        Returns a TaskResult with the final response and execution history.
        """
        tracer = get_tracer()

        # ── SESSION_START ──────────────────────────────────────────────────
        HOOK_REGISTRY.fire_session(
            HookEvent.SESSION_START,
            task=task,
            user_id=self.user_id,
        )

        with tracer.start_as_current_span(
            "core.run_task",
            attributes={
                "task": task[:200],
                "user_id": self.user_id,
                "memory_mode": self.memory_mode,
            },
        ) as root_span:
            state = WorldState()
            state.current_task = task

            # ── Phase 1: Context Memoization ──────────────────────────────
            if self.inject_git_context and self._git_context_cache is None:
                self._git_context_cache = _get_git_context()

            # ── Phase 2: Memory Retrieval ──────────────────────────────────
            with tracer.start_as_current_span("core.retrieve_memories") as mem_span:
                relevant_memories = self._retrieve_memories(task)
                mem_span.set_attribute("memories.count", len(relevant_memories))

            # ── Phase 3: Build LLM context ────────────────────────────────
            self._llm._init_history()

            # Inject git context once (memoized)
            if self._git_context_cache:
                self._llm.add_message(
                    "system",
                    f"CURRENT WORKSPACE STATE:\n{self._git_context_cache}",
                )

            # Inject current date
            self._llm.add_message(
                "system",
                f"Today's date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            )

            # Inject relevant memories
            if relevant_memories:
                memory_context = "\n".join(
                    f"- [{m['category']}] {m['content']}" for m in relevant_memories
                )
                self._llm.add_message(
                    "system",
                    f"THINGS YOU KNOW ABOUT THE USER (use when relevant):\n{memory_context}",
                )

            self._llm.add_message("user", task)

            # ── Phase 4: Reasoning Loop ───────────────────────────────────
            step_records: list[StepRecord] = []
            final_response = ""
            response_lengths: deque[int] = deque(maxlen=DIMINISHING_STEPS)

            for step_num in range(self.max_steps):
                raw = self._llm.think()
                decision = parse_planner_response(raw)
                log_decision(
                    logger,
                    decision.thought,
                    decision.tool or "done",
                    decision.confidence,
                )

                # ── Diminishing returns detection ──────────────────────────
                response_lengths.append(len(raw))
                if (
                    len(response_lengths) == DIMINISHING_STEPS
                    and all(l < DIMINISHING_THRESHOLD for l in response_lengths)
                    and not decision.done
                ):
                    logger.warning(
                        f"[CoreAgent] Diminishing returns detected after {step_num + 1} steps "
                        f"(lengths={list(response_lengths)}). Stopping loop."
                    )
                    final_response = decision.response or raw
                    root_span.set_attribute("stop_reason", "diminishing_returns")
                    break

                if decision.done:
                    final_response = decision.response or raw
                    logger.info(f"[CoreAgent] Task completed in {step_num + 1} step(s).")
                    root_span.set_attribute("steps.total", step_num + 1)
                    break

                tool_name = decision.tool
                tool_input = decision.tool_input

                if not tool_name or tool_name not in self._available_tools:
                    final_response = f"Unknown or restricted tool: '{tool_name}'"
                    logger.error(f"[CoreAgent] {final_response}")
                    break

                spec = self._available_tools[tool_name]

                # ── PreToolUse hooks ───────────────────────────────────────
                pre_result = HOOK_REGISTRY.fire_pre_tool(tool_name, tool_input or {})
                if not pre_result.allowed:
                    final_response = f"Action '{tool_name}' blocked by hook: {pre_result.block_reason}"
                    logger.warning(f"[CoreAgent] {final_response}")
                    self._llm.add_message(
                        "assistant",
                        json.dumps({"action": {"tool": tool_name, "input": tool_input}}),
                    )
                    self._llm.add_message("user", f"ACTION BLOCKED: {pre_result.block_reason}")
                    break

                # ── Security Gate (with audit trail) ──────────────────────
                if not self._authorize_tool(spec, tool_input):
                    final_response = f"Action '{tool_name}' denied."
                    state.record_action(tool_name, tool_input, "Denied by user.", False)
                    step_records.append(
                        StepRecord(
                            step=state.step_count,
                            tool=tool_name,
                            tool_input=tool_input or {},
                            result="Denied by user.",
                            success=False,
                        )
                    )
                    self._llm.add_message(
                        "assistant",
                        json.dumps({"action": {"tool": tool_name, "input": tool_input}}),
                    )
                    self._llm.add_message("user", "ACTION DENIED BY USER. STOP.")
                    break

                # ── Execute Tool ───────────────────────────────────────────
                with tracer.start_as_current_span(
                    "core.tool_execution",
                    attributes={"tool.name": tool_name, "tool.step": step_num + 1},
                ) as tool_span:
                    action_result = execute_with_retry(spec, tool_input)
                    tool_span.set_attribute("tool.success", action_result.success)
                    tool_span.set_attribute(
                        "tool.result_preview", action_result.message[:200]
                    )

                # ── PostToolUse hooks ──────────────────────────────────────
                HOOK_REGISTRY.fire_post_tool(
                    tool_name=tool_name,
                    tool_input=tool_input or {},
                    result=action_result.message,
                    success=action_result.success,
                )

                state.record_action(
                    tool_name, tool_input, action_result.message, action_result.success
                )
                log_step(logger, state, tool_name, action_result.message, action_result.success)

                step_records.append(
                    StepRecord(
                        step=state.step_count,
                        tool=tool_name,
                        tool_input=tool_input or {},
                        result=action_result.message[:500],
                        success=action_result.success,
                        timestamp=state.action_history[-1].timestamp,
                    )
                )

                self._llm.add_message(
                    "assistant",
                    json.dumps({"action": {"tool": tool_name, "input": tool_input}}),
                )
                self._llm.add_message("user", f"TOOL RESULT: {action_result.message}")

                final_response = (
                    action_result.message
                    if action_result.success
                    else f"Step failure: {action_result.message}"
                )

            # ── Phase 5: Memory Extraction ────────────────────────────────
            if self.memory_mode != "off" and final_response:
                with tracer.start_as_current_span("core.extract_memories"):
                    self._maybe_extract_memories(task, relevant_memories)

            # Invalidate git cache so next task gets a fresh snapshot
            self._git_context_cache = None

            success = not final_response.startswith(
                ("Step failure", "Unknown tool", "Action", "Blocked")
            )
            root_span.set_attribute("result.success", success)

            task_result = TaskResult(
                success=success,
                task=task,
                response=final_response,
                steps_executed=state.step_count,
                history=step_records,
                memories_used=len(relevant_memories),
            )

        # ── SESSION_END ────────────────────────────────────────────────────
        HOOK_REGISTRY.fire_session(
            HookEvent.SESSION_END,
            task=task,
            result=task_result,
        )

        return task_result

    # ==========================================================================
    # Streaming Entry Point
    # ==========================================================================

    def run_task_stream(self, task: str) -> Generator[str, None, None]:
        """
        Streaming variant for single-turn, no-tool queries.
        Yields LLM text chunks as they arrive (SSE / CLI live output).
        """
        self._llm._init_history()
        if self.inject_git_context:
            ctx = _get_git_context()
            if ctx:
                self._llm.add_message("system", f"CURRENT WORKSPACE STATE:\n{ctx}")
        self._llm.add_message("user", task)
        yield from self._llm.think_stream()

    # ==========================================================================
    # Telegram-Specific Entry Point
    # ==========================================================================

    def think_with_context(self, messages: list[dict]) -> str:
        return self._llm.think_with_messages(messages)

    def call_lightweight(self, prompt: str) -> str:
        return self._llm.call_lightweight(prompt)

    # ==========================================================================
    # Memory Management (Private)
    # ==========================================================================

    def _retrieve_memories(self, query: str) -> list[dict]:
        if self.memory_mode == "off":
            return []
        if self.memory_mode == "session":
            return self._retrieve_session_memories(query)
        if self.memory_mode == "persistent":
            try:
                from src.core.memory import retrieve_relevant_memories
                return retrieve_relevant_memories(self.user_id, query, top_k=6)
            except Exception as e:
                logger.warning(f"[CoreAgent] Memory retrieval failed: {e}")
                return []
        return []

    def _retrieve_session_memories(self, query: str, top_k: int = 3) -> list[dict]:
        if not self._session_memories:
            return []
        memories = list(self._session_memories)
        documents = [m["content"] for m in memories]
        if _SKLEARN_AVAILABLE:
            scores = _tfidf_similarity(query, documents)
            scored = sorted(zip(scores, memories), key=lambda x: x[0], reverse=True)
            return [m for score, m in scored[:top_k] if score > 0.05]
        else:
            query_words = {w for w in query.lower().split() if len(w) > 3}
            return [
                m for m in memories
                if any(w in m["content"].lower() for w in query_words)
            ][:top_k]

    def _maybe_extract_memories(self, user_message: str, existing_memories: list[dict]):
        if self.memory_mode == "session":
            if len(user_message) > EXTRACT_MIN_LENGTH:
                self._session_memories.append(
                    {"content": user_message[:200], "category": "fact"}
                )
            return
        if self.memory_mode == "persistent":
            try:
                from src.core.memory import (
                    extract_memories_from_text,
                    save_extracted_memories,
                    should_extract_memory,
                )
                if should_extract_memory(user_message, 5):
                    facts = extract_memories_from_text(
                        user_message, existing_memories, self._llm.call_lightweight
                    )
                    if facts:
                        save_extracted_memories(
                            self.user_id, facts, llm_call_fn=self._llm.call_lightweight
                        )
            except Exception as e:
                logger.warning(f"[CoreAgent] Memory extraction failed: {e}")

    # ==========================================================================
    # Security Gate (Private)
    # ==========================================================================

    def _authorize_tool(self, spec_or_name, tool_input: dict) -> bool:
        """
        Checks if a tool execution should proceed.
        Logs every decision to the permission audit trail.

        Args:
            spec_or_name: ToolSpec instance or tool name string (backward compat).
        """
        if isinstance(spec_or_name, str):
            spec = self._available_tools.get(spec_or_name) or REGISTRY.get(spec_or_name)
            if spec is None:
                _log_permission_decision(
                    str(spec_or_name), tool_input or {}, "denied_auto", "unknown", "not_found"
                )
                return False
        else:
            spec = spec_or_name

        # ── Safe tools: always allowed ──
        if not spec.requires_confirmation():
            _log_permission_decision(spec.name, tool_input or {}, "allowed", spec.risk, "safe")
            return True

        # ── API mode: auto-block ──
        if self.require_confirmation:
            logger.warning(
                f"[CoreAgent] Auto-blocked '{spec.name}' (risk={spec.risk})"
            )
            _log_permission_decision(
                spec.name, tool_input or {}, "denied_auto", spec.risk, "api_auto"
            )
            return False

        # ── CLI mode: ask the user ──
        if self.confirmation_callback:
            allowed = self.confirmation_callback(spec.name, tool_input)
            _log_permission_decision(
                spec.name,
                tool_input or {},
                "allowed" if allowed else "denied_user",
                spec.risk,
                "callback",
            )
            return allowed

        # ── Default: allow ──
        _log_permission_decision(spec.name, tool_input or {}, "allowed", spec.risk, "default")
        return True
