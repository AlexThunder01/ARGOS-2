"""
Executor — Esegue i tool con retry automatico, timeout e classificazione degli errori.

Accetta ToolSpec invece di un callable grezzo: l'input viene validato tramite
lo schema Pydantic prima dell'esecuzione.
"""

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

from src.actions.base import ActionResult, ActionStatus

if TYPE_CHECKING:
    from src.tools.spec import ToolSpec

logger = logging.getLogger("argos")

MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.5  # secondi; il delay cresce: 1.5s, 3s, 4.5s

# Keywords indicating a transient error (retry is worthwhile)
RETRYABLE_KEYWORDS = [
    "timeout",
    "connection",
    "network",
    "rate limit",
    "api failed",
    "connection error",
    "unreachable",
]

# Keywords indicating a permanent error (retry is futile)
FATAL_KEYWORDS = [
    "not found",
    "does not exist",
    "permission denied",
    "already exists",
    "error: please specify",
    "is a directory",
]


def _classify_error(message: str) -> bool:
    """
    Returns True if the error is transient and a retry is warranted.
    Returns False if the error is permanent.
    """
    msg_lower = message.lower()
    if any(kw in msg_lower for kw in FATAL_KEYWORDS):
        return False
    if any(kw in msg_lower for kw in RETRYABLE_KEYWORDS):
        return True
    return False  # Unknown errors are not retried (fail-fast)


def execute_with_retry(
    spec_or_fn: "ToolSpec | Callable",
    tool_input: Any,
    tool_name: str = "unknown",
    max_retries: int = MAX_RETRIES,
) -> ActionResult:
    """
    Valida l'input tramite ToolSpec.validate_input() ed esegue il tool con retry
    automatico in caso di errori temporanei.

    Args:
        spec_or_fn: ToolSpec (preferred) or bare callable (backward compat).
        tool_input: Input grezzo dal LLM (dict, str, o None).
        tool_name: Name for logging (ignored if spec_or_fn is a ToolSpec).
        max_retries: Numero massimo di tentativi.

    Returns:
        ActionResult con status SUCCESS o FAILED.
    """
    # Support both ToolSpec objects and plain callables (used in tests)
    if hasattr(spec_or_fn, "executor"):
        spec = spec_or_fn
        validated = spec.validate_input(tool_input)
        executor_fn = spec.executor
        name = spec.name
    else:
        validated = tool_input
        executor_fn = spec_or_fn
        name = tool_name

    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            result = executor_fn(validated)
            result_str = str(result)

            if result_str.startswith(("Error", "Errore")):
                is_retryable = _classify_error(result_str)
                if is_retryable and attempt < max_retries:
                    wait = RETRY_DELAY_BASE * attempt
                    logger.warning(
                        f"[{name}] Attempt {attempt}/{max_retries} → transient error. "
                        f"Waiting {wait:.1f}s... ({result_str[:80]})"
                    )
                    time.sleep(wait)
                    last_error = result_str
                    continue
                else:
                    return ActionResult(
                        status=ActionStatus.FAILED,
                        message=result_str,
                        should_retry=False,
                    )

            return ActionResult(
                status=ActionStatus.SUCCESS,
                message=result_str,
            )

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                wait = RETRY_DELAY_BASE * attempt
                logger.warning(
                    f"[{name}] Exception attempt {attempt}/{max_retries}: {e} "
                    f"— Retry in {wait:.1f}s"
                )
                time.sleep(wait)
            else:
                logger.error(f"[{name}] Failed after {max_retries} attempts: {e}")

    return ActionResult(
        status=ActionStatus.FAILED,
        message=f"Failed after {max_retries} attempts. Last error: {last_error}",
        should_retry=False,
    )
