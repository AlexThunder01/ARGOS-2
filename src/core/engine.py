"""
ARGOS-2 Core — Unified Cognitive Engine.

CoreAgent is the single brain shared by all interfaces (CLI, API, Telegram).
It orchestrates: LLM reasoning → Planning → Tool execution → Memory → Security.

Usage:
    from src.core import CoreAgent

    agent = CoreAgent(memory_mode="persistent", user_id=12345)
    result = agent.run_task("List files in the current directory")
"""

import hashlib
import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional, Set

from src.agent import ArgosAgent
from src.core.memory import EXTRACT_MIN_LENGTH
from src.executor.executor import execute_with_retry
from src.logging.otel import get_tracer
from src.logging.tracer import log_decision, log_step
from src.planner.planner import parse_planner_response
from src.tools import TOOLS
from src.world_model.state import WorldState

logger = logging.getLogger("argos")


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
    """

    def __init__(
        self,
        memory_mode: str = "off",
        user_id: Optional[int] = None,
        max_steps: int = 10,
        require_confirmation: bool = False,
        confirmation_callback: Optional[Callable] = None,
        allowed_tools: Optional[Set[str]] = None,
    ):
        if memory_mode not in MEMORY_MODES:
            raise ValueError(
                f"Invalid memory_mode '{memory_mode}'. Must be one of {MEMORY_MODES}"
            )

        self.memory_mode = memory_mode
        self.max_steps = max_steps
        self.require_confirmation = require_confirmation
        self.confirmation_callback = confirmation_callback

        # Tool filtering: when set, only these tools are exposed to the LLM
        if allowed_tools is not None:
            self._available_tools = {k: v for k, v in TOOLS.items() if k in allowed_tools}
        else:
            self._available_tools = TOOLS

        # Resolve user ID
        if user_id is not None:
            self.user_id = user_id
        else:
            linux_user = os.environ.get("USER", "argos")
            self.user_id = int(
                hashlib.sha256(linux_user.encode()).hexdigest()[:16], 16
            ) % (2**31)

        # LLM provider (wraps Groq/OpenAI/Anthropic)
        self._llm = ArgosAgent()

        # Session memory (RAM-only, cleared on exit). Bounded to prevent OOM on long sessions.
        self._session_memories: deque[dict] = deque(maxlen=500)

        # Dangerous tools that require confirmation
        self._dangerous_tools = {
            "create_file",
            "modify_file",
            "rename_file",
            "create_directory",
            "delete_directory",
            "delete_file",
            "read_file",
            "visual_click",
            "keyboard_type",
            "launch_app",
            "python_repl",
            "bash_exec",
            "read_pdf",
        }

        logger.info(
            f"[CoreAgent] Initialized | memory={memory_mode} | "
            f"user_id={self.user_id} | backend={self._llm.backend} | "
            f"model={self._llm.model} | tools={len(self._available_tools)}/{len(TOOLS)}"
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
        1. Retrieve relevant memories (if enabled)
        2. LLM reasoning loop (think → plan → execute → observe)
        3. Extract new memories (if enabled)

        Returns a TaskResult with the final response and execution history.
        """
        tracer = get_tracer()

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

            # --- Phase 1: Memory Retrieval ---
            with tracer.start_as_current_span("core.retrieve_memories") as mem_span:
                relevant_memories = self._retrieve_memories(task)
                mem_span.set_attribute("memories.count", len(relevant_memories))

            # --- Phase 2: Build context and initialize LLM history ---
            self._llm._init_history()

            # Inject memories into context if available
            if relevant_memories:
                memory_context = "\n".join(
                    f"- [{m['category']}] {m['content']}" for m in relevant_memories
                )
                self._llm.add_message(
                    "system",
                    f"THINGS YOU KNOW ABOUT THE USER (use when relevant):\n{memory_context}",
                )

            self._llm.add_message("user", task)

            # --- Phase 3: Reasoning Loop ---
            step_records = []
            final_response = ""

            for step_num in range(self.max_steps):
                raw = self._llm.think()
                decision = parse_planner_response(raw)
                log_decision(
                    logger,
                    decision.thought,
                    decision.tool or "done",
                    decision.confidence,
                )

                # Agent decided it's done
                if decision.done:
                    final_response = decision.response or raw
                    logger.info(
                        f"[CoreAgent] Task completed in {step_num + 1} step(s)."
                    )
                    root_span.set_attribute("steps.total", step_num + 1)
                    break

                tool_name = decision.tool
                tool_input = decision.tool_input

                # Unknown tool or not allowed
                if not tool_name or tool_name not in self._available_tools:
                    final_response = f"Unknown or restricted tool: '{tool_name}'"
                    logger.error(f"[CoreAgent] {final_response}")
                    break

                # --- Security Gate ---
                if not self._authorize_tool(tool_name, tool_input):
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
                        json.dumps(
                            {"action": {"tool": tool_name, "input": tool_input}}
                        ),
                    )
                    self._llm.add_message("user", "ACTION DENIED BY USER. STOP.")
                    break

                # --- Execute Tool (with OTel span) ---
                with tracer.start_as_current_span(
                    "core.tool_execution",
                    attributes={"tool.name": tool_name, "tool.step": step_num + 1},
                ) as tool_span:
                    action_result = execute_with_retry(
                        self._available_tools[tool_name], tool_input, tool_name
                    )
                    tool_span.set_attribute("tool.success", action_result.success)
                    tool_span.set_attribute(
                        "tool.result_preview", action_result.message[:200]
                    )

                state.record_action(
                    tool_name, tool_input, action_result.message, action_result.success
                )
                log_step(
                    logger,
                    state,
                    tool_name,
                    action_result.message,
                    action_result.success,
                )

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

                # Feed result back to LLM
                self._llm.add_message(
                    "assistant",
                    json.dumps({"action": {"tool": tool_name, "input": tool_input}}),
                )
                self._llm.add_message("user", f"TOOL RESULT: {action_result.message}")

                if action_result.success:
                    final_response = action_result.message
                else:
                    final_response = f"Step failure: {action_result.message}"

            # --- Phase 4: Memory Extraction (post-task) ---
            if self.memory_mode != "off" and final_response:
                with tracer.start_as_current_span("core.extract_memories"):
                    self._maybe_extract_memories(task, relevant_memories)

            root_span.set_attribute(
                "result.success",
                not final_response.startswith(
                    ("Step failure", "Unknown tool", "Action")
                ),
            )

            return TaskResult(
                success=not final_response.startswith(
                    ("Step failure", "Unknown tool", "Action")
                ),
                task=task,
                response=final_response,
                steps_executed=state.step_count,
                history=step_records,
                memories_used=len(relevant_memories),
            )

    # ==========================================================================
    # Telegram-Specific Entry Point
    # ==========================================================================

    def think_with_context(self, messages: list[dict]) -> str:
        """
        Executes a single LLM inference with an externally-provided message history.
        Used by the Telegram chat module where each user has their own sliding-window context.
        """
        return self._llm.think_with_messages(messages)

    def call_lightweight(self, prompt: str) -> str:
        """Calls a lightweight model for structured extraction tasks."""
        return self._llm.call_lightweight(prompt)

    # ==========================================================================
    # Memory Management (Private)
    # ==========================================================================

    def _retrieve_memories(self, query: str) -> list[dict]:
        """Retrieves relevant memories based on the current memory mode."""
        if self.memory_mode == "off":
            return []

        if self.memory_mode == "session":
            # Simple keyword matching for session memories (no embeddings needed)
            query_lower = query.lower()
            return [
                m
                for m in self._session_memories
                if any(
                    word in m["content"].lower()
                    for word in query_lower.split()
                    if len(word) > 3
                )
            ][:3]

        if self.memory_mode == "persistent":
            try:
                from src.core.memory import retrieve_relevant_memories

                return retrieve_relevant_memories(self.user_id, query, top_k=6)
            except Exception as e:
                logger.warning(f"[CoreAgent] Memory retrieval failed: {e}")
                return []

        return []

    def _maybe_extract_memories(self, user_message: str, existing_memories: list[dict]):
        """Extracts and stores new memories from the conversation if conditions are met."""
        if self.memory_mode == "session":
            # For session mode, just store raw facts in RAM
            if len(user_message) > EXTRACT_MIN_LENGTH:
                self._session_memories.append(
                    {
                        "content": user_message[:200],
                        "category": "fact",
                    }
                )
            return

        if self.memory_mode == "persistent":
            try:
                from src.core.memory import (
                    extract_memories_from_text,
                    save_extracted_memories,
                    should_extract_memory,
                )

                # Use a simple heuristic: extract every time for CLI (no msg_count tracking)
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

    def _authorize_tool(self, tool_name: str, tool_input: dict) -> bool:
        """
        Checks if a tool execution should proceed.
        - API mode: auto-blocks if require_confirmation is True
        - CLI mode: calls the confirmation_callback for user approval
        """
        if tool_name not in self._dangerous_tools:
            return True  # Safe tools always allowed

        # API mode: auto-block dangerous tools when flag is set
        if self.require_confirmation:
            logger.warning(
                f"[CoreAgent] Auto-blocked '{tool_name}' (require_confirmation=True)"
            )
            return False

        # CLI mode: ask the user
        if self.confirmation_callback:
            return self.confirmation_callback(tool_name, tool_input)

        # Default: allow (no restrictions configured)
        return True
