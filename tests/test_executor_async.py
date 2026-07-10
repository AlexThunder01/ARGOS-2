"""Tests for async execute_with_retry."""

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
