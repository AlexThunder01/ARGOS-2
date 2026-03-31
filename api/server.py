"""
ARGOS REST API — FastAPI server for external integration (n8n, remote CLI, etc.)
End-to-end refactored.
"""
import os
import sys
import logging
import time
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import JSONResponse
from src.db.connection import get_connection
from src.logging.tracer import setup_tracer
from api.security import verify_api_key

logger = logging.getLogger("argos")

def init_db():
    try:
        conn = get_connection()
        conn.execute('''CREATE TABLE IF NOT EXISTS pending_emails (
            msg_id TEXT PRIMARY KEY,
            payload TEXT
        )''')
        conn.commit()
    except Exception as e:
        print(f"❌ Failed to initialize SQLite database: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global logger
    logger = setup_tracer()
    logger.info("🚀 ARGOS API Server Initialized")
    init_db()
    yield
    logger.info("🛑 ARGOS API Server Shutdown")

app = FastAPI(
    title="ARGOS API",
    description="Autonomous Remote Grid Operating System — REST Interface",
    version="2.0.0",
    lifespan=lifespan,
)

from api.routes import agent, email, telegram, admin

app.include_router(agent.router)
app.include_router(email.router)
app.include_router(telegram.router)
app.include_router(admin.router)

@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "timestamp": time.time()}

@app.get("/metrics", tags=["System"], dependencies=[Depends(verify_api_key)])
async def get_metrics():
    return {
        "status": "online",
        "message": "Metrics endpoint refactored. Realtime counters moved to logger/monitoring tools."
    }

@app.get("/logs/last", tags=["System"], dependencies=[Depends(verify_api_key)])
async def last_log():
    import glob
    log_files = sorted(glob.glob("logs/argos_*.log"))
    if not log_files:
        raise HTTPException(status_code=404, detail="Nessun log disponibile.")
    with open(log_files[-1], "r", encoding="utf-8") as f:
        lines = f.readlines()
    return JSONResponse({"log_file": log_files[-1], "lines": lines[-100:]})
