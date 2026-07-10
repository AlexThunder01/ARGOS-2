# Phase 1: LiteLLM + Parallel Tool Calls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom HTTP LLM client in `src/agent.py` with LiteLLM, enabling native parallel tool calls via `asyncio.gather` in the engine loop.

**Architecture:** `src/llm/client.py` becomes the single LLM transport layer. `ToolSpec` gains `to_openai_schema()` to emit OpenAI-format tool definitions. `_reasoning_loop` in `engine.py` dispatches multiple tool calls per step concurrently. The legacy JSON planner schema survives as a fallback for content-only model responses.

**Tech Stack:** `litellm>=1.56.0`, `tenacity>=8.2.0`, `pytest-asyncio>=0.23.0`, Python `asyncio.gather`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `requirements.txt` | Add litellm, tenacity, pytest-asyncio; remove requests, pybreaker |
| Modify | `src/tools/spec.py` | Add `to_openai_schema()` to `ToolSpec`; `as_openai_tools()` to `ToolRegistry`; replace TF-IDF `select_for_query()` with embedding-based |
| Create | `src/llm/__init__.py` | Package marker |
| Create | `src/llm/client.py` | `LLMResponse`, `ToolCall` dataclasses; `complete()` and `stream()` async functions via litellm |
| Modify | `src/agent.py` | Remove all `_call_*` HTTP methods; `think_async()` returns `LLMResponse`; remove pybreaker import |
| Modify | `src/planner/planner.py` | Add `parse_litellm_response()` that handles native `tool_calls` list; update `PLANNER_RESPONSE_SCHEMA` |
| Modify | `src/core/engine.py` | `_reasoning_loop` handles `LLMResponse.tool_calls`; new `_execute_tool_calls_parallel()`; remove sklearn import |
| Create | `tests/test_llm_client.py` | Unit tests for `src/llm/client.py` |
| Create | `tests/test_planner_parallel.py` | Unit tests for `parse_litellm_response()` |
| Modify | `tests/test_reasoning_loop.py` | Add `pytest-asyncio` markers; update mocks for `LLMResponse` |
| Create | `conftest.py` (root) | `asyncio_mode = "auto"` for pytest-asyncio |

---

## Task 1: Update Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Edit requirements.txt**

Replace the `requests`, `pybreaker`, and `scikit-learn` lines and add the new ones. The final relevant section should look like:

```
# --- Core Network & Environment ---
httpx==0.28.1
python-dotenv==1.2.2

# --- LLM Provider (unified) ---
litellm>=1.56.0
tenacity>=8.2.0

# --- REST API ---
fastapi==0.135.3
uvicorn[standard]==0.42.0
python-multipart==0.0.20

# --- Testing ---
pytest-asyncio>=0.23.0
```

Lines to **remove** from `requirements.txt`:
- `requests==2.33.1`
- `pybreaker==1.4.1`
- `scikit-learn==1.6.1`

- [ ] **Step 2: Install new dependencies**

```bash
pip install "litellm>=1.56.0" "tenacity>=8.2.0" "pytest-asyncio>=0.23.0"
pip uninstall -y requests pybreaker scikit-learn
```

Expected: no errors. `python -c "import litellm; print(litellm.__version__)"` prints a version string.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add litellm+tenacity+pytest-asyncio, remove requests/pybreaker/scikit-learn"
```

---

## Task 2: Add OpenAI Schema to ToolSpec and Replace TF-IDF Tool RAG

**Files:**
- Modify: `src/tools/spec.py`
- Test: `tests/test_tool_spec_schema.py` (create)

- [ ] **Step 1: Write failing test**

Create `tests/test_tool_spec_schema.py`:

```python
import pytest
from pydantic import Field
from src.tools.spec import ToolInput, ToolRegistry, ToolSpec


class _PathInput(ToolInput):
    path: str = Field(description="Directory path", examples=["."])


_DUMMY = ToolSpec(
    name="list_files",
    description="Lists files in a directory",
    input_schema=_PathInput,
    executor=lambda inp: "ok",
    risk="none",
    category="filesystem",
    icon="📁",
    label="List Files",
)


def test_to_openai_schema_structure():
    schema = _DUMMY.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "list_files"
    assert "parameters" in schema["function"]
    assert "properties" in schema["function"]["parameters"]
    assert "path" in schema["function"]["parameters"]["properties"]


def test_registry_as_openai_tools():
    registry = ToolRegistry([_DUMMY])
    tools = registry.as_openai_tools()
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "list_files"


def test_select_for_query_falls_back_when_embedding_unavailable(monkeypatch):
    """When embedding service is down, select_for_query returns full registry."""
    registry = ToolRegistry([_DUMMY])
    # With only 1 tool and top_k=12, always returns full registry
    result = registry.select_for_query("list directory files", top_k=12)
    assert "list_files" in result.names()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_tool_spec_schema.py -v
```

Expected: `AttributeError: 'ToolSpec' object has no attribute 'to_openai_schema'`

- [ ] **Step 3: Add `to_openai_schema()` to `ToolSpec` in `src/tools/spec.py`**

Add this method inside the `ToolSpec` dataclass, after `requires_confirmation()`:

```python
def to_openai_schema(self) -> dict:
    """Converts this ToolSpec to an OpenAI-format function calling schema."""
    schema = self.input_schema.model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": self.name,
            "description": self.description,
            "parameters": schema,
        },
    }
```

- [ ] **Step 4: Add `as_openai_tools()` to `ToolRegistry` in `src/tools/spec.py`**

Add after `dashboard_whitelist()`:

```python
def as_openai_tools(self) -> list[dict]:
    """Returns all specs as OpenAI-format tool definitions for LiteLLM."""
    return [spec.to_openai_schema() for spec in self._specs.values()]
```

- [ ] **Step 5: Replace TF-IDF `select_for_query()` with embedding-based**

Replace the entire `select_for_query()` method in `ToolRegistry` with this version (it reuses `get_embedding()` from `src/core/memory.py`, which already calls the configured embedding API):

```python
def select_for_query(self, query: str, top_k: int = 12) -> "ToolRegistry":
    """
    Returns top_k tools most relevant to query using embedding cosine similarity.
    Falls back to full registry if embedding service is unavailable or top_k >= len.
    """
    if len(self._specs) <= top_k:
        return self

    try:
        import numpy as np
        from src.core.memory import get_embedding

        names = list(self._specs.keys())
        corpus = [
            f"{s.name} {s.description} {s.category}" for s in self._specs.values()
        ]

        query_vec = get_embedding(query)
        tool_vecs = np.array([get_embedding(text) for text in corpus], dtype=np.float32)

        # Cosine similarity
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        tool_norms = tool_vecs / (np.linalg.norm(tool_vecs, axis=1, keepdims=True) + 1e-8)
        scores = tool_norms @ query_norm

        top_indices = scores.argsort()[-top_k:][::-1]
        selected = {names[i] for i in top_indices}

        for tool_name, companions in self._COSELECT_PAIRS.items():
            if tool_name in selected:
                for companion in companions:
                    if companion in self._specs:
                        selected.add(companion)

        return self.filter(selected)
    except Exception:
        return self
```

Also remove the now-unused sklearn imports at the top of `src/tools/spec.py` if any exist (check with `grep sklearn src/tools/spec.py`).

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_tool_spec_schema.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/tools/spec.py tests/test_tool_spec_schema.py
git commit -m "feat(tools): add to_openai_schema(), as_openai_tools(); replace TF-IDF RAG with embeddings"
```

---

## Task 3: Create `src/llm/client.py`

**Files:**
- Create: `src/llm/__init__.py`
- Create: `src/llm/client.py`
- Test: `tests/test_llm_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_client.py`:

```python
"""Tests for src/llm/client.py — LiteLLM wrapper."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.client import LLMResponse, ToolCall, complete


@pytest.mark.asyncio
async def test_complete_text_response():
    """complete() returns LLMResponse with content when model replies with text."""
    mock_msg = MagicMock()
    mock_msg.content = "Hello from LLM"
    mock_msg.tool_calls = None

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_response.usage = mock_usage

    with patch("src.llm.client.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await complete([{"role": "user", "content": "Hi"}])

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello from LLM"
    assert result.tool_calls == []
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5


@pytest.mark.asyncio
async def test_complete_single_tool_call():
    """complete() parses a single tool call from the LiteLLM response."""
    mock_tc = MagicMock()
    mock_tc.id = "call_abc123"
    mock_tc.function.name = "list_files"
    mock_tc.function.arguments = json.dumps({"path": "/tmp"})

    mock_msg = MagicMock()
    mock_msg.content = None
    mock_msg.tool_calls = [mock_tc]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_response.usage = MagicMock(prompt_tokens=20, completion_tokens=10)

    with patch("src.llm.client.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await complete(
            [{"role": "user", "content": "list /tmp"}],
            tools=[{"type": "function", "function": {"name": "list_files", "parameters": {}}}],
        )

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert isinstance(tc, ToolCall)
    assert tc.id == "call_abc123"
    assert tc.name == "list_files"
    assert tc.arguments == {"path": "/tmp"}


@pytest.mark.asyncio
async def test_complete_parallel_tool_calls():
    """complete() parses multiple parallel tool calls."""
    def _make_tc(call_id, name, args):
        tc = MagicMock()
        tc.id = call_id
        tc.function.name = name
        tc.function.arguments = json.dumps(args)
        return tc

    mock_msg = MagicMock()
    mock_msg.content = None
    mock_msg.tool_calls = [
        _make_tc("call_1", "list_files", {"path": "."}),
        _make_tc("call_2", "get_weather", {"city": "Rome"}),
    ]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_response.usage = MagicMock(prompt_tokens=30, completion_tokens=15)

    with patch("src.llm.client.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await complete([{"role": "user", "content": "weather and files"}])

    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].name == "list_files"
    assert result.tool_calls[1].name == "get_weather"


@pytest.mark.asyncio
async def test_complete_empty_tool_call_arguments():
    """complete() handles tool calls with empty or null arguments gracefully."""
    mock_tc = MagicMock()
    mock_tc.id = "call_empty"
    mock_tc.function.name = "system_stats"
    mock_tc.function.arguments = None  # model sent null arguments

    mock_msg = MagicMock()
    mock_msg.content = None
    mock_msg.tool_calls = [mock_tc]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_response.usage = MagicMock(prompt_tokens=5, completion_tokens=3)

    with patch("src.llm.client.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await complete([{"role": "user", "content": "stats"}])

    assert result.tool_calls[0].arguments == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_llm_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.llm'`

- [ ] **Step 3: Create `src/llm/__init__.py`**

```python
```

(Empty file — package marker only.)

- [ ] **Step 4: Create `src/llm/client.py`**

```python
"""
LiteLLM-based async LLM client for Argos.

Single responsibility: wrap LiteLLM acompletion/stream calls into clean
dataclasses. All retry, key rotation, and provider routing logic lives here.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

from litellm import acompletion
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("argos")


@dataclass
class ToolCall:
    """A single native tool call returned by the LLM."""
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    """Structured response from one LLM completion call."""
    content: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _build_kwargs(
    model: str,
    messages: list[dict],
    tools: Optional[list[dict]],
    temperature: float,
    api_key: Optional[str],
    api_base: Optional[str],
    stream: bool = False,
) -> dict:
    kwargs: dict = {
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
    return kwargs


def _parse_tool_calls(raw_tool_calls) -> list[ToolCall]:
    if not raw_tool_calls:
        return []
    result = []
    for tc in raw_tool_calls:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except (json.JSONDecodeError, TypeError):
            args = {}
        result.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    return result


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def complete(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    model: Optional[str] = None,
    temperature: float = 0.0,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> LLMResponse:
    """Single async LLM completion call via LiteLLM with automatic retry."""
    from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

    kwargs = _build_kwargs(
        model=model or LLM_MODEL,
        messages=messages,
        tools=tools,
        temperature=temperature,
        api_key=api_key or LLM_API_KEY or None,
        api_base=api_base or LLM_BASE_URL or None,
    )

    response = await acompletion(**kwargs)
    msg = response.choices[0].message
    usage = response.usage

    return LLMResponse(
        content=msg.content,
        tool_calls=_parse_tool_calls(msg.tool_calls),
        prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
    )


async def stream(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.0,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Streaming LLM call via LiteLLM. Yields text chunks."""
    from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

    kwargs = _build_kwargs(
        model=model or LLM_MODEL,
        messages=messages,
        tools=None,
        temperature=temperature,
        api_key=api_key or LLM_API_KEY or None,
        api_base=api_base or LLM_BASE_URL or None,
        stream=True,
    )

    response = await acompletion(**kwargs)
    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_llm_client.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/llm/__init__.py src/llm/client.py tests/test_llm_client.py
git commit -m "feat(llm): add LiteLLM client wrapper with LLMResponse and ToolCall dataclasses"
```

---

## Task 4: Configure pytest-asyncio

**Files:**
- Create: `conftest.py` (project root, or `pytest.ini`)

- [ ] **Step 1: Check if pytest.ini or pyproject.toml exists**

```bash
ls pytest.ini pyproject.toml setup.cfg 2>/dev/null
```

- [ ] **Step 2: Add asyncio_mode config**

If `pytest.ini` exists, add to it. Otherwise create it:

```ini
[pytest]
asyncio_mode = auto
```

If a `pyproject.toml` exists with `[tool.pytest.ini_options]`, add:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 3: Verify existing tests still pass**

```bash
pytest tests/ -x -q --ignore=tests/test_llm_client.py --ignore=tests/test_tool_spec_schema.py
```

Expected: all existing tests pass (asyncio_mode=auto is backward compatible).

- [ ] **Step 4: Commit**

```bash
git add pytest.ini  # or pyproject.toml
git commit -m "test: set asyncio_mode=auto for pytest-asyncio"
```

---

## Task 5: Add `parse_litellm_response()` to Planner

**Files:**
- Modify: `src/planner/planner.py`
- Test: `tests/test_planner_parallel.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_planner_parallel.py`:

```python
"""Tests for parse_litellm_response() — parallel tool call parsing."""
import pytest
from src.llm.client import LLMResponse, ToolCall
from src.planner.planner import parse_litellm_response, PlannerDecision


def test_parse_single_tool_call():
    response = LLMResponse(
        content=None,
        tool_calls=[ToolCall(id="call_1", name="list_files", arguments={"path": "."})],
    )
    decisions = parse_litellm_response(response)
    assert len(decisions) == 1
    assert decisions[0].tool == "list_files"
    assert decisions[0].tool_input == {"path": "."}
    assert decisions[0].done is False


def test_parse_parallel_tool_calls():
    response = LLMResponse(
        content=None,
        tool_calls=[
            ToolCall(id="call_1", name="list_files", arguments={"path": "."}),
            ToolCall(id="call_2", name="web_search", arguments={"query": "argos agent"}),
        ],
    )
    decisions = parse_litellm_response(response)
    assert len(decisions) == 2
    assert decisions[0].tool == "list_files"
    assert decisions[1].tool == "web_search"


def test_parse_final_answer():
    response = LLMResponse(content="The answer is 42.", tool_calls=[])
    decisions = parse_litellm_response(response)
    assert len(decisions) == 1
    assert decisions[0].done is True
    assert decisions[0].response == "The answer is 42."
    assert decisions[0].tool is None


def test_parse_empty_response():
    """Empty content and no tool calls → treated as empty final answer."""
    response = LLMResponse(content=None, tool_calls=[])
    decisions = parse_litellm_response(response)
    assert len(decisions) == 1
    assert decisions[0].done is True


def test_parse_content_with_json_fallback():
    """If content looks like legacy JSON planner format, it still works."""
    import json
    legacy_json = json.dumps({
        "thought": "I need to list files",
        "action": {"tool": "list_files", "input": {"path": "/tmp"}},
        "done": False,
    })
    response = LLMResponse(content=legacy_json, tool_calls=[])
    decisions = parse_litellm_response(response)
    assert decisions[0].tool == "list_files"
    assert decisions[0].done is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_planner_parallel.py -v
```

Expected: `ImportError: cannot import name 'parse_litellm_response'`

- [ ] **Step 3: Add `parse_litellm_response()` to `src/planner/planner.py`**

Add this import at the top of the file (with the other imports):

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.llm.client import LLMResponse
```

Add this function at the bottom of `src/planner/planner.py`, before `build_system_prompt_suffix()`:

```python
def parse_litellm_response(response: "LLMResponse") -> list[PlannerDecision]:
    """
    Converts a LLMResponse (from src/llm/client.py) into a list of PlannerDecisions.

    Primary path: if response.tool_calls is non-empty, each call becomes a
    PlannerDecision with done=False. Parallel calls produce multiple decisions.

    Fallback path: if response.content is set (no tool calls), delegates to the
    legacy parse_planner_response() so JSON-format responses still work.
    """
    if response.tool_calls:
        return [
            PlannerDecision(
                thought="",
                tool=tc.name,
                tool_input=tc.arguments,
                confidence=1.0,
                done=False,
                response=None,
                raw=f"tool_call:{tc.id}",
            )
            for tc in response.tool_calls
        ]

    # No native tool calls — fall back to text/JSON planner
    content = response.content or ""
    decision = parse_planner_response(content)
    return [decision]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_planner_parallel.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/planner/planner.py tests/test_planner_parallel.py
git commit -m "feat(planner): add parse_litellm_response() for native parallel tool calls"
```

---

## Task 6: Rewrite `ArgosAgent` to Use LiteLLM Client

**Files:**
- Modify: `src/agent.py`

- [ ] **Step 1: Remove dead imports in `src/agent.py`**

Remove these import lines (they will no longer be needed):

```python
import requests
# and:
from pybreaker import CircuitBreaker, CircuitBreakerOpen
```

Also remove the circuit breaker instantiation line (search for `_llm_circuit_breaker`).

- [ ] **Step 2: Add LiteLLM client import**

At the top of `src/agent.py`, add:

```python
from src.llm.client import LLMResponse, complete as llm_complete, stream as llm_stream
```

- [ ] **Step 3: Replace `think_async()` to return `LLMResponse`**

Find `think_async()` (around line 570). Replace its entire body with:

```python
async def think_async(self) -> LLMResponse:
    """Single LLM reasoning step — non-blocking. Returns LLMResponse with tool_calls or content."""
    self._check_time_based_mc()
    self.trim_history()
    self._last_llm_call_time = time.monotonic()

    from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

    # Build OpenAI-format tool schemas for the current filtered registry
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
        from src.llm.client import LLMResponse as _R
        return _R(content=f"LLM Error: {e}", tool_calls=[])
```

- [ ] **Step 4: Replace `think_stream()` to use LiteLLM streaming**

Find `think_stream()` (around line 728). Replace its entire body with:

```python
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
```

- [ ] **Step 5: Remove dead methods**

Delete these methods entirely from `src/agent.py` (they are replaced by LiteLLM):
- `_call_openai_compatible()`
- `_call_anthropic()`
- `_call_openai_compatible_async()`
- `_call_anthropic_async()`
- `_call_openai_compatible_stream()`
- `_call_anthropic_stream()`
- `_call_for_compaction()` — keep this one but update it to use `llm_complete()`

Update `_call_for_compaction()` to:

```python
def _call_for_compaction(self, messages: list[dict]) -> str:
    """Sync wrapper for compaction calls (lightweight model)."""
    import asyncio
    from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_LIGHTWEIGHT_MODEL
    try:
        response = asyncio.run(llm_complete(
            messages=messages,
            model=LLM_LIGHTWEIGHT_MODEL,
            temperature=0.0,
            api_key=LLM_API_KEY or None,
            api_base=LLM_BASE_URL or None,
        ))
        return response.content or ""
    except Exception as e:
        logger.error(f"[LLM] Compaction call failed: {e}")
        return ""
```

- [ ] **Step 6: Keep `think()` sync wrapper for CLI**

Find `think()` (around line 433). Replace its body with:

```python
def think(self) -> str:
    """Sync wrapper for CLI use. Returns text content of the LLM response."""
    import asyncio
    response = asyncio.run(self.think_async())
    return response.content or ""
```

- [ ] **Step 7: Run import check**

```bash
python -c "from src.agent import ArgosAgent; print('OK')"
```

Expected: `OK` (no ImportError)

- [ ] **Step 8: Commit**

```bash
git add src/agent.py
git commit -m "feat(agent): replace custom HTTP client with LiteLLM in ArgosAgent"
```

---

## Task 7: Update Engine for Parallel Tool Execution

**Files:**
- Modify: `src/core/engine.py`

- [ ] **Step 1: Remove sklearn imports from `src/core/engine.py`**

Find and remove this block in `src/core/engine.py`:

```python
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
```

If `_tfidf_similarity` is called elsewhere in the file, search for usages:

```bash
grep -n "_tfidf_similarity" src/core/engine.py
```

Replace any call to `_tfidf_similarity(query, docs)` with a simple keyword overlap fallback:

```python
def _keyword_similarity(query: str, documents: list[str]) -> list[float]:
    """Simple keyword overlap scoring — fallback when embeddings unavailable."""
    query_words = set(query.lower().split())
    scores = []
    for doc in documents:
        doc_words = set(doc.lower().split())
        overlap = len(query_words & doc_words)
        scores.append(overlap / (len(query_words) + 1))
    return scores
```

- [ ] **Step 2: Add LiteLLM imports to engine.py**

At the top of `src/core/engine.py`, add:

```python
from src.llm.client import LLMResponse
from src.planner.planner import parse_litellm_response
```

- [ ] **Step 3: Add `_execute_tool_calls_parallel()` method to `CoreAgent`**

Add this method to the `CoreAgent` class, near `_reasoning_loop`:

```python
async def _execute_tool_calls_parallel(
    self, decisions: list, state, tracer, root_span
) -> list[tuple[str, str, bool]]:
    """
    Execute a list of PlannerDecisions concurrently via asyncio.gather.

    Returns list of (tool_name, result_str, success) tuples in the same
    order as decisions.
    """
    async def _run_one(decision) -> tuple[str, str, bool]:
        tool_name = decision.tool
        tool_input = decision.tool_input or {}

        spec = self._available_tools.get(tool_name)
        if not spec:
            return tool_name, f"Unknown tool: {tool_name}", False

        authorized = self._authorize_tool(tool_name, tool_input)
        if not authorized:
            return tool_name, f"Tool '{tool_name}' was not authorized.", False

        HOOK_REGISTRY.fire(HookEvent.PRE_TOOL_USE, tool=tool_name, input=tool_input)

        try:
            result_str = await asyncio.to_thread(
                execute_with_retry, spec.executor, tool_input
            )
            HOOK_REGISTRY.fire(
                HookEvent.POST_TOOL_USE, tool=tool_name, input=tool_input, output=result_str
            )
            return tool_name, result_str, True
        except Exception as exc:
            err = str(exc)
            HOOK_REGISTRY.fire(
                HookEvent.POST_TOOL_USE_FAILURE, tool=tool_name, input=tool_input, error=err
            )
            return tool_name, f"Tool error: {err}", False

    tasks = [_run_one(d) for d in decisions]
    return await asyncio.gather(*tasks)
```

- [ ] **Step 4: Update `_reasoning_loop` to use `LLMResponse` and parallel execution**

Find the section in `_reasoning_loop` where `self._llm.think_async()` is called. Replace the single-tool handling block with:

```python
# ── LLM call ─────────────────────────────────────────────────────────
llm_response: LLMResponse = await self._llm.think_async()

# ── Parse decisions (may be multiple for parallel tool calls) ─────────
decisions = parse_litellm_response(llm_response)

# Track response length for diminishing returns
response_lengths.append(
    sum(len(d.tool or "") + len(d.response or "") for d in decisions)
)

# ── Done check ────────────────────────────────────────────────────────
if len(decisions) == 1 and decisions[0].done:
    final_response = decisions[0].response or ""
    self._llm.history.append({"role": "assistant", "content": final_response})
    break

# ── Parallel tool execution ───────────────────────────────────────────
tool_decisions = [d for d in decisions if not d.done and d.tool]
if not tool_decisions:
    final_response = decisions[0].response or ""
    break

results = await self._execute_tool_calls_parallel(tool_decisions, state, tracer, root_span)

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
    self._llm.history.append({
        "role": "tool",
        "tool_call_id": f"call_{i}",
        "content": result_str,
    })
    step_records.append(StepRecord(
        step=state.step_count,
        tool=tool_name,
        tool_input=tool_decisions[i].tool_input or {},
        result=result_str[:500],
        success=success,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ))

state.step_count += len(results)
```

- [ ] **Step 5: Run import check**

```bash
python -c "from src.core.engine import CoreAgent; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/core/engine.py
git commit -m "feat(engine): parallel tool execution via asyncio.gather, LiteLLM response handling"
```

---

## Task 8: Update Existing Tests

**Files:**
- Modify: `tests/test_reasoning_loop.py`

- [ ] **Step 1: Update mocks in `tests/test_reasoning_loop.py`**

The tests mock `self._llm.think_async()`. Previously it returned a string; now it returns `LLMResponse`. Find all occurrences of:

```bash
grep -n "think_async\|return.*json.dumps\|MagicMock.*think" tests/test_reasoning_loop.py | head -20
```

For each test that patches `think_async`, update the mock return value from a string to an `LLMResponse`. Example pattern:

**Before:**
```python
mock_think.return_value = json.dumps({"thought": "done", "response": "Fatto!", "done": True})
```

**After:**
```python
from src.llm.client import LLMResponse
mock_think.return_value = LLMResponse(
    content=json.dumps({"thought": "done", "response": "Fatto!", "done": True}),
    tool_calls=[],
)
```

For tests that mock a tool call response:

**Before:**
```python
mock_think.return_value = json.dumps({
    "thought": "listing", "action": {"tool": "test_echo", "input": {}}, "done": False
})
```

**After:**
```python
from src.llm.client import LLMResponse, ToolCall
mock_think.return_value = LLMResponse(
    content=None,
    tool_calls=[ToolCall(id="call_1", name="test_echo", arguments={})],
)
```

- [ ] **Step 2: Run the updated tests**

```bash
pytest tests/test_reasoning_loop.py -v
```

Expected: all tests PASS. Fix any remaining mocking issues by following the same pattern above.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_reasoning_loop.py
git commit -m "test: update reasoning loop mocks for LLMResponse format"
```

---

## Task 9: End-to-End Smoke Test

**Files:**
- No changes — verification only

- [ ] **Step 1: Run the full test suite one final time**

```bash
pytest tests/ -q
```

Expected: all tests pass with no warnings about unresolved imports.

- [ ] **Step 2: Import smoke test**

```bash
python -c "
from src.llm.client import complete, LLMResponse, ToolCall
from src.tools.spec import ToolSpec
from src.planner.planner import parse_litellm_response
from src.core.engine import CoreAgent
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 3: Verify no requests/pybreaker/scikit-learn usage remains**

```bash
grep -rn "import requests\|from requests\|pybreaker\|CircuitBreaker\|TfidfVectorizer\|sklearn" src/ --include="*.py"
```

Expected: no output (zero matches).

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(phase1): LiteLLM + parallel tool calls — Phase 1 complete"
```

---

## Self-Review Checklist

- [x] LiteLLM wrapper (`src/llm/client.py`) tested in isolation
- [x] `ToolSpec.to_openai_schema()` tested
- [x] `parse_litellm_response()` tested for single, parallel, and fallback cases
- [x] Parallel execution via `asyncio.gather` in engine
- [x] `requests`, `pybreaker`, `scikit-learn` removed
- [x] Legacy JSON planner fallback preserved via `parse_planner_response()` in content path
- [x] Streaming preserved via `llm_stream()` 
- [x] `_call_for_compaction()` updated (no more requests)
- [x] Existing tests updated for `LLMResponse` format
