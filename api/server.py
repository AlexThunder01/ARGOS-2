"""
ARGOS REST API — FastAPI server for external integration (n8n, remote CLI, etc.)

Endpoints:
  POST /run          — Executes an autonomous task
  GET  /status       — System health check and backend status
  GET  /logs/last    — Retrieves the most recent session log file

Startup Command: uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
"""
import os
import sys
import json
import time
import logging
import glob
import uuid
import requests
from collections import defaultdict

# Append the root directory to the system path to locate the src/ modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, BackgroundTasks, Security, Depends, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager

from src.agent import JarvisAgent
from src.tools import TOOLS
from src.config import ENABLE_VOICE, LLM_BACKEND, MODEL_GROQ, MODEL_OLLAMA
from src.world_model.state import WorldState
from src.planner.planner import parse_planner_response
from src.executor.executor import execute_with_retry
from src.logging.tracer import setup_tracer, log_step, log_decision
from src.utils import extract_json

# --- Global Server State ---
_agent: JarvisAgent = None
_logger: logging.Logger = None
_metrics = defaultdict(int)
_metrics["start_time"] = time.time()

# --- Security Configuration ---
ARGOS_API_KEY = os.getenv("ARGOS_API_KEY", "").strip()
api_key_header = APIKeyHeader(name="X-ARGOS-API-KEY", auto_error=False)

async def verify_api_key(key: str = Security(api_key_header)):
    """Validates the incoming request's X-ARGOS-API-KEY header."""
    if not ARGOS_API_KEY:
        return # Permissive mode if no key is set in .env
    if key != ARGOS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: Invalid or missing API Key"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes the core agent upon server startup."""
    global _agent, _logger
    _logger = setup_tracer()
    _logger.info("🚀 ARGOS API Server Initialized")
    try:
        _agent = JarvisAgent()
        _logger.info(f"✅ Agent Ready [Backend: {_agent.backend}] [Model: {_agent.model}]")
    except Exception as e:
        _logger.error(f"❌ Failed to initialize the agent instance: {e}")
        _agent = None
    yield
    _logger.info("🛑 ARGOS API Server Shutdown")


app = FastAPI(
    title="ARGOS API",
    description="Autonomous Remote Grid Operating System — REST Interface",
    version="2.0.0",
    lifespan=lifespan,
)


# --- Request/Response Data Schemas ---

class TaskRequest(BaseModel):
    task: str = Field(..., description="Natural language task description to be executed")
    require_confirmation: bool = Field(
        default=False,
        description="If True, halts execution on dangerous actions (Remote HITL mode)"
    )
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
    history: list[StepRecord]
    backend: str
    model: str


class StatusResponse(BaseModel):
    status: str
    backend: str
    model: str
    agent_ready: bool


# --- Synchronous Task Execution Logic ---

MAX_DANGEROUS = [
    "create_file", "modify_file", "rename_file", "create_directory",
    "delete_directory", "delete_file", "visual_click", "keyboard_type", "launch_app"
]


def _run_task_sync(task: str, require_confirmation: bool, max_steps: int) -> TaskResponse:
    """Executes a complete task lifecycle and returns a structured TaskResponse."""
    global _agent, _logger

    if not _agent:
        raise HTTPException(status_code=503, detail="Agent instance unavailable.")

    state = WorldState()
    state.current_task = task
    _agent._init_history()
    _agent.add_message("user", task)

    final_result = ""
    step_records = []

    _metrics["tasks_total"] += 1
    for step_num in range(max_steps):
        # Think
        raw = _agent.think()
        decision = parse_planner_response(raw)

        log_decision(_logger, decision.thought, decision.tool or "done", decision.confidence)

        # Final Response Phase
        if decision.done:
            final_result = decision.response or raw
            _logger.info(f"✅ Task successfully completed in {step_num + 1} step(s).")
            break

        tool_name = decision.tool
        tool_input = decision.tool_input

        if not tool_name or tool_name not in TOOLS:
            final_result = f"Command restricted or unknown tool invoked: '{tool_name}'"
            break

        # Prevent dangerous actions when executed in API mode (interactive confirmation disabled)
        if require_confirmation and tool_name in MAX_DANGEROUS:
            final_result = f"Action '{tool_name}' automatically blocked (require_confirmation flag is True)"
            _logger.warning(f"Restricted action prevented: {tool_name}")
            break

        # Execute target tool utilizing retry architecture
        action_result = execute_with_retry(TOOLS[tool_name], tool_input, tool_name)
        state.record_action(tool_name, tool_input, action_result.message, action_result.success)
        log_step(_logger, state, tool_name, action_result.message, action_result.success)

        step_records.append(StepRecord(
            step=state.step_count,
            tool=tool_name,
            result=action_result.message[:200],
            success=action_result.success,
            timestamp=state.action_history[-1].timestamp,
        ))

        # Internal state feedback iteration
        _agent.add_message("assistant", json.dumps({"tool": tool_name, "input": tool_input}))
        _agent.add_message("user", f"TOOL EXECUTION RESULT: {action_result.message}")

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
        backend=_agent.backend,
        model=_agent.model,
    )

def _run_task_async_worker(job_id: str, webhook_url: str, task: str, req_conf: bool, max_steps: int):
    """Background dedicated worker orchestrator. Executes the task and dispatches results to n8n."""
    global _logger
    _logger.info(f"⏳ Async Job [{job_id}] initialized for target webhook: {webhook_url}")
    
    try:
        # Utilize the unified synchronous logic architecture to retrieve the base TaskResponse
        result: TaskResponse = _run_task_sync(task, req_conf, max_steps)
        payload = result.model_dump()
        payload["job_id"] = job_id
        
        # Forward execution payload to the automation hook
        _logger.info(f"📤 Dispatching Job result [{job_id}] to {webhook_url}")
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code >= 400:
            _logger.error(f"❌ Webhook dispatch failed for Job [{job_id}]: HTTP {resp.status_code} - {resp.text}")
        else:
            _logger.info(f"✅ Webhook successfully delivered for Job [{job_id}]")
            
    except Exception as e:
        _logger.error(f"❌ Critical exception caught in async job worker [{job_id}]: {e}")
        # Attempt hard fallback structural routing
        try:
            requests.post(webhook_url, json={"success": False, "job_id": job_id, "result": f"Internal Server Error: {e}"}, timeout=5)
        except:
            pass

@app.get("/metrics", tags=["System"], dependencies=[Depends(verify_api_key)])
async def get_metrics():
    """Provides real-time operational observability and performance metrics."""
    return {
        "uptime_seconds": time.time() - _metrics["start_time"],
        "tasks_executed": _metrics["tasks_total"],
        "emails_queued": _metrics["emails_queued"],
        "emails_deleted": _metrics["emails_deleted"],
        "pending_file_exists": os.path.exists(_PENDING_FILE)
    }

# --- Core Application Endpoints ---

@app.get("/health", tags=["System"])
async def health():
    """Diagnostic health check for Docker orchestration."""
    return {"status": "ok", "timestamp": time.time()}

@app.get("/status", response_model=StatusResponse, tags=["System"])
async def status():
    """Health check protocol: returns backend diagnostic state and LLM model initialization confirmation."""
    model = MODEL_GROQ if (_agent and _agent.backend == "groq") else MODEL_OLLAMA
    return StatusResponse(
        status="online",
        backend=LLM_BACKEND,
        model=model,
        agent_ready=_agent is not None,
    )


@app.post("/run", response_model=TaskResponse, tags=["Agent"], dependencies=[Depends(verify_api_key)])
async def run_task(req: TaskRequest):
    """
    Executes a standard synchronous autonomous cycle.
    
    - `task`: Descriptive natural language parameter string.
    - `require_confirmation`: Security halt for non-reversible OS destructive actions.
    - `max_steps`: Agent cognitive loop bounded limit.
    """
    try:
        return _run_task_sync(req.task, req.require_confirmation, req.max_steps)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error(f"Endpoint Exception /run: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/run_async", response_model=AsyncAcceptedResponse, status_code=202, tags=["Agent"], dependencies=[Depends(verify_api_key)])
async def run_task_async(req: TaskAsyncRequest, background_tasks: BackgroundTasks):
    """
    Initializes a background detached job stream preventing long-polling n8n upstream timeouts.
    
    - `webhook_url`: Terminal n8n execution target node URL.
    - `task`: Objective prompt.
    """
    if not _agent:
        raise HTTPException(status_code=503, detail="Agent instance currently unavailable.")
        
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

# --- Persistent Email Queue Logic (Dedicated HITL architecture) ---
_PENDING_FILE = "/tmp/argos_pending_reply.json"

@app.post("/pending_email", tags=["Email HITL"], dependencies=[Depends(verify_api_key)])
async def store_pending_email(data: dict):
    """Generates a persisted context index linking metadata dictionary payloads directly to thread message IDs."""
    import json as _json
    import os as _os
    
    store = {}
    if _os.path.exists(_PENDING_FILE):
        try:
            with open(_PENDING_FILE, "r", encoding="utf-8") as f:
                store = _json.load(f)
                if isinstance(store, list):
                    store = {} # Overwrite inherited legacy datatype architecture
        except:
            store = {}
            
    msg_id = data.get("messageId", "default")
    store[msg_id] = data
    
    with open(_PENDING_FILE, "w", encoding="utf-8") as f:
        _json.dump(store, f, ensure_ascii=False)
        
    _metrics["emails_queued"] += 1
    _logger.info(f"📧 Active Context Queued: ID {msg_id} (Allocated heap index count: {len(store)})")
    return {"status": "saved", "sender": data.get("sender", ""), "queue_size": len(store)}

@app.delete("/pending_email", tags=["Email HITL"], dependencies=[Depends(verify_api_key)])
async def delete_pending_email(message_id: str):
    """Query, extract, and synchronously destruct email queues bounded to explicitly defined IDs."""
    import json as _json
    import os as _os
    try:
        with open(_PENDING_FILE, "r", encoding="utf-8") as f:
            store = _json.load(f)
            
        if not isinstance(store, dict):
            return {"status": "empty", "reason": "invalid_store"}
            
        if message_id not in store:
            return {"status": "empty", "reason": "not_found"}
            
        data = store.pop(message_id) # Estrai e cancella
        
        with open(_PENDING_FILE, "w", encoding="utf-8") as f:
            _json.dump(store, f, ensure_ascii=False)
            
        _metrics["emails_deleted"] += 1
        return {**data, "status": "deleted", "remaining": len(store)}
    except Exception as e:
        return {"status": "empty", "reason": str(e)}


@app.get("/logs/last", tags=["System"], dependencies=[Depends(verify_api_key)])
async def last_log():
    """Ritorna il contenuto dell'ultimo file di log della sessione."""
    log_files = sorted(glob.glob("logs/argos_*.log"))
    if not log_files:
        raise HTTPException(status_code=404, detail="Nessun log disponibile.")
    with open(log_files[-1], "r", encoding="utf-8") as f:
        lines = f.readlines()
    return JSONResponse({"log_file": log_files[-1], "lines": lines[-100:]})  # ultimi 100 righe
