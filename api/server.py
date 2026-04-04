"""
ARGOS REST API — FastAPI server for external integration (n8n, remote CLI, etc.)
End-to-end refactored with OTel tracing and PostgreSQL support.
"""

import logging
import os
import sys
import time
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from api.security import verify_api_key
from src.db.connection import DB_BACKEND, get_connection
from src.logging.otel import init_otel
from src.logging.tracer import setup_tracer

logger = logging.getLogger("argos")


def init_db():
    try:
        conn = get_connection()
        if DB_BACKEND == "sqlite":
            conn.execute("""CREATE TABLE IF NOT EXISTS pending_emails (
                msg_id TEXT PRIMARY KEY,
                payload TEXT
            )""")
            conn.commit()
        # PostgreSQL schema is auto-initialized via docker-entrypoint-initdb.d
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global logger
    logger = setup_tracer()

    # Initialize OpenTelemetry tracing
    init_otel()

    # Instrument FastAPI (if OTel packages available)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("📡 FastAPI auto-instrumented with OpenTelemetry")
    except ImportError:
        logger.info("📡 OpenTelemetry FastAPI instrumentation not available (skipped)")

    # Initialize async DB pool for PostgreSQL
    if DB_BACKEND == "postgres":
        try:
            from src.db.connection import close_async_pool, init_async_pool

            app.state.db_pool = await init_async_pool()
            logger.info("🐘 PostgreSQL async pool initialized in lifespan")
        except Exception as e:
            logger.warning(f"🐘 Async pool init failed (sync fallback active): {e}")
            app.state.db_pool = None

    logger.info("🚀 ARGOS API Server Initialized")
    init_db()
    yield

    # Shutdown
    if DB_BACKEND == "postgres" and hasattr(app.state, "db_pool") and app.state.db_pool:
        from src.db.connection import close_async_pool

        await close_async_pool(app.state.db_pool)

    logger.info("🛑 ARGOS API Server Shutdown")


app = FastAPI(
    title="ARGOS API",
    description="Autonomous Remote Grid Operating System — REST Interface",
    version="2.1.0",
    lifespan=lifespan,
)

from api.routes import admin, agent, dashboard, email, telegram

app.include_router(agent.router)
app.include_router(email.router)
app.include_router(telegram.router)
app.include_router(admin.router)
app.include_router(dashboard.router)

import os

from fastapi.staticfiles import StaticFiles

if os.path.isdir("dashboard/dist"):
    app.mount(
        "/", StaticFiles(directory="dashboard/dist", html=True), name="dashboard_ui"
    )


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/metrics", tags=["System"], dependencies=[Depends(verify_api_key)])
async def get_metrics():
    return {
        "status": "online",
        "message": "Metrics endpoint refactored. Realtime counters moved to logger/monitoring tools.",
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
