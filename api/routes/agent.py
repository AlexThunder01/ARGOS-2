"""
ARGOS-2 API — Agent Task Execution Routes.

Provides /run (synchronous) and /run_async (webhook-based) endpoints
for executing natural language tasks through the CoreAgent.
"""

import asyncio
import logging
import uuid
from typing import List

import pybreaker
import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from api.security import verify_api_key
from src.config import LLM_BACKEND, LLM_MODEL
from src.core import CoreAgent

router = APIRouter(tags=["Agent"])
logger = logging.getLogger("argos")

llm_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60)


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


class TaskAsyncRequest(TaskRequest):
    webhook_url: str = Field(
        ..., description="Target n8n webhook URL to receive the post-execution payload"
    )


class AsyncAcceptedResponse(BaseModel):
    status: str
    job_id: str
    message: str


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


def _run_task_sync(
    task: str, require_confirmation: bool, max_steps: int
) -> TaskResponse:
    """Executes a task synchronously via the CoreAgent."""
    agent = CoreAgent(
        memory_mode="off",
        require_confirmation=require_confirmation,
        max_steps=max_steps,
    )

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
        except:
            pass


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

    try:
        return await asyncio.to_thread(
            _run_task_sync, req.task, req.require_confirmation, req.max_steps
        )
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
async def run_task_async(req: TaskAsyncRequest, background_tasks: BackgroundTasks):
    from src.core.rate_limit import RateLimitExceeded, check_rate_limit

    try:
        check_rate_limit(0)  # 0 is standard for REST API access
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    job_id = str(uuid.uuid4())[:8]

    background_tasks.add_task(
        _run_task_async_worker,
        job_id=job_id,
        webhook_url=req.webhook_url,
        task=req.task,
        req_conf=req.require_confirmation,
        max_steps=req.max_steps,
    )

    return AsyncAcceptedResponse(
        status="accepted",
        job_id=job_id,
        message="The task has been securely queued. Final execution payload will be delivered to the provided webhook.",
    )
