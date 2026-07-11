"""
Executor — Esegue i tool con retry automatico su errori transitori.
"""

import asyncio
import inspect
from collections.abc import Callable
from typing import Any


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
