"""
Health check endpoint for system observability.

Provides comprehensive status of all critical subsystems:
- API: always ok (this endpoint is running)
- DB: SELECT 1 to verify connectivity
- LLM: lightweight ping to {LLM_BASE_URL}/v1/models
- Migrations: compare applied count vs pending
- n8n: configured or unconfigured based on N8N_BASE_URL
"""

import asyncio
import logging
from pathlib import Path

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_HEALTH_CHECK_TIMEOUT,
    N8N_BASE_URL,
    N8N_CHECK_TIMEOUT,
)
from src.db.connection import DB_BACKEND, get_connection

router = APIRouter(tags=["System"])
logger = logging.getLogger("argos")


def _check_db() -> str:
    """Check database connectivity. Returns 'ok' or 'error'."""
    try:
        conn = get_connection()
        if DB_BACKEND == "postgres":
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
        else:
            conn.execute("SELECT 1")
        logger.info("[DB] Health check passed")
        return "ok"
    except Exception as e:
        logger.error(f"[DB] Health check failed: {e}")
        return "error"


def _check_llm() -> str:
    """
    Check LLM connectivity with lightweight ping.
    Queries {LLM_BASE_URL}/models with 3s timeout.
    LLM_BASE_URL already contains the version prefix (e.g. /v1), so we
    append only /models — not /v1/models — to avoid double-versioning.
    Returns 'ok' or 'error'.
    """
    try:
        base_url = LLM_BASE_URL.rstrip("/")
        headers = {}
        if LLM_API_KEY:
            headers["Authorization"] = f"Bearer {LLM_API_KEY}"

        resp = requests.get(
            f"{base_url}/models",
            headers=headers,
            timeout=LLM_HEALTH_CHECK_TIMEOUT,
        )
        if resp.status_code < 400:
            logger.info("[LLM] Health check passed")
            return "ok"
        else:
            logger.error(f"[LLM] Health check failed: HTTP {resp.status_code}")
            return "error"
    except requests.RequestException as e:
        logger.error(f"[LLM] Health check failed: {e}")
        return "error"


def _check_migrations() -> str:
    """
    Check if pending migrations exist.
    Compare COUNT(*) FROM schema_migrations vs .py files in migrations dir.
    Returns 'applied', 'pending', or 'error'.
    """
    try:
        conn = get_connection()

        # Count applied migrations
        if DB_BACKEND == "postgres":
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM schema_migrations")
            row = cursor.fetchone()
            applied_count = row[0] if row else 0
        else:
            cursor = conn.execute("SELECT COUNT(*) FROM schema_migrations")
            applied_count = cursor.fetchone()[0]

        # Count pending migrations (matching pattern [0-9][0-9][0-9]_*.py)
        migrations_dir = Path(__file__).parent.parent.parent / "src" / "db" / "migrations"
        pending_files = list(migrations_dir.glob("[0-9][0-9][0-9]_*.py"))
        total_migrations = len(pending_files)

        if applied_count >= total_migrations:
            logger.info(f"[Migrations] All {total_migrations} migrations applied")
            return "applied"
        else:
            logger.warning(f"[Migrations] {applied_count}/{total_migrations} migrations applied")
            return "pending"
    except Exception as e:
        logger.error(f"[Migrations] Health check failed: {e}")
        return "error"


def _check_n8n() -> str:
    """
    Check n8n configuration and connectivity.
    Returns 'configured', 'unconfigured', or 'error'.
    """
    if not N8N_BASE_URL:
        logger.info("[n8n] Not configured (N8N_BASE_URL is empty)")
        return "unconfigured"

    try:
        resp = requests.get(
            f"{N8N_BASE_URL.rstrip('/')}/api/v1/health",
            timeout=N8N_CHECK_TIMEOUT,
        )
        if resp.status_code < 400:
            logger.info(f"[n8n] Health check passed at {N8N_BASE_URL}")
            return "configured"
        else:
            logger.error(f"[n8n] Health check failed: HTTP {resp.status_code}")
            return "error"
    except requests.RequestException as e:
        logger.error(f"[n8n] Health check failed: {e}")
        return "error"


@router.get("/health")
async def health_check():
    """
    Comprehensive health check endpoint.

    Returns:
        {
            "status": "ok" | "degraded",
            "checks": {
                "api": "ok",
                "db": "ok" | "error",
                "llm": "ok" | "error",
                "migrations": "applied" | "pending" | "error",
                "n8n": "configured" | "unconfigured"
            }
        }

    Status: 200 if all checks are "ok" or "configured"/"unconfigured" for n8n.
            503 if any check is "error".
    """
    checks = {
        "api": "ok",  # This endpoint is running
        "db": await asyncio.to_thread(_check_db),
        "llm": await asyncio.to_thread(_check_llm),
        "migrations": await asyncio.to_thread(_check_migrations),
        "n8n": _check_n8n(),
    }

    # Status is "degraded" if any check is "error"
    has_error = any(v == "error" for v in checks.values())
    status = "degraded" if has_error else "ok"

    return JSONResponse(
        content={
            "status": status,
            "checks": checks,
            "timestamp": asyncio.get_event_loop().time(),
        },
        status_code=503 if has_error else 200,
    )
