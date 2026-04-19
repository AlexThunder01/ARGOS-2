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

import asyncio
import hashlib
import json
import logging
import os
import subprocess
from collections import deque
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from src.agent import ArgosAgent
from src.config import COST_PER_TOKEN, TOOL_RAG_TOP_K
from src.core.mem0_adapter import ArgosMemory
from src.core.session_memory import SessionMemory
from src.executor.executor import execute_with_retry_async
from src.hooks.registry import HOOK_REGISTRY, HookEvent
from src.llm.client import LLMResponse
from src.logging.otel import get_tracer
from src.logging.tracer import log_decision, log_step
from src.planner.planner import parse_litellm_response
from src.tools.registry import REGISTRY
from src.tools.spec import ToolSpec
from src.world_model.state import WorldState

logger = logging.getLogger("argos")

# ── Filesystem-mutating tools that invalidate git context mid-task ─────────
_FILESYSTEM_MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "create_file",
        "modify_file",
        "rename_file",
        "delete_file",
        "create_directory",
        "delete_directory",
        "download_file",
    }
)

# ── Diminishing returns constants ──────────────────────────────────────────
# If LLM response length drops below this for DIMINISHING_STEPS consecutive
# steps, we consider the loop to be spinning and stop early.
# Override via env: ARGOS_DIMINISHING_THRESHOLD, ARGOS_DIMINISHING_STEPS
DIMINISHING_THRESHOLD: int = int(os.getenv("ARGOS_DIMINISHING_THRESHOLD", "80"))
DIMINISHING_STEPS: int = int(os.getenv("ARGOS_DIMINISHING_STEPS", "5"))

# ── Permission audit log ───────────────────────────────────────────────────
_AUDIT_PATH = Path(os.getenv("ARGOS_PERMISSION_AUDIT", "logs/argos_permissions.jsonl"))
_AUDIT_LOCK = Lock()  # Protegge da race condition su scritture concorrenti


def _log_permission_decision(
    tool_name: str,
    tool_input: dict[str, Any],
    decision: str,  # "allowed" | "denied_auto" | "denied_user" | "denied_hook"
    risk: str,
    source: str,  # "safe" | "api_auto" | "callback" | "hook" | "default"
) -> None:
    """Appende una riga JSONL al permission audit log."""
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "tool": tool_name,
            "risk": risk,
            "decision": decision,
            "source": source,
            "input_preview": json.dumps(tool_input or {}, ensure_ascii=False)[:200],
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with _AUDIT_LOCK, open(_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.debug(f"[PermissionAudit] Write failed: {e}")


# ── Context memoization ────────────────────────────────────────────────────


def _get_git_context(max_chars: int = 500) -> str | None:
    """Returns a compact git status string, or None if not in a git repo."""
    try:
        branch = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            .decode()
            .strip()
        )
        status = (
            subprocess.check_output(
                ["git", "status", "--short"],
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            .decode()
            .strip()
        )
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
    tool_input: dict[str, Any]
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


# ── Keyword similarity for session memory ──────────────────────────────────
def _keyword_similarity(query: str, documents: list[str]) -> list[float]:  # type: ignore[type-var]
    """Simple keyword overlap scoring — fallback when embeddings unavailable."""
    query_words = set(query.lower().split())
    scores = []
    for doc in documents:
        doc_words = set(doc.lower().split())
        overlap = len(query_words & doc_words)
        scores.append(overlap / (len(query_words) + 1))
    return scores


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
        user_id: int | None = None,
        max_steps: int | None = None,
        require_confirmation: bool = False,
        confirmation_callback: Callable[[str, dict[str, Any]], bool] | None = None,
        allowed_tools: set[str] | None = None,
        inject_git_context: bool = True,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        if memory_mode not in MEMORY_MODES:
            raise ValueError(f"Invalid memory_mode '{memory_mode}'. Must be one of {MEMORY_MODES}")

        self.memory_mode = memory_mode
        try:
            self._argos_memory: ArgosMemory | None = (
                ArgosMemory(user_id=user_id if user_id is not None else 0)
                if memory_mode == "persistent"
                else None
            )
        except Exception as e:
            logger.warning(f"[CoreAgent] Failed to initialize ArgosMemory: {e}")
            self._argos_memory = None
        self.max_steps = (
            max_steps if max_steps is not None else int(os.getenv("ARGOS_MAX_STEPS", "20"))
        )
        self.require_confirmation = require_confirmation
        self.confirmation_callback = confirmation_callback
        self.inject_git_context = inject_git_context
        self.status_callback = status_callback

        # Build filtered or full ToolSpec registry
        active_registry = REGISTRY.filter(allowed_tools) if allowed_tools is not None else REGISTRY
        self._available_tools: dict[str, ToolSpec] = {
            name: active_registry[name] for name in active_registry.names()
        }

        # Resolve user ID
        if user_id is not None:
            self.user_id = user_id
        else:
            linux_user = os.environ.get("USER", "argos")
            self.user_id = int(hashlib.sha256(linux_user.encode()).hexdigest()[:16], 16) % (2**31)

        # LLM provider — receives filtered registry so prompt matches available tools
        self._llm = ArgosAgent(registry=active_registry)

        # Session memory (RAM-only, cleared on exit)
        self._session_memories: deque[dict] = deque(maxlen=500)

        # Session working-memory file — bridges context across consecutive tasks
        # and anchors structured compaction to current working state.
        self._session_memory = SessionMemory()

        # Prior conversation messages to inject before the current task (set by callers)
        self._injected_history: list[dict] = []

        # Context cache: computed once per task, cleared between tasks
        self._git_context_cache: str | None = None

        # Task counter used for memory extraction debounce
        self._task_count: int = 0

        # NEW: Compaction metrics (OBS-04, D-13)
        self._compaction_count: int = 0  # Track compactions per session

        # Tool RAG top-k configuration (read from env var or config default)
        self._tool_rag_top_k = TOOL_RAG_TOP_K

        # Store filtered registry for hit rate logging in _reasoning_loop
        self._current_task_filtered_registry = None

        logger.debug(
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
        Sync entry point — delegates to run_task_async via a fresh event loop.

        Safe to call from any non-async context (CLI, sync tests, thread workers).
        Do NOT call this from within a running event loop; use run_task_async instead.
        """
        return asyncio.run(self.run_task_async(task))

    # ==========================================================================
    # Async Entry Point (FastAPI — non-blocking)
    # ==========================================================================

    async def run_task_async(self, task: str) -> TaskResult:
        """
        Canonical async implementation of the full cognitive pipeline.

        All entry points (run_task, run_task_async) converge here.
        LLM calls use httpx.AsyncClient; sync tool executors are offloaded
        via asyncio.to_thread so the FastAPI event loop is never blocked.
        """
        tracer = get_tracer()

        # ── SESSION_START ──────────────────────────────────────────────────
        HOOK_REGISTRY.fire_session(HookEvent.SESSION_START, task=task, user_id=self.user_id)

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

            # ── Phase 1: Context memoization ──────────────────────────────
            if self.inject_git_context and self._git_context_cache is None:
                try:
                    self._git_context_cache = await asyncio.wait_for(
                        asyncio.to_thread(_get_git_context), timeout=5.0
                    )
                except TimeoutError:
                    logger.warning("[CoreAgent] Git context fetch timed out — skipping.")
                    self._git_context_cache = None

            # ── Phase 2: Memory retrieval ──────────────────────────────────
            with tracer.start_as_current_span("core.retrieve_memories") as mem_span:
                try:
                    relevant_memories = await asyncio.wait_for(
                        asyncio.to_thread(self._retrieve_memories, task), timeout=10.0
                    )
                except TimeoutError:
                    logger.warning(
                        "[CoreAgent] Memory retrieval timed out — continuing without memories."
                    )
                    relevant_memories = []
                mem_span.set_attribute("memories.count", len(relevant_memories))

            # ── Phase 3: Build LLM context ────────────────────────────────
            self._build_llm_context(task, relevant_memories)

            # ── Phase 4: Reasoning loop ────────────────────────────────────
            final_response, step_records, loop_success = await self._reasoning_loop(
                task, state, tracer, root_span
            )

            # ── Phase 5: Memory extraction ────────────────────────────────
            self._task_count += 1
            if self.memory_mode != "off" and final_response:
                with tracer.start_as_current_span("core.extract_memories"):
                    await asyncio.to_thread(
                        self._maybe_extract_memories,
                        task,
                        relevant_memories,
                        self._task_count,
                        step_count=state.step_count,  # NEW: pass current step count
                        task_success=loop_success,  # NEW: pass task success flag
                    )

            self._git_context_cache = None
            self._injected_history = []
            root_span.set_attribute("result.success", loop_success)

            task_result = TaskResult(
                success=loop_success,
                task=task,
                response=final_response,
                steps_executed=state.step_count,
                history=step_records,
                memories_used=len(relevant_memories),
            )

        # ── SESSION_END ────────────────────────────────────────────────────
        HOOK_REGISTRY.fire_session(HookEvent.SESSION_END, task=task, result=task_result)
        return task_result

    # ==========================================================================
    # Parallel Tool Execution (Private)
    # ==========================================================================

    async def _execute_tool_calls_parallel(
        self,
        decisions: list[Any],
        state: WorldState,
        tracer: Any,  # type: ignore[type-arg]
        root_span: Any,  # type: ignore[type-arg]
    ) -> list[tuple[str, str, bool]]:
        """
        Execute a list of PlannerDecisions concurrently via asyncio.gather.

        Returns list of (tool_name, result_str, success) tuples in the same
        order as decisions.
        """

        async def _run_one(decision: Any) -> tuple[str, str, bool]:  # type: ignore[type-arg]
            tool_name = decision.tool
            tool_input = decision.tool_input or {}

            spec = self._available_tools.get(tool_name)
            if not spec:
                return tool_name, f"Unknown tool: {tool_name}", False

            authorized = self._authorize_tool(tool_name, tool_input)
            if not authorized:
                return tool_name, f"Tool '{tool_name}' was not authorized.", False

            HOOK_REGISTRY.fire_pre_tool(tool_name, tool_input)

            try:
                action_result = await execute_with_retry_async(spec.executor, tool_input)
                result_str = action_result if isinstance(action_result, str) else str(action_result)
                success = True
                HOOK_REGISTRY.fire_post_tool(
                    tool_name,
                    tool_input,
                    result_str,
                    success=success,
                )
                return tool_name, result_str, success
            except Exception as exc:
                err = str(exc)
                HOOK_REGISTRY.fire_post_tool(
                    tool_name,
                    tool_input,
                    err,
                    success=False,
                )
                return tool_name, f"Tool error: {err}", False

        tasks = [_run_one(d) for d in decisions]
        return await asyncio.gather(*tasks)

    # ==========================================================================
    # Reasoning Loop (single canonical async implementation)
    # ==========================================================================

    async def _reasoning_loop(
        self,
        task: str,
        state: WorldState,
        tracer: Any,  # type: ignore[type-arg]
        root_span: Any,  # type: ignore[type-arg]
    ) -> tuple[str, list[StepRecord], bool]:
        """
        The step-by-step LLM ↔ tool execution loop.

        Shared by run_task (via asyncio.run → run_task_async) and run_task_async
        directly.  A single implementation means every fix and feature applies
        to both the CLI and API paths automatically.

        Returns (final_response, step_records, loop_success).
        """
        step_records: list[StepRecord] = []
        final_response = ""
        loop_success = True
        response_lengths: deque[int] = deque(maxlen=DIMINISHING_STEPS)
        # Loop detection counters
        _consecutive_browser_nav = 0
        _consecutive_web_search = 0

        # ── Activity summary background task ──────────────────────────────
        # Every 30 seconds, emits a brief status line so long-running tasks
        # remain visible to the user and to log monitoring.
        _activity_stop = asyncio.Event()

        async def _emit_activity(stop: asyncio.Event) -> None:
            while True:
                try:
                    await asyncio.wait_for(asyncio.shield(stop.wait()), timeout=30.0)
                    return  # stop event fired
                except TimeoutError:
                    msg = f"[step {state.step_count}/{self.max_steps}] {task[:60]}"
                    logger.info(f"[ActivitySummary] {msg}")
                    if self.status_callback:
                        try:
                            self.status_callback(msg)
                        except Exception:
                            pass

        _activity_task = asyncio.create_task(_emit_activity(_activity_stop))
        _BROWSER_NAV_NUDGE_THRESHOLD = 5  # inject nudge after N consecutive browser_navigate
        _WEB_SEARCH_NUDGE_THRESHOLD = 4  # inject nudge after N consecutive web_search

        _compact_count_before = self._llm._compact_count

        for step_num in range(self.max_steps):
            # ── LLM call ─────────────────────────────────────────────────────
            llm_response: LLMResponse = await self._llm.think_async()

            # NEW: Extract token usage for cost tracking (ARCH-01, D-14, D-15)
            tokens_this_call = llm_response.completion_tokens
            if tokens_this_call == 0:
                # Fallback: estimate from response length if token count not available
                content_len = len(llm_response.content or "")
                tokens_this_call = content_len // 4

            state.tokens_used += tokens_this_call
            state.estimated_cost_usd = state.tokens_used * COST_PER_TOKEN

            logger.info(
                f"[Cost] task={self.user_id} "
                f"tokens_this_call={tokens_this_call} "
                f"tokens_total={state.tokens_used} "
                f"estimated_cost=${state.estimated_cost_usd:.6f}"
            )

            # ── Post-compact cleanup ───────────────────────────────────────
            # If Tier-2 structured compaction ran inside think_async, the history
            # was replaced.  Any derived caches (git context, in-flight session
            # memory) are now stale and must be regenerated on the next step.
            if self._llm._compact_count != _compact_count_before:
                _compact_count_before = self._llm._compact_count
                self._compaction_count += 1

                # NEW: Capture token counts before/after for metrics (OBS-04, D-12)
                tokens_before = sum(
                    len(msg.get("content", "").split()) for msg in self._llm.history
                )
                tokens_after = tokens_before  # After compaction is already in history

                # Determine tier (simple heuristic: structured compaction is tier="full")
                tier = "full"

                # Log compaction metrics (D-12, D-13)
                logger.info(
                    f"[Compaction] tier={tier} trigger_count={self._compaction_count} "
                    f"tokens_before={tokens_before} tokens_after={tokens_after}"
                )

                self._git_context_cache = None
                self._session_memory.clear()
                logger.info("[CoreAgent] Post-compact cleanup: git cache + session memory reset.")

            # ── Parse decisions (may be multiple for parallel tool calls) ─────────
            decisions = parse_litellm_response(llm_response)

            # Track response length for diminishing returns
            response_lengths.append(
                sum(len(d.tool or "") + len(d.response or "") for d in decisions)
            )

            # Log first decision (backward compat)
            if decisions:
                first = decisions[0]
                log_decision(logger, first.thought, first.tool or "done", first.confidence)

            # ── Diminishing returns detection ──────────────────────────────
            if (
                len(response_lengths) == DIMINISHING_STEPS
                and all(length < DIMINISHING_THRESHOLD for length in response_lengths)
                and decisions
                and not decisions[0].done
            ):
                logger.warning(
                    f"[CoreAgent] Diminishing returns after {step_num + 1} steps "
                    f"(lengths={list(response_lengths)}). Stopping."
                )
                # decisions[0].response is None when the LLM was mid-action (done=False).
                # Never leak the raw JSON action to the user.
                if decisions[0].response:
                    final_response = decisions[0].response
                else:
                    final_response = (
                        "Could not complete the task after several attempts. "
                        "Try providing more details or rephrasing the request."
                    )
                root_span.set_attribute("stop_reason", "diminishing_returns")
                break

            # ── Done check ────────────────────────────────────────────────────
            if len(decisions) == 1 and decisions[0].done:
                final_response = decisions[0].response or (llm_response.content or "")
                # Guard: if think-tag stripping left an empty response, provide fallback
                if not final_response or not final_response.strip():
                    final_response = (
                        "Processed the request but produced no response. "
                        "Try rephrasing the question."
                    )
                logger.debug(f"[CoreAgent] Task completed in {step_num + 1} step(s).")
                root_span.set_attribute("steps.total", step_num + 1)
                break

            # ── Parallel tool execution ───────────────────────────────────────
            tool_decisions = [d for d in decisions if not d.done and d.tool]
            if not tool_decisions:
                final_response = decisions[0].response or "" if decisions else ""
                break

            results = await self._execute_tool_calls_parallel(
                tool_decisions, state, tracer, root_span
            )

            # Append all tool calls and results to history (OpenAI multi-call format)
            tool_calls_msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": r[0],
                            "arguments": json.dumps(tool_decisions[i].tool_input or {}),
                        },
                    }
                    for i, r in enumerate(results)
                ],
            }
            self._llm.history.append(tool_calls_msg)

            for i, (tool_name, result_str, success) in enumerate(results):
                self._llm.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": f"call_{i}",
                        "content": result_str,
                    }
                )

                # Handle repetitive tool loop detection per tool
                if tool_name == "browser_navigate":
                    _consecutive_browser_nav += 1
                    _consecutive_web_search = 0
                    if _consecutive_browser_nav == _BROWSER_NAV_NUDGE_THRESHOLD:
                        logger.warning(
                            f"[CoreAgent] {_consecutive_browser_nav} consecutive browser_navigate "
                            f"calls — injecting strategy nudge."
                        )
                        self._llm.add_message(
                            "user",
                            "You have been browsing many pages in a row. "
                            "If you already have the data you need, stop browsing and use "
                            "python_repl to compute the answer and provide FINAL ANSWER. "
                            "If you still need data, use web_search to find specific facts faster.",
                        )
                elif tool_name == "web_search":
                    _consecutive_web_search += 1
                    _consecutive_browser_nav = 0
                    if _consecutive_web_search == _WEB_SEARCH_NUDGE_THRESHOLD:
                        logger.warning(
                            f"[CoreAgent] {_consecutive_web_search} consecutive web_search "
                            f"calls — injecting strategy nudge."
                        )
                        self._llm.add_message(
                            "user",
                            "You have run several web searches in a row. "
                            "If the search results are not giving you the structured data you need, "
                            "switch to browser_navigate to visit the full Wikipedia/article page directly, "
                            "or use python_repl to compute the answer with data you already have. "
                            "Do not repeat the same search query.",
                        )
                else:
                    _consecutive_browser_nav = 0
                    _consecutive_web_search = 0

                # Tool RAG hit rate logging
                if self._current_task_filtered_registry:
                    recommended_tools = self._current_task_filtered_registry.names()
                    hit = tool_name in recommended_tools if recommended_tools else False
                    miss_tools = [t for t in recommended_tools if t != tool_name]

                    logger.info(
                        f"[ToolRAG] task={self.user_id} "
                        f"recommended={len(recommended_tools)} "
                        f"used={tool_name} "
                        f"hit={hit} "
                        f"miss_tools={miss_tools}"
                    )

                # Git context refresh after filesystem mutations
                if success and tool_name in _FILESYSTEM_MUTATING_TOOLS and self.inject_git_context:
                    try:
                        self._git_context_cache = await asyncio.wait_for(
                            asyncio.to_thread(_get_git_context), timeout=5.0
                        )
                    except TimeoutError:
                        logger.warning("[CoreAgent] Git context refresh timed out — skipping.")
                        self._git_context_cache = None
                    if self._git_context_cache:
                        self._llm.add_message(
                            "system",
                            f"WORKSPACE STATE UPDATED:\n{self._git_context_cache}",
                        )

                state.record_action(tool_name, tool_decisions[i].tool_input, result_str, success)
                log_step(logger, state, tool_name, result_str, success)

                step_records.append(
                    StepRecord(
                        step=state.step_count,
                        tool=tool_name,
                        tool_input=tool_decisions[i].tool_input or {},
                        result=result_str[:500],
                        success=success,
                        timestamp=datetime.now(UTC).isoformat(),
                    )
                )

            state.step_count += len(results)

            # Inject WorldState snapshot so the LLM has structured context
            self._llm.add_message("system", state.to_context_string())

            # Session memory update (background, non-blocking)
            self._session_memory.record_tool_call()
            if self._session_memory.should_update():
                history_snapshot = list(self._llm.history)
                try:
                    asyncio.create_task(
                        asyncio.to_thread(
                            self._session_memory.update,
                            history_snapshot,
                            self._llm.call_lightweight,
                        )
                    )
                except RuntimeError:
                    # No running event loop (e.g. sync test context) — skip silently
                    pass

            # Update final response and loop success from results
            if results:
                all_success = all(r[2] for r in results)
                final_response = results[-1][1] if results else ""
                if not all_success:
                    loop_success = False

        # Stop the activity summary background task
        _activity_stop.set()
        _activity_task.cancel()

        return final_response, step_records, loop_success

    # ==========================================================================
    # Streaming Entry Point
    # ==========================================================================

    def run_task_stream(self, task: str) -> Generator[str, None, None]:  # type: ignore[type-arg]
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

    def think_with_context(self, messages: list[dict[str, Any]]) -> str:
        return self._llm.think_with_messages(messages)

    def call_lightweight(self, prompt: str) -> str:
        return self._llm.call_lightweight(prompt)

    # ==========================================================================
    # Memory Management (Private)
    # ==========================================================================

    # ==========================================================================
    # LLM Context Builder (shared by run_task and run_task_async)
    # ==========================================================================

    def _build_llm_context(self, task: str, relevant_memories: list[str | dict[str, Any]]) -> None:
        """
        Initialises the LLM history for a new task.

        Uses Tool RAG to inject only the most relevant tools (top-k by TF-IDF
        similarity), then appends git context, current date, memories, and the
        task message.  Called identically from run_task() and run_task_async()
        so both paths always receive the same context.
        """
        filtered_registry = self._llm._registry.select_for_query(task, top_k=self._tool_rag_top_k)
        # Store for hit rate logging in _reasoning_loop
        self._current_task_filtered_registry = filtered_registry
        self._llm._init_history_with_tools(filtered_registry.build_prompt_block())

        # Load user profile and inject display name
        try:
            from src.telegram.db import db_get_profile

            profile = db_get_profile(self.user_id)
            if profile and profile.get("display_name") and profile["display_name"].strip():
                self._llm.add_message(
                    "system",
                    f"USER NAME: The user has previously introduced themselves as "
                    f"'{profile['display_name']}'. Use this name, but if they explicitly "
                    "state a different name in this conversation, use the new one instead.",
                )
        except Exception:
            pass

        if self._git_context_cache:
            self._llm.add_message(
                "system",
                f"CURRENT WORKSPACE STATE:\n{self._git_context_cache}",
            )

        self._llm.add_message(
            "system",
            f"Today's date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        )

        if relevant_memories:
            # Handle both old dict format and new string format from mem0
            memory_lines = []
            for m in relevant_memories:
                if isinstance(m, dict):
                    memory_lines.append(f"- [{m.get('category', 'fact')}] {m.get('content', '')}")
                else:
                    memory_lines.append(f"- [memory] {m}")
            memory_context = "\n".join(memory_lines)
            self._llm.add_message(
                "system",
                f"THINGS YOU KNOW ABOUT THE USER (use when relevant):\n{memory_context}",
            )

        # Inject session working-memory if available (bridges consecutive tasks).
        session_mem = self._session_memory.load()
        if session_mem:
            self._llm.add_message(
                "system",
                f"SESSION WORKING MEMORY (recent task state — use as context):\n{session_mem}",
            )

        if self._injected_history:
            for msg in self._injected_history:
                role = "assistant" if msg.get("role") == "agent" else msg.get("role", "user")
                self._llm.add_message(role, msg["content"])

        self._llm.add_message("user", task)

    def _retrieve_memories(self, task: str) -> list[str | dict[str, Any]]:
        if self.memory_mode == "off":
            return []
        if self.memory_mode == "session":
            return self._retrieve_session_memories(task)
        if self.memory_mode == "persistent":
            if self._argos_memory is None:
                return []
            return self._argos_memory.search(task, top_k=5)
        return []

    def _retrieve_session_memories(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        if not self._session_memories:
            return []
        memories = list(self._session_memories)
        documents = [m["content"] for m in memories]
        scores = _keyword_similarity(query, documents)
        scored = sorted(zip(scores, memories), key=lambda x: x[0], reverse=True)
        return [m for score, m in scored[:top_k] if score > 0.05]

    def _maybe_extract_memories(
        self,
        task: str,
        relevant_memories: list[str | dict[str, Any]],
        task_count: int,
        step_count: int = 0,
        task_success: bool = True,
    ) -> None:
        if self.memory_mode != "persistent" or self._argos_memory is None:
            return
        if not task_success:
            return
        summary_parts = [f"Task: {task}"]
        if relevant_memories:
            summary_parts.append(f"Prior context: {'; '.join(relevant_memories[:3])}")
        summary = " | ".join(summary_parts)
        self._argos_memory.add(summary)

    # ==========================================================================
    # Security Gate (Private)
    # ==========================================================================

    def _authorize_tool(self, spec_or_name: str | ToolSpec, tool_input: dict[str, Any]) -> bool:
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
                    str(spec_or_name),
                    tool_input or {},
                    "denied_auto",
                    "unknown",
                    "not_found",
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
            logger.warning(f"[CoreAgent] Auto-blocked '{spec.name}' (risk={spec.risk})")
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
