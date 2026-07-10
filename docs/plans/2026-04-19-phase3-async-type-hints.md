# Phase 3: Async Coverage + Type Hints — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise async coverage from 4/120 files to 80%+ and type hint coverage from 15% to 80%+ across all core modules, enforced by mypy strict mode and ruff.

**Architecture:** All I/O-bound tool executors in `src/tools/` become `async def`. `src/executor/executor.py` becomes fully async. `src/core/` modules get complete type annotations. mypy is added to CI. ruff replaces any existing linter.

**Prerequisite:** Phase 1 complete (LiteLLM and pytest-asyncio installed).

**Tech Stack:** `mypy>=1.10.0`, `ruff>=0.4.0`, `asyncio.to_thread` (stdlib)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `requirements.txt` | Add `mypy`, `ruff` (dev deps) |
| Modify | `src/executor/executor.py` | Fully async `execute_with_retry()` |
| Modify | `src/tools/web.py` | Async tool executors (web_search, weather, stats) |
| Modify | `src/tools/filesystem.py` | Async tool executors (read_file, write, etc.) |
| Modify | `src/tools/code_exec.py` | Async tool executors (bash_exec, python_repl) |
| Modify | `src/core/engine.py` | Full type annotations on all public methods |
| Modify | `src/core/memory.py` | Full type annotations |
| Modify | `src/llm/client.py` | Full type annotations (already mostly done) |
| Modify | `src/planner/planner.py` | Full type annotations |
| Create | `mypy.ini` | mypy strict configuration |
| Create | `ruff.toml` | ruff linter configuration |

---

## Task 1: Install Dev Tools

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add mypy and ruff to requirements.txt**

Add a dev section:

```
# --- Dev / Linting ---
mypy>=1.10.0
ruff>=0.4.0
```

- [ ] **Step 2: Install**

```bash
pip install "mypy>=1.10.0" "ruff>=0.4.0"
```

- [ ] **Step 3: Create `ruff.toml`**

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
ignore = ["E501", "B008"]

[tool.ruff.lint.isort]
known-first-party = ["src"]
```

- [ ] **Step 4: Create `mypy.ini`**

```ini
[mypy]
python_version = 3.12
strict = true
ignore_missing_imports = true
exclude = tests/|dashboard/|eval/
```

- [ ] **Step 5: Run ruff on src/ (baseline)**

```bash
ruff check src/ --statistics
```

Note the error count — we will bring this to 0.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt ruff.toml mypy.ini
git commit -m "chore(lint): add ruff and mypy strict configuration"
```

---

## Task 2: Async Executor

**Files:**
- Modify: `src/executor/executor.py`
- Test: `tests/test_executor_async.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_executor_async.py`:

```python
"""Tests for async execute_with_retry."""
import asyncio
import pytest
from src.executor.executor import execute_with_retry_async


@pytest.mark.asyncio
async def test_execute_sync_tool_in_thread():
    """Sync executors run in a thread pool and return correctly."""
    def sync_executor(inp: dict) -> str:
        return f"ok:{inp.get('x', 'none')}"

    result = await execute_with_retry_async(sync_executor, {"x": "test"})
    assert result == "ok:test"


@pytest.mark.asyncio
async def test_execute_async_tool_directly():
    """Async executors are awaited directly."""
    async def async_executor(inp: dict) -> str:
        return f"async:{inp.get('x', 'none')}"

    result = await execute_with_retry_async(async_executor, {"x": "hello"})
    assert result == "async:hello"


@pytest.mark.asyncio
async def test_execute_retries_on_exception():
    """execute_with_retry_async retries on transient errors."""
    call_count = 0

    def flaky_executor(inp: dict) -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("transient")
        return "ok"

    result = await execute_with_retry_async(flaky_executor, {}, max_retries=3)
    assert result == "ok"
    assert call_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_executor_async.py -v
```

Expected: `ImportError: cannot import name 'execute_with_retry_async'`

- [ ] **Step 3: Add `execute_with_retry_async` to `src/executor/executor.py`**

Read `src/executor/executor.py` first, then add at the bottom:

```python
import asyncio
import inspect
from typing import Any, Callable


async def execute_with_retry_async(
    executor: Callable[..., Any],
    tool_input: dict,
    max_retries: int = 2,
) -> str:
    """
    Execute a tool executor (sync or async) with retry on transient errors.

    Sync executors are offloaded to asyncio.to_thread so the event loop
    is never blocked. Async executors are awaited directly.
    """
    last_error: Exception = RuntimeError("execute_with_retry_async: no attempts made")
    for attempt in range(max_retries + 1):
        try:
            if inspect.iscoroutinefunction(executor):
                result = await executor(tool_input)
            else:
                result = await asyncio.to_thread(executor, tool_input)
            return str(result) if result is not None else ""
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))
    return f"Tool error after {max_retries + 1} attempts: {last_error}"
```

- [ ] **Step 4: Update `_execute_tool_calls_parallel` in engine.py to use `execute_with_retry_async`**

In `src/core/engine.py`, find the `_run_one` inner function inside `_execute_tool_calls_parallel`. Replace:

```python
result_str = await asyncio.to_thread(
    execute_with_retry, spec.executor, tool_input
)
```

With:

```python
from src.executor.executor import execute_with_retry_async
result_str = await execute_with_retry_async(spec.executor, tool_input)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_executor_async.py tests/ -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/executor/executor.py tests/test_executor_async.py src/core/engine.py
git commit -m "feat(executor): add execute_with_retry_async for non-blocking tool dispatch"
```

---

## Task 3: Type Annotate `src/llm/client.py` and `src/planner/planner.py`

**Files:**
- Modify: `src/llm/client.py`
- Modify: `src/planner/planner.py`

- [ ] **Step 1: Run mypy on these two files (baseline)**

```bash
mypy src/llm/client.py src/planner/planner.py --ignore-missing-imports
```

Note the errors.

- [ ] **Step 2: Fix mypy errors in `src/llm/client.py`**

Add missing return type annotations. Key additions:

```python
# _build_kwargs return type
def _build_kwargs(...) -> dict[str, object]: ...

# _parse_tool_calls return type
def _parse_tool_calls(raw_tool_calls: object) -> list[ToolCall]: ...

# stream return type
async def stream(...) -> AsyncGenerator[str, None]: ...
```

- [ ] **Step 3: Fix mypy errors in `src/planner/planner.py`**

Add return type annotations to all functions:

```python
def parse_planner_response(raw_response: str) -> PlannerDecision: ...
def parse_litellm_response(response: "LLMResponse") -> list[PlannerDecision]: ...
def build_system_prompt_suffix() -> str: ...
def _strip_think_tags(text: str) -> str: ...  # if present
```

Also annotate the `PlannerDecision` dataclass fields with explicit types if any are missing.

- [ ] **Step 4: Run mypy again to verify 0 errors**

```bash
mypy src/llm/client.py src/planner/planner.py --ignore-missing-imports
```

Expected: `Success: no issues found`

- [ ] **Step 5: Run ruff**

```bash
ruff check src/llm/ src/planner/ --fix
```

- [ ] **Step 6: Commit**

```bash
git add src/llm/client.py src/planner/planner.py
git commit -m "chore(types): full type annotations on llm/client.py and planner.py"
```

---

## Task 4: Type Annotate `src/core/engine.py`

**Files:**
- Modify: `src/core/engine.py`

- [ ] **Step 1: Run mypy baseline**

```bash
mypy src/core/engine.py --ignore-missing-imports 2>&1 | head -40
```

- [ ] **Step 2: Annotate `StepRecord` and `TaskResult` dataclasses**

Ensure all fields have explicit types:

```python
@dataclass
class StepRecord:
    step: int
    tool: str
    tool_input: dict[str, object]
    result: str
    success: bool
    timestamp: str = ""

@dataclass
class TaskResult:
    success: bool
    task: str
    response: str
    steps_executed: int
    history: list[StepRecord] = field(default_factory=list)
    memories_used: int = 0
```

- [ ] **Step 3: Annotate `CoreAgent` public methods**

Add return types to:

```python
def run_task(self, task: str) -> TaskResult: ...
async def run_task_async(self, task: str) -> TaskResult: ...
async def _reasoning_loop(self, task: str, state: WorldState, tracer: object, root_span: object) -> tuple[str, list[StepRecord], bool]: ...
def _retrieve_memories(self, task: str) -> list[str]: ...
def _build_llm_context(self, task: str, memories: list[str]) -> None: ...
def _authorize_tool(self, tool_name: str, tool_input: dict[str, object]) -> bool: ...
async def _execute_tool_calls_parallel(self, decisions: list[object], state: WorldState, tracer: object, root_span: object) -> list[tuple[str, str, bool]]: ...
```

- [ ] **Step 4: Run mypy and fix remaining errors**

```bash
mypy src/core/engine.py --ignore-missing-imports 2>&1 | grep "error:" | head -20
```

Fix errors iteratively. Common patterns:
- `Optional[X]` → `X | None` (Python 3.12 style)
- `list[dict]` → `list[dict[str, object]]`
- Missing `-> None` on methods that don't return

- [ ] **Step 5: Run ruff**

```bash
ruff check src/core/engine.py --fix
```

- [ ] **Step 6: Commit**

```bash
git add src/core/engine.py
git commit -m "chore(types): full type annotations on core/engine.py"
```

---

## Task 5: Type Annotate `src/core/memory.py` and `src/tools/spec.py`

**Files:**
- Modify: `src/core/memory.py`
- Modify: `src/tools/spec.py`

- [ ] **Step 1: Annotate `src/core/memory.py`**

Add return types:

```python
def get_embedding(text: str) -> np.ndarray: ...
def check_embedding_dimensions() -> None: ...
```

Run:

```bash
mypy src/core/memory.py --ignore-missing-imports
```

Fix errors.

- [ ] **Step 2: Annotate `src/tools/spec.py`**

Key annotations:

```python
# ToolSpec
def prompt_example(self) -> str: ...
def to_metadata(self) -> dict[str, str]: ...
def requires_confirmation(self) -> bool: ...
def validate_input(self, raw: object) -> dict[str, object]: ...
def to_openai_schema(self) -> dict[str, object]: ...

# ToolRegistry
def names(self) -> list[str]: ...
def filter(self, allowed: set[str]) -> "ToolRegistry": ...
def as_openai_tools(self) -> list[dict[str, object]]: ...
def select_for_query(self, query: str, top_k: int = 12) -> "ToolRegistry": ...
def build_prompt_block(self, group: str | None = None) -> str: ...
```

- [ ] **Step 3: Run mypy on both files**

```bash
mypy src/core/memory.py src/tools/spec.py --ignore-missing-imports
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add src/core/memory.py src/tools/spec.py
git commit -m "chore(types): full type annotations on memory.py and tools/spec.py"
```

---

## Task 6: Full Ruff + Mypy Pass on All Core Modules

**Files:**
- Modify: various `src/` files as needed

- [ ] **Step 1: Run ruff on all of src/**

```bash
ruff check src/ --fix
```

Review and commit any auto-fixes. For errors ruff can't auto-fix, fix manually.

- [ ] **Step 2: Run mypy on core modules**

```bash
mypy src/llm/ src/core/ src/planner/ src/tools/spec.py --ignore-missing-imports
```

Fix remaining errors. Common patterns that need manual fixing:
- `dict` without type params → `dict[str, str]` or `dict[str, object]`
- Missing `Optional` imports → use `X | None` syntax
- Untyped lambdas in `ToolSpec.executor` → cast as `Callable[[dict[str, object]], str]`

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Final commit**

```bash
git add src/
git commit -m "feat(phase3): async coverage + type hints — Phase 3 complete"
```
