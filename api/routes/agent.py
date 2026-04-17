"""
ARGOS-2 API — Agent Task Execution Routes.

Provides /run (synchronous) and /run_async (webhook-based) endpoints
for executing natural language tasks through the CoreAgent.

Idempotence: /run_async accepts an optional Idempotency-Key header.
If the same key is submitted twice, the second request returns the
cached job_id immediately without spawning a new execution.
"""

import asyncio
import ipaddress
import logging
import urllib.parse
import uuid
from threading import Lock
from typing import List, Optional

import pybreaker
import requests
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api.security import verify_api_key
from src.config import LLM_BACKEND, LLM_MODEL
from src.core import CoreAgent

router = APIRouter(tags=["Agent"])
logger = logging.getLogger("argos")

llm_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60)

# ── Idempotency store ──────────────────────────────────────────────────────
# Maps idempotency_key → job_id for deduplication of async requests.
# In-memory: resets on server restart (acceptable for short-lived jobs).
_idempotency_store: dict[str, str] = {}
_idempotency_lock = Lock()

# ── Agent cache ────────────────────────────────────────────────────────────
# CoreAgent construction rebuilds the ToolSpec registry and ArgosAgent on
# every call.  Since memory_mode="off" agents are stateless between tasks,
# we cache them by (require_confirmation, max_steps).
# Bounded to _AGENT_CACHE_MAX entries to prevent unbounded memory growth.
_AGENT_CACHE_MAX = 32
_agent_cache: dict[tuple, "CoreAgent"] = {}
_agent_cache_lock = Lock()


def _get_agent(require_confirmation: bool, max_steps: int) -> "CoreAgent":
    key = (require_confirmation, max_steps)
    with _agent_cache_lock:
        if key not in _agent_cache:
            if len(_agent_cache) >= _AGENT_CACHE_MAX:
                # Evict the oldest entry (insertion-order dict, Python 3.7+)
                oldest_key = next(iter(_agent_cache))
                del _agent_cache[oldest_key]
            _agent_cache[key] = CoreAgent(
                memory_mode="off",
                require_confirmation=require_confirmation,
                max_steps=max_steps,
            )
    return _agent_cache[key]


# ── SSRF guard ─────────────────────────────────────────────────────────────

_SSRF_BLOCKED_HOSTS = frozenset({"localhost", "0.0.0.0"})


def _validate_webhook_url(url: str) -> None:
    """
    Raises ValueError if the URL targets a loopback, private, link-local,
    or otherwise non-public address (SSRF prevention).
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise ValueError(f"Invalid webhook URL: {exc}") from exc

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Webhook URL must use http or https, got: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook URL has no hostname.")

    if hostname.lower() in _SSRF_BLOCKED_HOSTS:
        raise ValueError(f"Webhook URL targets a blocked hostname: {hostname}")

    try:
        addr = ipaddress.ip_address(hostname)
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            raise ValueError(f"Webhook URL targets a non-public IP address: {hostname}")
    except ValueError as exc:
        if "Webhook URL targets" in str(exc):
            raise
        # hostname is a domain name, not an IP literal — allow it


# ==========================================================================
# Request / Response Models
# ==========================================================================


class TaskRequest(BaseModel):
    task: str = Field(
        ..., description="Natural language task description to be executed"
    )
    require_confirmation: bool = Field(
        default=False, description="If True, halts execution on dangerous actions"
    )
    max_steps: int = Field(
        default=5, ge=1, le=20, description="Maximum internal step bound"
    )
    attachments: list[str] = Field(
        default_factory=list,
        description="Optional list of upload_id UUIDs from POST /api/upload",
    )


class TaskAsyncRequest(TaskRequest):
    webhook_url: str = Field(
        ..., description="Target n8n webhook URL to receive the post-execution payload"
    )


class AsyncAcceptedResponse(BaseModel):
    status: str
    job_id: str
    message: str
    deduplicated: bool = False  # True if this job_id was already in flight


class StepRecord(BaseModel):
    step: int
    tool: str
    result: str
    success: bool
    timestamp: str


class TaskResponse(BaseModel):
    success: bool
    task: str
    steps_executed: int
    result: str
    history: List[StepRecord]
    backend: str
    model: str


class StatusResponse(BaseModel):
    status: str
    backend: str
    model: str
    agent_ready: bool


# ==========================================================================
# Core Logic — Delegates to CoreAgent
# ==========================================================================


def _task_result_to_response(result, agent: CoreAgent, task: str) -> TaskResponse:
    step_records = [
        StepRecord(
            step=s.step,
            tool=s.tool,
            result=s.result[:200],
            success=s.success,
            timestamp=s.timestamp,
        )
        for s in result.history
    ]
    return TaskResponse(
        success=result.success,
        task=task,
        steps_executed=result.steps_executed,
        result=result.response,
        history=step_records,
        backend=agent.backend,
        model=agent.model,
    )


async def _run_task_async_core(
    task: str, require_confirmation: bool, max_steps: int
) -> TaskResponse:
    """
    Executes a task via the async CoreAgent (non-blocking httpx LLM calls).

    pybreaker.CircuitBreaker.call() is sync-only; we manually honour the
    breaker's open state and delegate success/failure tracking to it via a
    thread so we don't block the event loop.
    """
    agent = _get_agent(require_confirmation, max_steps)

    # Honour open circuit without blocking
    if llm_breaker.current_state == pybreaker.STATE_OPEN:
        return TaskResponse(
            success=False,
            task=task,
            steps_executed=0,
            result="LLM Service unavailable (Circuit Breaker OPEN)",
            history=[],
            backend=agent.backend,
            model=agent.model,
        )

    try:
        result = await agent.run_task_async(task)
        # Record success so the breaker can close from HALF_OPEN
        await asyncio.to_thread(llm_breaker.call, lambda: None)
    except pybreaker.CircuitBreakerError:
        return TaskResponse(
            success=False,
            task=task,
            steps_executed=0,
            result="LLM Service unavailable (Circuit Breaker OPEN)",
            history=[],
            backend=agent.backend,
            model=agent.model,
        )
    except Exception:
        raise

    return _task_result_to_response(result, agent, task)


def _run_task_sync(
    task: str, require_confirmation: bool, max_steps: int
) -> TaskResponse:
    """Sync fallback — used only by the webhook background worker."""
    agent = _get_agent(require_confirmation, max_steps)
    try:
        result = llm_breaker.call(agent.run_task, task)
    except pybreaker.CircuitBreakerError:
        return TaskResponse(
            success=False,
            task=task,
            steps_executed=0,
            result="LLM Service unavailable (Circuit Breaker OPEN)",
            history=[],
            backend=agent.backend,
            model=agent.model,
        )
    return _task_result_to_response(result, agent, task)


def _run_task_async_worker(
    job_id: str, webhook_url: str, task: str, req_conf: bool, max_steps: int
):
    """Background worker for asynchronous task execution."""
    logger.info(
        f"⏳ Async Job [{job_id}] initialized for target webhook: {webhook_url}"
    )

    try:
        result: TaskResponse = _run_task_sync(task, req_conf, max_steps)
        payload = result.model_dump()
        payload["job_id"] = job_id

        # NEW: n8n credential validation (D-02)
        # If credential_id is present in payload and becomes None, fail immediately
        cred_id = payload.get("n8n_credential_id")
        if "n8n_credential_id" in payload and cred_id is None:
            error_msg = "n8n credential creation returned None cred_id — aborting workflow activation"
            logger.error(f"[n8n] {error_msg}")
            raise ValueError(error_msg)

        # NEW: n8n OAuth2 authorization check (D-03)
        import os

        try:
            from src.config import N8N_BASE_URL

            n8n_base = N8N_BASE_URL
            if n8n_base:  # Only check if n8n is configured
                oauth_status_url = f"{n8n_base.rstrip('/')}/api/v1/oauth2/authorize"
                oauth_resp = requests.get(oauth_status_url, timeout=3)
                if oauth_resp.status_code not in (200, 204):
                    error_msg = f"n8n OAuth2 authorization failed: HTTP {oauth_resp.status_code}"
                    logger.error(f"[n8n] {error_msg}")
                    raise ValueError(error_msg)
                logger.info("[n8n] OAuth2 authorization verified")
        except requests.RequestException as e:
            error_msg = f"n8n OAuth2 check failed: {e}"
            logger.error(f"[n8n] {error_msg}")
            raise ValueError(error_msg)

        logger.info(f"📤 Dispatching Job result [{job_id}] to {webhook_url}")
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code >= 400:
            logger.error(
                f"❌ Webhook dispatch failed for Job [{job_id}]: HTTP {resp.status_code} - {resp.text}"
            )
        else:
            logger.info(f"✅ Webhook successfully delivered for Job [{job_id}]")

    except Exception as e:
        logger.error(
            f"❌ Critical exception caught in async job worker [{job_id}]: {e}"
        )
        try:
            requests.post(
                webhook_url,
                json={
                    "success": False,
                    "job_id": job_id,
                    "result": f"Internal Server Error: {e}",
                },
                timeout=5,
            )
        except Exception:
            logger.warning(
                f"[Job {job_id}] Failed to deliver error payload to webhook."
            )


# ==========================================================================
# Routes
# ==========================================================================


@router.get("/status", response_model=StatusResponse, tags=["System"])
async def status():
    return StatusResponse(
        status="online",
        backend=LLM_BACKEND,
        model=LLM_MODEL,
        agent_ready=True,
    )


@router.post(
    "/run", response_model=TaskResponse, dependencies=[Depends(verify_api_key)]
)
async def run_task(req: TaskRequest):
    from src.core.rate_limit import RateLimitExceeded, check_rate_limit

    try:
        check_rate_limit(0)  # 0 is standard for REST API access
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    task = req.task
    if req.attachments:
        from src.upload import build_attachment_context

        task = f"{task}\n\n{build_attachment_context(req.attachments)}"

    try:
        return await _run_task_async_core(task, req.require_confirmation, req.max_steps)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Endpoint Exception /run: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/run_async",
    response_model=AsyncAcceptedResponse,
    status_code=202,
    dependencies=[Depends(verify_api_key)],
)
async def run_task_async(
    req: TaskAsyncRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    from src.core.rate_limit import RateLimitExceeded, check_rate_limit

    try:
        check_rate_limit(0)
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    # ── SSRF guard ─────────────────────────────────────────────────────────
    try:
        _validate_webhook_url(req.webhook_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook_url: {e}")

    # ── Idempotency check ──────────────────────────────────────────────────
    if idempotency_key:
        with _idempotency_lock:
            if idempotency_key in _idempotency_store:
                existing_job_id = _idempotency_store[idempotency_key]
                logger.info(
                    f"[Idempotency] Duplicate request for key '{idempotency_key}' "
                    f"→ returning existing job_id={existing_job_id}"
                )
                return AsyncAcceptedResponse(
                    status="accepted",
                    job_id=existing_job_id,
                    message="Duplicate request detected. Returning existing job.",
                    deduplicated=True,
                )

    job_id = str(uuid.uuid4())[:8]

    # Store idempotency key before spawning background task
    if idempotency_key:
        with _idempotency_lock:
            _idempotency_store[idempotency_key] = job_id

    async_task = req.task
    if req.attachments:
        from src.upload import build_attachment_context

        async_task = f"{async_task}\n\n{build_attachment_context(req.attachments)}"

    background_tasks.add_task(
        _run_task_async_worker,
        job_id=job_id,
        webhook_url=req.webhook_url,
        task=async_task,
        req_conf=req.require_confirmation,
        max_steps=req.max_steps,
    )

    return AsyncAcceptedResponse(
        status="accepted",
        job_id=job_id,
        message="The task has been securely queued. Final execution payload will be delivered to the provided webhook.",
    )
