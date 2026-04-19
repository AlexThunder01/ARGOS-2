"""Tests for mem0 adapter — all mem0 calls mocked."""

from unittest.mock import MagicMock, patch

import pytest

from src.core.mem0_adapter import ArgosMemory


@pytest.fixture
def mock_mem0(monkeypatch):
    mock = MagicMock()
    mock.add.return_value = {
        "results": [{"id": "mem_1", "memory": "user likes Python"}]
    }
    mock.search.return_value = {
        "results": [{"id": "mem_1", "memory": "user likes Python", "score": 0.92}]
    }
    mock.get_all.return_value = {
        "results": [{"id": "mem_1", "memory": "user likes Python"}]
    }
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
