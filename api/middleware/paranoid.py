"""
ARGOS-2 API — Paranoid Mode Middleware.

FastAPI dependency that runs the Paranoid Judge security pipeline
on incoming request text. Controlled by ARGOS_PARANOID_MODE env var.

Usage in routes:
    from api.middleware.paranoid import paranoid_guard

    @router.post("/run", dependencies=[Depends(paranoid_guard)])
    async def run_task(req: TaskRequest):
        ...
"""

import logging
import os

from fastapi import HTTPException

from src.core.security import run_security_pipeline

logger = logging.getLogger("argos")

# Read once at import time; restart to change
_PARANOID_MODE = os.getenv("ARGOS_PARANOID_MODE", "false").lower() == "true"


async def paranoid_guard(text: str = ""):
    """
    FastAPI dependency. When ARGOS_PARANOID_MODE is enabled,
    runs the full security pipeline on the request text.
    Raises HTTP 422 if the input is flagged as suspicious.

    When disabled, this is a no-op pass-through.
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
