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
import sqlite3
import pybreaker
from src.db.connection import get_connection, DB_PATH

# --- File System & DB Config ---
DB_DIR = "/app/data" if os.environ.get("DOCKER_ENV") else "./data"
os.makedirs(DB_DIR, exist_ok=True)

# --- Circuit Breaker ---
# Fails fast for 60 seconds after 3 consecutive LLM timeouts
llm_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60)

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


def init_db():
    """Initializes the SQLite state database ensuring safe WAL mode concurrency."""
    try:
        conn = get_connection()
        conn.execute('''CREATE TABLE IF NOT EXISTS pending_emails (
            msg_id TEXT PRIMARY KEY,
            payload TEXT
        )''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"❌ Failed to initialize SQLite database: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes the core agent and database upon server startup."""
    global _agent, _logger
    _logger = setup_tracer()
    _logger.info("🚀 ARGOS API Server Initialized")
    
    # Init Database
    init_db()
    
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
        # Think with Circuit Breaker
        try:
            raw = llm_breaker.call(_agent.think)
        except pybreaker.CircuitBreakerError:
            final_result = "Step execution failure: LLM Service is unavailable (Circuit Breaker OPEN)"
            _logger.error("🛑 LLM Circuit Breaker tripped. Failing fast.")
            break
            
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

class EmailAnalyzeRequest(BaseModel):
    sender: str
    subject: str
    body: str

@app.post("/analyze_email", tags=["Email HITL"], dependencies=[Depends(verify_api_key)])
async def analyze_email(req: EmailAnalyzeRequest):
    """
    Dynamically categorizes and evaluates incoming emails based on the central config.yaml.
    """
    from src.workflows_config import config
    import re

    # 1. Global Killswitch
    if not config.is_gmail_enabled:
        return {"status": "ignored", "reason": "gmail_assistant is disabled in config.yaml"}

    # 2. Sender Filtering
    for pattern in config.ignore_senders:
        regex_pattern = pattern.replace("*", ".*")
        if re.search(regex_pattern, req.sender, re.IGNORECASE):
            _logger.info(f"🚫 Email ignored: sender {req.sender} matches blacklist pattern {pattern}")
            return {"status": "ignored", "reason": "sender_blacklisted"}

    # 3. Dynamic Prompt Construction
    prompt = f"""Analyze the following email. Respond EXACTLY in this textual format (DO NOT use JSON):

PRIORITY: [high/medium/low/spam]
SUMMARY: [summarize the sender's request in 1-2 sentences. If spam, write 'Spam detected.']
DRAFT RESPONSE:
[draft a polite response in the SAME LANGUAGE as the original email. Tone: {config.tone_of_voice}. End the response with: {config.custom_signature}. If spam, write 'ignored'.]

### GREETING & PERSONA INSTRUCTIONS:
1. You are responding on behalf of the owner of this inbox. Speak natively in the first person (e.g., "I will check this", "Thank you for reaching out to me").
2. ALWAYS greet the sender by their actual Name if it is available in the SENDER field (e.g., "Dear Alessandro", "Buongiorno Marco").
3. NEVER address the sender by their raw email address (e.g., do NOT write "Gentile catania.alex3@gmail.com").
4. If no human name is found in the SENDER field, use a generic polite greeting without a name (e.g., "Buongiorno," or "Dear customer,").

"""
    if config.allowed_languages:
        prompt += f"IMPORTANT: Only process this if the email is primarily in one of these languages: {', '.join(config.allowed_languages)}. If not, set PRIORITY: low and DRAFT RESPONSE: ignored.\n\n"

    prompt += f"Do not hallucinate information. Base your response strictly on the provided text.\n\nSENDER: {req.sender}\nSUBJECT: {req.subject}\nBODY: {req.body}"

    # 4. LLM Execution
    try:
        result = _run_task_sync(prompt, require_confirmation=False, max_steps=3)
        result_text = result.result
        
        # 5. Parsing & Schema Validation
        import re as regex
        imp_match = regex.search(r'PRIORITY:\s*(\S+)', result_text, regex.IGNORECASE)
        importanza = imp_match.group(1).upper() if imp_match else 'MEDIUM'
        
        # Schema verification defense
        allowed_priorities = {"HIGH", "MEDIUM", "LOW", "SPAM"}
        if importanza not in allowed_priorities:
            _logger.warning(f"⚠️ LLM hallucinated priority '{importanza}'. Falling back to LOW.")
            importanza = "LOW"
        
        # Priority Threshold Engine
        priority_map = {"HIGH": 4, "MEDIUM": 3, "LOW": 2, "SPAM": 1}
        email_prio_val = priority_map.get(importanza, 3) # default mapping fallback
        min_prio_val = priority_map.get(config.min_priority, 2) # defaults to LOW if not set

        if email_prio_val < min_prio_val:
            _logger.info(f"🚫 Email ignored: Priority '{importanza}' is below threshold '{config.min_priority}'")
            return {"status": "ignored", "reason": f"priority_below_threshold ({importanza})"}

        rias_match = regex.search(r'SUMMARY:\s*(.+?)(?=\nDRAFT|$)', result_text, regex.IGNORECASE | regex.DOTALL)
        riassunto = rias_match.group(1).strip() if rias_match else ''
        
        draft_match = regex.search(r'DRAFT RESPONSE:\s*\n?([\s\S]*)', result_text, regex.IGNORECASE)
        draft = draft_match.group(1).strip() if draft_match else result_text

        return {
            "status": "success",
            "priority": importanza.lower(),
            "summary": riassunto,
            "draft": draft
        }
    except Exception as e:
        _logger.error(f"Error in /analyze_email: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Persistent Email Queue Logic (Dedicated HITL architecture) ---

@app.post("/pending_email", tags=["Email HITL"], dependencies=[Depends(verify_api_key)])
async def store_pending_email(data: dict):
    """Generates a persisted context index linking metadata dictionary payloads directly to thread message IDs in SQLite."""
    import json as _json
    import os as _os
    
    msg_id = data.get("messageId", "default")
    payload_str = _json.dumps(data, ensure_ascii=False)
    
    try:
        conn = get_connection()
        # Using INSERT OR REPLACE to handle unexpected upstream retries gracefully
        conn.execute("INSERT OR REPLACE INTO pending_emails (msg_id, payload) VALUES (?, ?)", (msg_id, payload_str))
        conn.commit()
    except sqlite3.Error as e:
        _logger.error(f"SQLite Write Error: {e}")
        return {"status": "error", "reason": "database_write_error"}
        
    _metrics["emails_queued"] += 1
    _logger.info(f"📧 Active Context Queued in SQLite: ID {msg_id}")
    return {"status": "saved", "sender": data.get("sender", "")}

@app.post("/pending_email/{message_id}/consume", tags=["Email HITL"], dependencies=[Depends(verify_api_key)])
async def consume_pending_email(message_id: str):
    """Atomic SELECT and DELETE operation. Neutralizes replay-attacks by returning 404 if context doesn't exist."""
    import json as _json
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Standard SELECT and delayed DELETE inside a transaction
        cursor.execute("SELECT payload FROM pending_emails WHERE msg_id = ?", (message_id,))
        row = cursor.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Email context not found or already consumed.")
            
        data = _json.loads(row[0])
        cursor.execute("DELETE FROM pending_emails WHERE msg_id = ?", (message_id,))
        conn.commit()
        
        _metrics["emails_deleted"] += 1
        return {**data, "status": "deleted_and_consumed"}
        
    except sqlite3.Error as e:
        _logger.error(f"SQLite Read/Delete Error: {e}")
        raise HTTPException(status_code=500, detail="State architecture failure")


@app.get("/logs/last", tags=["System"], dependencies=[Depends(verify_api_key)])
async def last_log():
    """Ritorna il contenuto dell'ultimo file di log della sessione."""
    log_files = sorted(glob.glob("logs/argos_*.log"))
    if not log_files:
        raise HTTPException(status_code=404, detail="Nessun log disponibile.")
    with open(log_files[-1], "r", encoding="utf-8") as f:
        lines = f.readlines()
    return JSONResponse({"log_file": log_files[-1], "lines": lines[-100:]})


# ==============================================================================
# TELEGRAM CHAT MODULE
# ==============================================================================

# --- Telegram Pydantic Schemas ---

class TelegramChatRequest(BaseModel):
    user_id: int = Field(..., description="Telegram user_id (immutable)")
    chat_id: int = Field(..., description="Telegram chat_id for the reply")
    text: str = Field(..., description="User message text")
    first_name: str = Field(default="", description="Telegram first name")
    username: str = Field(default="", description="Telegram @username (optional)")

class TelegramChatResponse(BaseModel):
    status: str  # 'ok' | 'unauthorized' | 'pending' | 'banned' | 'disabled'
    reply: str
    user_id: int
    memories_used: int = 0
    is_new_user: bool = False

class AdminActionRequest(BaseModel):
    admin_chat_id: int
    target_user_id: int
    reason: str = ""


# --- Telegram Slash Command Handler ---

def _handle_telegram_command(text: str, user_id: int, config) -> str | None:
    """Handles slash commands without invoking the LLM. Returns response or None."""
    from src.telegram.db import (
        db_clear_conversation_window, db_get_user_stats,
        db_delete_user_data, db_update_profile, db_get_open_tasks
    )

    if not text.startswith("/"):
        return None

    parts = text.split()
    cmd = parts[0].lower().split("@")[0]  # Strip @botname suffix

    if cmd == "/start":
        return config.telegram_welcome_message

    elif cmd == "/help":
        return (
            "📋 *Available commands:*\n"
            "/reset — Clear current session context\n"
            "/status — View your statistics\n"
            "/language it|en|... — Change language\n"
            "/tone formal|casual|neutral — Change tone\n"
            "/name <name> — Set your preferred name\n"
            "/tasks — Your open tasks\n"
            "/deleteme CONFIRM — Delete all your data"
        )

    elif cmd == "/reset":
        db_clear_conversation_window(user_id)
        return "✅ Session context cleared. Let's start fresh."

    elif cmd == "/status":
        stats = db_get_user_stats(user_id)
        return (
            f"👤 *Your profile:*\n"
            f"Status: ✅ Approved\n"
            f"Total messages: {stats['msg_count']}\n"
            f"Saved memories: {stats['memory_count']}\n"
            f"Open tasks: {stats['open_tasks']}\n"
            f"Member since: {stats['registered_at']}"
        )

    elif cmd == "/deleteme":
        if len(parts) > 1 and parts[1].upper() == "CONFIRM":
            db_delete_user_data(user_id)
            return (
                "🗑️ All your data has been permanently deleted.\n"
                "Your access has been revoked. Send a message to request approval again."
            )
        else:
            return (
                "⚠️ This will *permanently delete ALL* your data "
                "(conversations, memories, preferences, tasks).\n\n"
                "Type `/deleteme CONFIRM` to proceed."
            )

    elif cmd == "/language" and len(parts) > 1:
        lang = parts[1][:5]
        db_update_profile(user_id, language=lang)
        return f"✅ Language set to: {lang}"

    elif cmd == "/tone" and len(parts) > 1:
        tone = parts[1].lower()
        if tone not in ("formal", "casual", "neutral"):
            return "❌ Invalid tone. Use: formal | casual | neutral"
        db_update_profile(user_id, preferred_tone=tone)
        return f"✅ Tone set to: {tone}"

    elif cmd == "/name" and len(parts) > 1:
        name = " ".join(parts[1:])[:50]
        db_update_profile(user_id, display_name=name)
        return f"✅ I'll call you {name}."

    elif cmd == "/tasks":
        tasks = db_get_open_tasks(user_id)
        if not tasks:
            return "📋 No open tasks."
        lines = "\n".join(f"• {t['description']}" for t in tasks)
        return f"📋 *Open tasks:*\n{lines}"

    return None  # Not a recognized command → pass to LLM


# --- Admin Notification Helper ---

def _notify_admin_new_user(user_id: int, first_name: str, username: str):
    """Sends a notification to the admin via the existing HITL Telegram bot."""
    admin_chat_id = os.getenv("ADMIN_CHAT_ID", "").strip()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not admin_chat_id or not bot_token:
        _logger.warning("[Telegram] Cannot notify admin: ADMIN_CHAT_ID or TELEGRAM_BOT_TOKEN not set.")
        return
    text = (
        f"🆕 *New chat access request*\n\n"
        f"👤 Name: {first_name}\n"
        f"🔗 Username: @{username or 'none'}\n"
        f"🆔 User ID: `{user_id}`\n\n"
        f"To approve, send:\n`/approve_{user_id}`"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": admin_chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        _logger.error(f"[Telegram] Admin notification failed: {e}")


# --- Main Telegram Chat Endpoint ---

@app.post("/telegram/chat", response_model=TelegramChatResponse,
          tags=["Telegram"], dependencies=[Depends(verify_api_key)])
async def telegram_chat(req: TelegramChatRequest, background_tasks: BackgroundTasks):
    """
    Processes a single Telegram conversational turn.
    Handles: whitelist verification, memory retrieval (RAG), LLM call, memory extraction.
    """
    from src.workflows_config import get_workflows_config
    from src.telegram.db import (
        db_get_user, db_register_user, db_approve_user,
        db_get_profile, db_get_conversation_window,
        db_save_conversation_turn, db_increment_msg_count,
        db_get_open_tasks, db_gc_memories, db_get_all_memory_blobs
    )
    from src.telegram.memory import (
        retrieve_relevant_memories, should_extract_memory,
        should_run_gc, extract_memories_from_text, save_extracted_memories
    )
    from src.telegram.prompt import build_telegram_system_prompt

    config = get_workflows_config()

    # 1. Master switch
    if not config.is_telegram_enabled:
        return TelegramChatResponse(
            status="disabled", reply="The bot is temporarily disabled.",
            user_id=req.user_id
        )

    # 2. Input validation
    max_len = config.telegram_max_input_length
    if len(req.text) > max_len:
        return TelegramChatResponse(
            status="ok",
            reply=f"⚠️ Message too long ({len(req.text)} chars). Maximum: {max_len}.",
            user_id=req.user_id
        )

    # 3. Whitelist check
    user = db_get_user(req.user_id)

    if user is None:
        db_register_user(req.user_id, req.first_name, req.username)
        if config.telegram_auto_approve:
            db_approve_user(req.user_id)
        else:
            if config.telegram_notify_on_new_user:
                background_tasks.add_task(_notify_admin_new_user, req.user_id, req.first_name, req.username)
            return TelegramChatResponse(
                status="pending", reply=config.telegram_unauthorized_message,
                user_id=req.user_id, is_new_user=True
            )
        user = db_get_user(req.user_id)

    elif user["status"] == "pending":
        return TelegramChatResponse(
            status="pending", reply="Your access request is still pending approval.",
            user_id=req.user_id
        )

    elif user["status"] == "banned":
        _logger.info(f"[Telegram] Message from banned user {req.user_id} — silenced.")
        return TelegramChatResponse(
            status="banned", reply="", user_id=req.user_id
        )

    # 4. Handle slash commands (no LLM call)
    cmd_response = _handle_telegram_command(req.text, req.user_id, config)
    if cmd_response is not None:
        return TelegramChatResponse(
            status="ok", reply=cmd_response, user_id=req.user_id
        )

    # 5. Increment message counter
    db_increment_msg_count(req.user_id)
    msg_count = (user.get("msg_count_total", 0) or 0) + 1

    # 6. Retrieve context
    user_profile = db_get_profile(req.user_id)
    recent_history = db_get_conversation_window(
        req.user_id, limit=config.telegram_conversation_window
    )
    relevant_memories = retrieve_relevant_memories(
        req.user_id, req.text,
        top_k=config.telegram_max_memories,
        min_similarity=config.telegram_rag_threshold
    )
    open_tasks = db_get_open_tasks(req.user_id)

    # 7. Build prompt and call LLM
    system_prompt = build_telegram_system_prompt(
        bot_config=config.telegram_config,
        user_profile=user_profile,
        memories=relevant_memories,
        tasks=open_tasks
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": req.text})

    try:
        raw_reply = llm_breaker.call(_agent.think_with_messages, messages)
    except pybreaker.CircuitBreakerError:
        return TelegramChatResponse(
            status="ok",
            reply="⚠️ Service temporarily unavailable. Please try again in a minute.",
            user_id=req.user_id
        )

    # 8. Persist conversation turn (background)
    background_tasks.add_task(db_save_conversation_turn, req.user_id, req.text, raw_reply)

    # 9. Debounced memory extraction (background)
    if should_extract_memory(req.text, msg_count):
        # Read anti-poisoning config
        tg_cfg = config.telegram_config if hasattr(config, 'telegram_config') else {}
        beh_cfg = tg_cfg.get("behavior", {}) if isinstance(tg_cfg, dict) else {}
        mem_cfg = beh_cfg.get("memory", {})
        _poisoning_on = mem_cfg.get("enable_poisoning_detection", True)
        _risk_thresh = mem_cfg.get("risk_threshold", 0.5)
        _susp_ret = mem_cfg.get("suspicious_retention", 500)
        def _do_extraction():
            existing = [{"content": m["content"], "category": m["category"]} for m in relevant_memories]
            facts = extract_memories_from_text(req.text, existing, _agent.call_lightweight)
            if facts:
                save_extracted_memories(
                    req.user_id, facts,
                    llm_call_fn=_agent.call_lightweight,
                    poisoning_enabled=_poisoning_on,
                    risk_threshold=_risk_thresh,
                    suspicious_retention=_susp_ret
                )
        background_tasks.add_task(_do_extraction)

    # 10. Memory GC (background, periodic)
    if should_run_gc(msg_count):
        background_tasks.add_task(db_gc_memories, req.user_id)

    _metrics["telegram_messages_total"] = _metrics.get("telegram_messages_total", 0) + 1

    # 11. Sanitize markdown from LLM output (Telegram plain-text safety)
    clean_reply = _strip_markdown(raw_reply)

    return TelegramChatResponse(
        status="ok", reply=clean_reply, user_id=req.user_id,
        memories_used=len(relevant_memories)
    )


import re

def _strip_markdown(text: str) -> str:
    """Strips Markdown formatting that would break Telegram plain-text delivery."""
    text = re.sub(r'```[\s\S]*?```', lambda m: m.group(0).strip('`'), text)  # code blocks
    text = re.sub(r'`([^`]+)`', r'\1', text)          # inline code
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.M) # headers
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)      # **bold**
    text = re.sub(r'__(.+?)__', r'\1', text)           # __bold__
    text = re.sub(r'\*(.+?)\*', r'\1', text)           # *italic*
    text = re.sub(r'_(.+?)_', r'\1', text)             # _italic_
    return text


# --- Telegram Admin Endpoints ---

def _get_admin_chat_id() -> str:
    """Reads ADMIN_CHAT_ID dynamically from the environment."""
    return os.getenv("ADMIN_CHAT_ID", "0").strip()

@app.post("/telegram/admin/approve", tags=["Telegram Admin"], dependencies=[Depends(verify_api_key)])
async def admin_approve_user(req: AdminActionRequest):
    """Approves a pending user. Verifies that the requester is admin."""
    from src.telegram.db import db_approve_user
    if str(req.admin_chat_id) != _get_admin_chat_id():
        raise HTTPException(status_code=403, detail="Not admin.")
    db_approve_user(req.target_user_id, approved_by=req.admin_chat_id)
    return {"status": "approved", "user_id": req.target_user_id}


@app.post("/telegram/admin/ban", tags=["Telegram Admin"], dependencies=[Depends(verify_api_key)])
async def admin_ban_user(req: AdminActionRequest):
    """Bans a user."""
    from src.telegram.db import db_ban_user
    if str(req.admin_chat_id) != _get_admin_chat_id():
        raise HTTPException(status_code=403, detail="Not admin.")
    db_ban_user(req.target_user_id, reason=req.reason)
    return {"status": "banned", "user_id": req.target_user_id}


@app.get("/telegram/admin/users", tags=["Telegram Admin"], dependencies=[Depends(verify_api_key)])
async def admin_list_users(status_filter: str = "pending"):
    """Lists users filtered by status: pending | approved | banned"""
    from src.telegram.db import db_list_users
    if status_filter not in ("pending", "approved", "banned"):
        raise HTTPException(status_code=400, detail="Invalid status filter.")
    return {"users": db_list_users(status_filter)}


@app.get("/telegram/admin/suspicious", tags=["Telegram Admin"], dependencies=[Depends(verify_api_key)])
async def admin_suspicious_memories(admin_chat_id: int, limit: int = 50, offset: int = 0):
    """Returns paginated suspicious memory attempts. Requires admin auth."""
    from src.telegram.db import db_get_suspicious
    if str(admin_chat_id) != _get_admin_chat_id():
        raise HTTPException(status_code=403, detail="Not admin.")
    if limit > 100:
        limit = 100
    return {"suspicious": db_get_suspicious(limit=limit, offset=offset)}
