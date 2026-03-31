import uuid
import logging
import asyncio
import time
import requests
import pybreaker
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from api.security import verify_api_key
from src.agent import JarvisAgent
from src.tools import TOOLS
from src.config import LLM_BACKEND, LLM_MODEL
from src.world_model.state import WorldState
from src.planner.planner import parse_planner_response
from src.executor.executor import execute_with_retry
from src.logging.tracer import log_step, log_decision

router = APIRouter(tags=["Agent"])
logger = logging.getLogger("argos")

llm_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60)

MAX_DANGEROUS = [
    "create_file", "modify_file", "rename_file", "create_directory",
    "delete_directory", "delete_file", "visual_click", "keyboard_type", "launch_app"
]

class TaskRequest(BaseModel):
    task: str = Field(..., description="Natural language task description to be executed")
    require_confirmation: bool = Field(default=False, description="If True, halts execution on dangerous actions")
    max_steps: int = Field(default=5, ge=1, le=20, description="Maximum internal step bound")

class TaskAsyncRequest(TaskRequest):
    webhook_url: str = Field(..., description="Target n8n webhook URL to receive the post-execution payload")

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

def _run_task_sync(task: str, require_confirmation: bool, max_steps: int) -> TaskResponse:
    local_agent = JarvisAgent()
    state = WorldState()
    state.current_task = task
    local_agent._init_history()
    local_agent.add_message("user", task)

    final_result = ""
    step_records = []

    for step_num in range(max_steps):
        try:
            raw = llm_breaker.call(local_agent.think)
        except pybreaker.CircuitBreakerError:
            final_result = "Step execution failure: LLM Service is unavailable (Circuit Breaker OPEN)"
            logger.error("🛑 LLM Circuit Breaker tripped. Failing fast.")
            break
            
        decision = parse_planner_response(raw)

        log_decision(logger, decision.thought, decision.tool or "done", decision.confidence)

        if decision.done:
            final_result = decision.response or raw
            logger.info(f"✅ Task successfully completed in {step_num + 1} step(s).")
            break

        tool_name = decision.tool
        tool_input = decision.tool_input

        if not tool_name or tool_name not in TOOLS:
            final_result = f"Command restricted or unknown tool invoked: '{tool_name}'"
            break

        if require_confirmation and tool_name in MAX_DANGEROUS:
            final_result = f"Action '{tool_name}' automatically blocked (require_confirmation flag is True)"
            logger.warning(f"Restricted action prevented: {tool_name}")
            break

        action_result = execute_with_retry(TOOLS[tool_name], tool_input, tool_name)
        state.record_action(tool_name, tool_input, action_result.message, action_result.success)
        log_step(logger, state, tool_name, action_result.message, action_result.success)

        step_records.append(StepRecord(
            step=state.step_count,
            tool=tool_name,
            result=action_result.message[:200],
            success=action_result.success,
            timestamp=state.action_history[-1].timestamp,
        ))

        local_agent.add_message("assistant", f'{{"tool": "{tool_name}", "input": {tool_input}}}')
        local_agent.add_message("user", f"TOOL EXECUTION RESULT: {action_result.message}")

        if action_result.success:
            final_result = action_result.message
        else:
            final_result = f"Step execution failure at {state.step_count}: {action_result.message}"

    return TaskResponse(
        success=not final_result.startswith("Step execution failure"),
        task=task,
        steps_executed=state.step_count,
        result=final_result,
        history=step_records,
        backend=local_agent.backend,
        model=local_agent.model,
    )

def _run_task_async_worker(job_id: str, webhook_url: str, task: str, req_conf: bool, max_steps: int):
    logger.info(f"⏳ Async Job [{job_id}] initialized for target webhook: {webhook_url}")
    
    try:
        result: TaskResponse = _run_task_sync(task, req_conf, max_steps)
        payload = result.model_dump()
        payload["job_id"] = job_id
        
        logger.info(f"📤 Dispatching Job result [{job_id}] to {webhook_url}")
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code >= 400:
            logger.error(f"❌ Webhook dispatch failed for Job [{job_id}]: HTTP {resp.status_code} - {resp.text}")
        else:
            logger.info(f"✅ Webhook successfully delivered for Job [{job_id}]")
            
    except Exception as e:
        logger.error(f"❌ Critical exception caught in async job worker [{job_id}]: {e}")
        try:
            requests.post(webhook_url, json={"success": False, "job_id": job_id, "result": f"Internal Server Error: {e}"}, timeout=5)
        except:
            pass

@router.get("/status", response_model=StatusResponse, tags=["System"])
async def status():
    return StatusResponse(
        status="online",
        backend=LLM_BACKEND,
        model=LLM_MODEL,
        agent_ready=True,
    )

@router.post("/run", response_model=TaskResponse, dependencies=[Depends(verify_api_key)])
async def run_task(req: TaskRequest):
    try:
        # Wrap blocking execution in thread
        return await asyncio.to_thread(_run_task_sync, req.task, req.require_confirmation, req.max_steps)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Endpoint Exception /run: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/run_async", response_model=AsyncAcceptedResponse, status_code=202, dependencies=[Depends(verify_api_key)])
async def run_task_async(req: TaskAsyncRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())[:8]
    
    background_tasks.add_task(
        _run_task_async_worker,
        job_id=job_id,
        webhook_url=req.webhook_url,
        task=req.task,
        req_conf=req.require_confirmation,
        max_steps=req.max_steps
    )
    
    return AsyncAcceptedResponse(
        status="accepted",
        job_id=job_id,
        message="The task has been securely queued. Final execution payload will be sequentially delivered to the provided webhook."
    )
