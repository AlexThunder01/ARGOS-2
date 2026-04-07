import hmac
import logging
import os

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger("argos")

ARGOS_API_KEY = os.getenv("ARGOS_API_KEY", "").strip()
# Explicit opt-in required to run without an API key (dev/local only).
# Set ARGOS_PERMISSIVE_MODE=true in .env to bypass authentication.
_PERMISSIVE_MODE = os.getenv("ARGOS_PERMISSIVE_MODE", "false").lower() == "true"

if _PERMISSIVE_MODE:
    logger.warning(
        "⚠️  ARGOS_PERMISSIVE_MODE=true — API authentication is DISABLED. "
        "This setting is for local development only. "
        "Never use it in production."
    )

api_key_header = APIKeyHeader(name="X-ARGOS-API-KEY", auto_error=False)


async def verify_api_key(key: str = Security(api_key_header)):
    if not ARGOS_API_KEY:
        if _PERMISSIVE_MODE:
            logger.warning(
                "⚠️  ARGOS_PERMISSIVE_MODE=true — API is unprotected! "
                "Set ARGOS_API_KEY before deploying to production."
            )
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "API key not configured on server. "
                "Set ARGOS_API_KEY in the environment, or set "
                "ARGOS_PERMISSIVE_MODE=true for local development only."
            ),
        )
    if not hmac.compare_digest(key or "", ARGOS_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: Invalid or missing API Key",
        )


def get_admin_chat_id() -> str:
    return os.getenv("ADMIN_CHAT_ID", "0").strip()
