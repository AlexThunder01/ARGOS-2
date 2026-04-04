"""
ARGOS-2 API — Paranoid Mode Security Guard.

Runs the Paranoid Judge security pipeline on incoming request text.
Controlled by ARGOS_PARANOID_MODE env var.

Usage in routes (call directly, NOT via Depends — body content is not
available as a query parameter so Depends cannot extract it):

    from api.middleware.paranoid import check_paranoid

    @router.post("/run")
    async def run_task(req: TaskRequest):
        await check_paranoid(req.task)
        ...
"""

import logging
import os

from fastapi import HTTPException

from src.core.security import run_security_pipeline

logger = logging.getLogger("argos")

# Read once at import time; restart to change
_PARANOID_MODE = os.getenv("ARGOS_PARANOID_MODE", "false").lower() == "true"


async def check_paranoid(text: str) -> None:
    """
    When ARGOS_PARANOID_MODE is enabled, runs the full security pipeline on
    the provided text. Raises HTTP 422 if the input is flagged as suspicious.
    When disabled, this is a no-op pass-through.

    Call this at the start of any route that accepts user-provided text:
        await check_paranoid(req.task)
    """
    if not _PARANOID_MODE or not text:
        return

    is_safe, risk_score, blocked_by = run_security_pipeline(text)

    if not is_safe:
        logger.warning(
            f"[ParanoidGuard] BLOCKED request (score={risk_score:.2f}, by={blocked_by}): "
            f"{text[:80]}..."
        )
        raise HTTPException(
            status_code=422,
            detail=f"Input flagged by security pipeline (risk={risk_score:.2f}, layer={blocked_by})",
        )


# Backward-compatible alias kept so any existing `Depends(paranoid_guard)` calls
# still import without an AttributeError (they become no-ops since text="" by default).
paranoid_guard = check_paranoid
