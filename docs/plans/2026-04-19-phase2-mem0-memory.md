# Phase 2: mem0 Memory Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual debounced extraction and GC logic in `src/core/memory.py` with mem0, which adds entity extraction, deduplication, forgetting curve, and user profiles — all backed by the existing pgvector/SQLite infrastructure.

**Architecture:** mem0's `Memory` class wraps pgvector as its vector store. `get_embedding()` and `check_embedding_dimensions()` remain as utilities. The `CoreAgent._maybe_extract_memories()` and `_retrieve_memories()` methods delegate to mem0 instead of the hand-rolled extraction loop. The DB schema is unchanged; mem0 writes to the same `memories` table via its pgvector adapter.

**Prerequisite:** Phase 1 complete (LiteLLM installed and working).

**Tech Stack:** `mem0ai>=0.1.0`, existing pgvector (PostgreSQL) or numpy (SQLite) backend

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `requirements.txt` | Add `mem0ai` |
| Create | `src/core/mem0_adapter.py` | Thin wrapper: initialize mem0 `Memory`, expose `add()` / `search()` / `get_all()` |
| Modify | `src/core/memory.py` | Keep `get_embedding()`, `check_embedding_dimensions()`; remove extraction/GC logic |
| Modify | `src/core/engine.py` | `_maybe_extract_memories()` → `mem0_adapter.add()`; `_retrieve_memories()` → `mem0_adapter.search()` |
| Create | `tests/test_mem0_adapter.py` | Unit tests for mem0 adapter with mocked mem0 |

---

## Task 1: Install mem0

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add `mem0ai` to requirements.txt**

Add after the LiteLLM line:

```
mem0ai>=0.1.0
```

- [ ] **Step 2: Install**

```bash
pip install "mem0ai>=0.1.0"
```

Expected: `python -c "import mem0; print('OK')"` prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add mem0ai for structured agent memory"
```

---

## Task 2: Create `src/core/mem0_adapter.py`

**Files:**
- Create: `src/core/mem0_adapter.py`
- Test: `tests/test_mem0_adapter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_mem0_adapter.py`:

```python
"""Tests for mem0 adapter — all mem0 calls mocked."""
from unittest.mock import MagicMock, patch

import pytest

from src.core.mem0_adapter import ArgosMemory


@pytest.fixture
def mock_mem0(monkeypatch):
    mock = MagicMock()
    mock.add.return_value = {"results": [{"id": "mem_1", "memory": "user likes Python"}]}
    mock.search.return_value = {"results": [
        {"id": "mem_1", "memory": "user likes Python", "score": 0.92}
    ]}
    mock.get_all.return_value = {"results": [
        {"id": "mem_1", "memory": "user likes Python"}
    ]}
    monkeypatch.setattr("src.core.mem0_adapter._build_mem0", lambda: mock)
    return mock


def test_add_stores_memory(mock_mem0):
    memory = ArgosMemory(user_id=42)
    memory.add("user likes Python")
    mock_mem0.add.assert_called_once()
    call_args = mock_mem0.add.call_args
    assert "user likes Python" in str(call_args)


def test_search_returns_list_of_strings(mock_mem0):
    memory = ArgosMemory(user_id=42)
    results = memory.search("programming language preference")
    assert isinstance(results, list)
    assert len(results) == 1
    assert "user likes Python" in results[0]


def test_search_empty_query_returns_empty(mock_mem0):
    mock_mem0.search.return_value = {"results": []}
    memory = ArgosMemory(user_id=42)
    results = memory.search("")
    assert results == []


def test_get_all_returns_all_memories(mock_mem0):
    memory = ArgosMemory(user_id=42)
    all_mems = memory.get_all()
    assert isinstance(all_mems, list)
    assert len(all_mems) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mem0_adapter.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.core.mem0_adapter'`

- [ ] **Step 3: Create `src/core/mem0_adapter.py`**

```python
"""
mem0 adapter for Argos memory system.

Wraps mem0's Memory class to expose a simple add/search/get_all interface,
backed by the configured vector store (pgvector or numpy SQLite fallback).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("argos")


def _build_mem0():
    """Initialize and return a mem0 Memory instance with Argos config."""
    from mem0 import Memory
    from src.config import (
        EMBEDDING_API_KEY,
        EMBEDDING_BASE_URL,
        EMBEDDING_MODEL,
        LLM_API_KEY,
        LLM_BASE_URL,
        LLM_MODEL,
    )

    config = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": LLM_MODEL,
                "api_key": LLM_API_KEY or "dummy",
                "openai_base_url": LLM_BASE_URL,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": EMBEDDING_MODEL,
                "api_key": EMBEDDING_API_KEY or LLM_API_KEY or "dummy",
                "openai_base_url": EMBEDDING_BASE_URL,
            },
        },
        "vector_store": {
            "provider": "qdrant",  # mem0 uses qdrant by default; override below for pgvector
            "config": {"collection_name": "argos_memories", "embedding_model_dims": 768},
        },
    }

    # Prefer pgvector if DATABASE_URL is set (production)
    import os
    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith("postgresql"):
        config["vector_store"] = {
            "provider": "pgvector",
            "config": {
                "dbname": _parse_dbname(database_url),
                "collection_name": "argos_memories",
                "embedding_model_dims": int(os.getenv("EMBEDDING_DIM", "768")),
            },
        }

    return Memory.from_config(config)


def _parse_dbname(url: str) -> str:
    """Extracts the database name from a postgresql:// URL."""
    try:
        return url.split("/")[-1].split("?")[0]
    except Exception:
        return "argos"


class ArgosMemory:
    """
    Thin wrapper over mem0 Memory.

    All operations are synchronous (mem0 handles async internally).
    Callers in CoreAgent use asyncio.to_thread() to avoid blocking.
    """

    def __init__(self, user_id: int):
        self._user_id = str(user_id)
        self._mem0 = _build_mem0()

    def add(self, text: str) -> None:
        """Store a new memory fact. mem0 handles entity extraction and deduplication."""
        if not text or not text.strip():
            return
        try:
            self._mem0.add(text, user_id=self._user_id)
        except Exception as e:
            logger.warning(f"[Memory] mem0 add failed: {e}")

    def search(self, query: str, top_k: int = 5) -> list[str]:
        """Return top_k memory strings most relevant to query."""
        if not query or not query.strip():
            return []
        try:
            result = self._mem0.search(query, user_id=self._user_id, limit=top_k)
            return [r["memory"] for r in result.get("results", [])]
        except Exception as e:
            logger.warning(f"[Memory] mem0 search failed: {e}")
            return []

    def get_all(self) -> list[str]:
        """Return all stored memory strings for this user."""
        try:
            result = self._mem0.get_all(user_id=self._user_id)
            return [r["memory"] for r in result.get("results", [])]
        except Exception as e:
            logger.warning(f"[Memory] mem0 get_all failed: {e}")
            return []
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mem0_adapter.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/mem0_adapter.py tests/test_mem0_adapter.py
git commit -m "feat(memory): add ArgosMemory wrapper over mem0"
```

---

## Task 3: Wire ArgosMemory into CoreAgent

**Files:**
- Modify: `src/core/engine.py`

- [ ] **Step 1: Add ArgosMemory import to engine.py**

At the top of `src/core/engine.py`, add:

```python
from src.core.mem0_adapter import ArgosMemory
```

- [ ] **Step 2: Initialize `_argos_memory` in `CoreAgent.__init__`**

In `CoreAgent.__init__`, after `self.memory_mode = memory_mode`, add:

```python
self._argos_memory: Optional[ArgosMemory] = (
    ArgosMemory(user_id=self.user_id) if memory_mode == "persistent" else None
)
```

- [ ] **Step 3: Replace `_retrieve_memories()` implementation**

Find `_retrieve_memories()` in `CoreAgent`. Replace its body with:

```python
def _retrieve_memories(self, task: str) -> list[str]:
    if self.memory_mode != "persistent" or self._argos_memory is None:
        return []
    return self._argos_memory.search(task, top_k=5)
```

- [ ] **Step 4: Replace `_maybe_extract_memories()` implementation**

Find `_maybe_extract_memories()` in `CoreAgent`. Replace its body with:

```python
def _maybe_extract_memories(
    self,
    task: str,
    relevant_memories: list[str],
    task_count: int,
    step_count: int = 0,
    task_success: bool = True,
) -> None:
    if self.memory_mode != "persistent" or self._argos_memory is None:
        return
    if not task_success:
        return
    # Build a summary of what happened in this task for mem0 to extract from
    summary_parts = [f"Task: {task}"]
    if relevant_memories:
        summary_parts.append(f"Prior context: {'; '.join(relevant_memories[:3])}")
    summary = " | ".join(summary_parts)
    self._argos_memory.add(summary)
```

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/core/engine.py
git commit -m "feat(engine): wire ArgosMemory (mem0) into CoreAgent retrieve/extract pipeline"
```

---

## Task 4: Clean Up Old Extraction Logic in `memory.py`

**Files:**
- Modify: `src/core/memory.py`

- [ ] **Step 1: Identify what to remove**

```bash
grep -n "EXTRACT_EVERY_N\|GC_EVERY_N\|debounce\|garbage" src/core/memory.py
```

- [ ] **Step 2: Remove extraction/GC constants and functions**

Remove from `src/core/memory.py`:
- `EXTRACT_EVERY_N`, `GC_EVERY_N`, `EXTRACT_MIN_LENGTH` constants (if only used for extraction)
- Any `extract_memories_from_text()` or similar extraction function
- Any `gc_memories()` or similar GC function

**Keep:**
- `get_embedding()` — still used by `select_for_query()` in `tools/spec.py`
- `check_embedding_dimensions()` — still used at boot

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -x -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/core/memory.py
git commit -m "refactor(memory): remove manual extraction/GC — delegated to mem0"
```

---

## Task 5: End-to-End Verification

- [ ] **Step 1: Import smoke test**

```bash
python -c "
from src.core.mem0_adapter import ArgosMemory
from src.core.engine import CoreAgent
print('mem0 wiring OK')
"
```

Expected: `mem0 wiring OK`

- [ ] **Step 2: Full test suite**

```bash
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(phase2): mem0 memory layer — Phase 2 complete"
```
