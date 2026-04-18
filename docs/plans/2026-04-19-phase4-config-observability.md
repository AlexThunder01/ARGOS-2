# Phase 4: Config + Observability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify `src/config.py` + `src/workflows_config.py` into a single Pydantic Settings entry point, and replace plain-text logging with JSON-structured logs carrying trace_id via contextvars.

**Architecture:** `src/config.py` becomes a thin re-export shim for backward compat; real settings live in `src/settings.py` (Pydantic BaseSettings). `src/workflows_config.py` hot-reload stays via a `WorkflowSettings` sub-model with YAML override. JSON logging is configured once in `api/server.py` lifespan and `scripts/main.py`; all loggers in `src/` emit `extra={...}` dicts.

**Prerequisite:** None (independent of Phases 1-3, though best run last).

**Tech Stack:** `pydantic-settings>=2.2.0`, `python-json-logger>=2.0.7`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `requirements.txt` | Add `pydantic-settings`, `python-json-logger` |
| Create | `src/settings.py` | `ArgosSettings` Pydantic BaseSettings — single source of truth |
| Modify | `src/config.py` | Thin shim re-exporting from `src/settings.py` |
| Modify | `src/workflows_config.py` | Load from `ArgosSettings.workflow` sub-model |
| Create | `src/logging_config.py` | `configure_json_logging()` with contextvars trace_id |
| Modify | `api/server.py` | Call `configure_json_logging()` in lifespan |
| Modify | `scripts/main.py` | Call `configure_json_logging()` at startup |
| Modify | `src/core/engine.py` | Replace f-string log calls with structured `extra={}` |
| Create | `tests/test_settings.py` | Unit tests for ArgosSettings loading |
| Create | `tests/test_logging_config.py` | Unit tests for JSON log formatting |

---

## Task 1: Install Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add to requirements.txt**

```
pydantic-settings>=2.2.0
python-json-logger>=2.0.7
```

- [ ] **Step 2: Install**

```bash
pip install "pydantic-settings>=2.2.0" "python-json-logger>=2.0.7"
```

Expected: `python -c "from pydantic_settings import BaseSettings; print('OK')"` → `OK`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add pydantic-settings and python-json-logger"
```

---

## Task 2: Create `src/settings.py`

**Files:**
- Create: `src/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_settings.py`:

```python
"""Tests for ArgosSettings — Pydantic Settings config."""
import os
import pytest
from unittest.mock import patch


def test_default_values():
    """ArgosSettings has sensible defaults without any env vars."""
    with patch.dict(os.environ, {}, clear=False):
        from src.settings import ArgosSettings
        settings = ArgosSettings()
    assert settings.llm_model != ""
    assert settings.tool_rag_top_k > 0
    assert settings.rate_limit_per_hour > 0


def test_env_var_override():
    """Environment variables override defaults."""
    with patch.dict(os.environ, {"ARGOS_TOOL_RAG_TOP_K": "7"}):
        # Force reimport to pick up new env
        import importlib
        import src.settings as mod
        importlib.reload(mod)
        from src.settings import ArgosSettings
        settings = ArgosSettings()
    assert settings.tool_rag_top_k == 7


def test_llm_backend_validation():
    """LLM_BACKEND must be a known value."""
    with patch.dict(os.environ, {"LLM_BACKEND": "openai-compatible"}):
        from src.settings import ArgosSettings
        settings = ArgosSettings()
    assert settings.llm_backend == "openai-compatible"


def test_get_settings_is_cached():
    """get_settings() returns the same instance on repeated calls."""
    from src.settings import get_settings
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_settings.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.settings'`

- [ ] **Step 3: Create `src/settings.py`**

```python
"""
ArgosSettings — single source of truth for all Argos configuration.

Reads from environment variables (ARGOS_ prefix) and .env file.
src/config.py re-exports from here for backward compatibility.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class ArgosSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",       # legacy vars have no prefix (LLM_BACKEND, etc.)
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM ---
    llm_backend: str = "openai-compatible"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_api_key_2: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_lightweight_model: str = "llama-3.1-8b-instant"

    # --- Vision LLM ---
    vision_base_url: Optional[str] = None
    vision_api_key: Optional[str] = None
    vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # --- Embeddings ---
    embedding_base_url: str = "https://api.groq.com/openai/v1"
    embedding_api_key: str = ""
    embedding_model: str = "nomic-embed-text-v1.5"
    embedding_dim: int = 768

    # --- STT ---
    stt_backend: str = "groq"
    stt_custom_url: str = ""
    stt_custom_api_key: str = ""

    # --- Features ---
    enable_voice: bool = False
    history_limit: int = 10

    # --- Rate Limiting ---
    rate_limit_per_hour: int = 50
    rate_limit_per_minute: int = 5

    # --- Agent ---
    argos_max_steps: int = 20
    tool_rag_top_k: int = 12
    cost_per_token: float = 0.000002

    # --- Compaction ---
    argos_enable_compaction: bool = False
    argos_mc_ttl_minutes: int = 60
    argos_session_memory_update_every: int = 5
    argos_diminishing_threshold: int = 80
    argos_diminishing_steps: int = 5

    # --- Timeouts ---
    webhook_timeout_seconds: int = 10
    llm_health_check_timeout: int = 3
    n8n_check_timeout: int = 3

    # --- Resilience ---
    circuit_breaker_failure_threshold: int = 5

    # --- Security ---
    argos_paranoid_mode: bool = False
    argos_permission_audit: str = "logs/argos_permissions.jsonl"

    # --- Integrations ---
    n8n_base_url: str = ""

    # --- Observability ---
    otel_exporter_otlp_endpoint: str = ""


@lru_cache(maxsize=1)
def get_settings() -> ArgosSettings:
    """Returns the singleton settings instance (cached after first call)."""
    return ArgosSettings()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_settings.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/settings.py tests/test_settings.py
git commit -m "feat(config): add ArgosSettings via Pydantic Settings"
```

---

## Task 3: Update `src/config.py` as Shim

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: Replace `src/config.py` content**

Read the current `src/config.py` first, then replace it entirely with a shim that re-exports from `ArgosSettings` so all existing `from src.config import X` calls continue to work:

```python
"""
Backward-compatibility shim.

All config values are now defined in src/settings.py (ArgosSettings).
This module re-exports them so existing imports don't break.
"""
from src.settings import get_settings as _gs

_s = _gs()

LLM_BACKEND = _s.llm_backend
LLM_BASE_URL = _s.llm_base_url
LLM_API_KEY = _s.llm_api_key
LLM_API_KEY_2 = _s.llm_api_key_2
LLM_MODEL = _s.llm_model
LLM_LIGHTWEIGHT_MODEL = _s.llm_lightweight_model

VISION_BASE_URL = _s.vision_base_url or _s.llm_base_url
VISION_API_KEY = _s.vision_api_key or _s.llm_api_key
VISION_MODEL = _s.vision_model

EMBEDDING_BASE_URL = _s.embedding_base_url
EMBEDDING_API_KEY = _s.embedding_api_key
EMBEDDING_MODEL = _s.embedding_model
EMBEDDING_DIM = _s.embedding_dim

STT_BACKEND = _s.stt_backend
STT_CUSTOM_URL = _s.stt_custom_url
STT_CUSTOM_API_KEY = _s.stt_custom_api_key

ENABLE_VOICE = _s.enable_voice
HISTORY_LIMIT = _s.history_limit

RATE_LIMIT_PER_HOUR = _s.rate_limit_per_hour
RATE_LIMIT_PER_MINUTE = _s.rate_limit_per_minute

WEBHOOK_TIMEOUT_SECONDS = _s.webhook_timeout_seconds
LLM_HEALTH_CHECK_TIMEOUT = _s.llm_health_check_timeout
N8N_CHECK_TIMEOUT = _s.n8n_check_timeout

CIRCUIT_BREAKER_FAILURE_THRESHOLD = _s.circuit_breaker_failure_threshold

N8N_BASE_URL = _s.n8n_base_url

# Agent config
ARGOS_MAX_STEPS = _s.argos_max_steps
TOOL_RAG_TOP_K = _s.tool_rag_top_k
COST_PER_TOKEN = _s.cost_per_token
```

- [ ] **Step 2: Run import smoke test**

```bash
python -c "from src.config import LLM_MODEL, LLM_API_KEY, TOOL_RAG_TOP_K; print('shim OK')"
```

Expected: `shim OK`

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/config.py
git commit -m "refactor(config): convert config.py to ArgosSettings shim"
```

---

## Task 4: JSON Structured Logging

**Files:**
- Create: `src/logging_config.py`
- Test: `tests/test_logging_config.py`
- Modify: `api/server.py`
- Modify: `scripts/main.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_logging_config.py`:

```python
"""Tests for JSON logging configuration."""
import json
import logging
import io
import pytest
from src.logging_config import configure_json_logging, get_trace_id, set_trace_id


def test_configure_json_logging_emits_json():
    """After configure_json_logging(), log records are JSON-formatted."""
    stream = io.StringIO()
    configure_json_logging(stream=stream, level=logging.DEBUG)

    logger = logging.getLogger("test_json_logger")
    logger.info("hello world", extra={"tool": "list_files", "step": 3})

    output = stream.getvalue()
    assert output.strip() != ""
    record = json.loads(output.strip().split("\n")[-1])
    assert record["message"] == "hello world"
    assert record["tool"] == "list_files"
    assert record["step"] == 3


def test_trace_id_context():
    """set_trace_id/get_trace_id work per-context."""
    set_trace_id("abc-123")
    assert get_trace_id() == "abc-123"


def test_trace_id_default_empty():
    """get_trace_id returns empty string when not set."""
    from contextvars import copy_context
    ctx = copy_context()
    result = ctx.run(get_trace_id)
    # In a fresh context, trace_id defaults to ""
    assert isinstance(result, str)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_logging_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.logging_config'`

- [ ] **Step 3: Create `src/logging_config.py`**

```python
"""
JSON structured logging configuration for Argos.

Call configure_json_logging() once at application startup (in lifespan or main()).
All loggers under 'argos' namespace will emit JSON records with trace_id.
"""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from io import IOBase
from typing import Optional

from pythonjsonlogger import jsonlogger

# ── Per-request trace ID ───────────────────────────────────────────────────
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


class _TraceIdFilter(logging.Filter):
    """Injects trace_id from contextvars into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()  # type: ignore[attr-defined]
        return True


def configure_json_logging(
    stream: Optional[IOBase] = None,
    level: int = logging.INFO,
) -> None:
    """
    Configure root and 'argos' loggers to emit JSON records.

    Args:
        stream: Output stream (default: sys.stdout). Pass io.StringIO in tests.
        level: Log level threshold (default: INFO).
    """
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s %(trace_id)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        rename_fields={"asctime": "timestamp", "name": "logger", "levelname": "level"},
    )

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(_TraceIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "litellm", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_logging_config.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Call `configure_json_logging()` in `api/server.py`**

Read `api/server.py`, then find the lifespan function and add at the top of the startup block:

```python
from src.logging_config import configure_json_logging
configure_json_logging()
```

- [ ] **Step 6: Call `configure_json_logging()` in `scripts/main.py`**

Read `scripts/main.py`, then add near the top (after imports, before any other code):

```python
from src.logging_config import configure_json_logging
configure_json_logging()
```

- [ ] **Step 7: Commit**

```bash
git add src/logging_config.py tests/test_logging_config.py api/server.py scripts/main.py
git commit -m "feat(logging): add JSON structured logging with trace_id contextvars"
```

---

## Task 5: Update Key Log Calls in engine.py to Structured Format

**Files:**
- Modify: `src/core/engine.py`

- [ ] **Step 1: Find the most frequent log patterns**

```bash
grep -n "logger\." src/core/engine.py | head -30
```

- [ ] **Step 2: Update log calls to use `extra={}` dicts**

For each significant log call in `_reasoning_loop` and `_execute_tool_calls_parallel`, update from f-string format to structured format. Examples:

**Before:**
```python
logger.info(f"[Step {state.step_count}] Tool: {tool_name} | Input: {str(tool_input)[:80]}")
```

**After:**
```python
logger.info("tool_dispatched", extra={
    "step": state.step_count,
    "tool": tool_name,
    "input_preview": str(tool_input)[:80],
})
```

**Before:**
```python
logger.info(f"[ActivitySummary] [step {state.step_count}/{self.max_steps}] {task[:60]}")
```

**After:**
```python
logger.info("activity_summary", extra={
    "step": state.step_count,
    "max_steps": self.max_steps,
    "task_preview": task[:60],
})
```

Update at minimum the 5 most frequently emitted log lines. Leave debug-level calls as-is.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Final commit**

```bash
git add src/core/engine.py
git commit -m "feat(phase4): Pydantic Settings + JSON logging — Phase 4 complete"
```

---

## Final Verification

- [ ] **Smoke test all 4 phases together**

```bash
python -c "
from src.settings import get_settings
from src.llm.client import complete, LLMResponse
from src.tools.spec import ToolSpec
from src.planner.planner import parse_litellm_response
from src.core.mem0_adapter import ArgosMemory
from src.core.engine import CoreAgent
from src.logging_config import configure_json_logging, get_trace_id
print('All systems OK')
print(f'Model: {get_settings().llm_model}')
print(f'Tool RAG top-k: {get_settings().tool_rag_top_k}')
"
```

Expected:
```
All systems OK
Model: <your configured model>
Tool RAG top-k: 12
```

- [ ] **Final test suite**

```bash
pytest tests/ -q
```

Expected: all tests pass.
