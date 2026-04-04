import logging
import os

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger("argos")

ARGOS_API_KEY = os.getenv("ARGOS_API_KEY", "").strip()
api_key_header = APIKeyHeader(name="X-ARGOS-API-KEY", auto_error=False)


async def verify_api_key(key: str = Security(api_key_header)):
    if not ARGOS_API_KEY:
        logger.warning(
            "⚠️ Permissive mode: ARGOS_API_KEY is not set. API is unprotected!"
        )
        return
    if key != ARGOS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: Invalid or missing API Key",
        )


def get_admin_chat_id() -> str:
    return os.getenv("ADMIN_CHAT_ID", "0").strip()
