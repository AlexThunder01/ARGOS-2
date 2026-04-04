"""
Executor — Esegue i tool con retry automatico, timeout e classificazione degli errori.
"""

import logging
import time
from typing import Any, Callable

from src.actions.base import ActionResult, ActionStatus

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
    # Default: considera l'eccezione Python come temporanea
    return True


def execute_with_retry(
    tool_fn: Callable,
    tool_input: Any,
    tool_name: str = "unknown",
    max_retries: int = MAX_RETRIES,
) -> ActionResult:
    """
    Esegue un tool con retry automatico in caso di errori temporanei.

    Returns:
        ActionResult con status SUCCESS, FAILED o RETRYING.
    """
    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            result = tool_fn(tool_input)
            result_str = str(result)

            # Check if the return string is a recognized error
            if result_str.startswith(("Error", "Errore")):
                is_retryable = _classify_error(result_str)
                if is_retryable and attempt < max_retries:
                    wait = RETRY_DELAY_BASE * attempt
                    logger.warning(
                        f"[{tool_name}] Attempt {attempt}/{max_retries} → transient error. "
                        f"Waiting {wait:.1f}s... ({result_str[:80]})"
                    )
                    time.sleep(wait)
                    last_error = result_str
                    continue
                else:
                    # Fatal error or retries exhausted
                    return ActionResult(
                        status=ActionStatus.FAILED,
                        message=result_str,
                        should_retry=False,
                    )

            # Successo
            return ActionResult(
                status=ActionStatus.SUCCESS,
                message=result_str,
            )

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                wait = RETRY_DELAY_BASE * attempt
                logger.warning(
                    f"[{tool_name}] Eccezione tentativo {attempt}/{max_retries}: {e} "
                    f"— Retry in {wait:.1f}s"
                )
                time.sleep(wait)
            else:
                logger.error(f"[{tool_name}] Failed after {max_retries} attempts: {e}")

    return ActionResult(
        status=ActionStatus.FAILED,
        message=f"Failed after {max_retries} attempts. Last error: {last_error}",
        should_retry=False,
    )
