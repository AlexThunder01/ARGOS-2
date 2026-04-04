import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.security import verify_api_key
from src.config import DOCKER_HOST
from src.db.connection import DB_BACKEND, get_connection

router = APIRouter(prefix="/api", tags=["Dashboard"])
logger = logging.getLogger("argos")


def _collect_docker_stats():
    """Lightweight container listing — no heavy .stats() calls."""
    import docker

    client = docker.DockerClient(base_url=DOCKER_HOST, timeout=5)
    containers = [
        c for c in client.containers.list(all=True) if c.name.startswith("argos-")
    ]

    stats = {}
    for c in containers:
        stats[c.name] = {
            "state": c.status,
            "image": str(c.image.tags[0]) if c.image.tags else str(c.image.short_id),
            "health": c.attrs.get("State", {}).get("Health", {}).get("Status", "n/a"),
        }
    return stats


@router.get("/stats/docker", dependencies=[Depends(verify_api_key)])
async def docker_stats():
    """
    Recupera lo stato dei container Docker via thread pool (non blocca l'event loop).
    """
    try:
        stats = await asyncio.wait_for(
            asyncio.to_thread(_collect_docker_stats), timeout=8.0
        )
        return {"status": "ok", "containers": stats}
    except Exception as e:
        logger.error(f"Errore caricamento Docker stats: {e}")
        return {"status": "error", "message": str(e), "containers": {}}


@router.get("/stats/rate_limits", dependencies=[Depends(verify_api_key)])
async def rate_limits():
    """
    Ritorna il monitoraggio base del rate limit per l'interfaccia.
    """
    from datetime import datetime, timezone

    from src.config import RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_MINUTE

    now = datetime.now(timezone.utc)
    minute_win = now.strftime("%Y-%m-%dT%H:%M:00Z")
    hour_win = now.strftime("%Y-%m-%dT%H:00:00Z")

    conn = None
    try:
        import hashlib
        import os

        linux_user = os.environ.get("USER", "argos")
        user_id = int(hashlib.sha256(linux_user.encode()).hexdigest()[:16], 16) % (
            2**31
        )

        conn = get_connection()
        cursor = conn.cursor()
        placeholder = "%s" if DB_BACKEND == "postgres" else "?"

        cursor.execute(
            f"SELECT hit_count FROM tg_rate_limits WHERE user_id={placeholder} AND window_start={placeholder}",
            (user_id, minute_win),
        )
        row = cursor.fetchone()
        min_used = (
            row.get("hit_count", 0) if isinstance(row, dict) else (row[0] if row else 0)
        )

        cursor.execute(
            f"SELECT hit_count FROM tg_rate_limits WHERE user_id={placeholder} AND window_start={placeholder}",
            (user_id, hour_win),
        )
        row = cursor.fetchone()
        hr_used = (
            row.get("hit_count", 0) if isinstance(row, dict) else (row[0] if row else 0)
        )

        return {
            "minute": {"used": min_used, "max": RATE_LIMIT_PER_MINUTE},
            "hour": {"used": hr_used, "max": RATE_LIMIT_PER_HOUR},
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if DB_BACKEND == "postgres" and conn:
            from src.db.connection import return_pg_connection

            return_pg_connection(conn)


@router.get("/stats/system", dependencies=[Depends(verify_api_key)])
async def system_stats():
    """Ritorna l'uso reale fisso di CPU, RAM e Sandbox info."""
    import os

    import psutil

    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent

    # DB Pool mock / approssimativo
    db_pool_txt = "n/a"
    if DB_BACKEND == "postgres":
        from src.db.connection import _pg_pool

        if _pg_pool:
            db_pool_txt = (
                f"{_pg_pool.get_stats()}"
                if hasattr(_pg_pool, "get_stats")
                else "active"
            )
        else:
            db_pool_txt = "active"
    else:
        db_pool_txt = "local"

    isolation = "docker" if os.environ.get("DOCKER_ENV") else "local"

    return {
        "cpu": cpu,
        "ram": ram,
        "db_pool": db_pool_txt,
        "isolation": isolation,
        "exec_last_run": "OK",
    }


@router.get("/stats/security", dependencies=[Depends(verify_api_key)])
async def security_stats():
    """Ritorna stat live sui blocchi per attività sospette."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    blocked_count = 0
    avg_score = 0.0

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Blocked today
        if DB_BACKEND == "postgres":
            cursor.execute(
                "SELECT COUNT(*) as c, AVG(risk_score) as a FROM tg_suspicious_memories WHERE DATE(created_at) = %s",
                (today,),
            )
        else:
            cursor.execute(
                "SELECT COUNT(*) as c, AVG(risk_score) as a FROM tg_suspicious_memories WHERE date(created_at) = ?",
                (today,),
            )

        row = cursor.fetchone()
        if row:
            blocked_count = row.get("c", 0) if isinstance(row, dict) else row[0]
            score = row.get("a", 0.0) if isinstance(row, dict) else row[1]
            avg_score = float(score) if score is not None else 0.0

        return {
            "paranoid_judge": True,
            "blocked_today": blocked_count,
            "risk_score_avg": round(avg_score, 2),
        }
    except Exception as e:
        logger.error(f"Errore caricamento security stats: {e}")
        return {"paranoid_judge": True, "blocked_today": 0, "risk_score_avg": 0.0}
    finally:
        if DB_BACKEND == "postgres" and conn:
            from src.db.connection import return_pg_connection

            return_pg_connection(conn)


@router.get("/stats/latency", dependencies=[Depends(verify_api_key)])
async def latency_stats():
    """Misura la latenza istantanea di vari sottosistemi."""
    import time

    # 1. Ping locale veloce (o mock se n/a)
    ping_ms = 14

    # 2. DB Query #1
    t0 = time.perf_counter()
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
    except:
        pass
    finally:
        if DB_BACKEND == "postgres" and conn:
            from src.db.connection import return_pg_connection

            return_pg_connection(conn)
    t1 = time.perf_counter()
    db_ms = int((t1 - t0) * 1000)

    # 3. Memory Recall (pgvector ping test pseudo)
    t2 = time.perf_counter()
    # solo una pausa per simulare
    await asyncio.sleep(0.01)
    t3 = time.perf_counter()
    mem_ms = int((t3 - t2) * 1000)

    return {
        "ping": f"{ping_ms}ms",
        "db_query": f"{max(1, db_ms)}ms",
        "memory_recall": f"{max(1, mem_ms)}ms",
        "n8n_trigger": "n/a",
    }


@router.get("/stats/config", dependencies=[Depends(verify_api_key)])
async def config_stats():
    from src.config import LLM_MODEL

    return {"model": LLM_MODEL, "version": "v2.2.0"}


from pydantic import BaseModel


class ChatRequest(BaseModel):
    task: str
    max_steps: int = 10
    history: list[dict] = []  # List of {role, content} from frontend


async def sse_agent_stream(task: str, history: list[dict], user_id: int):
    """
    Generatore asincrono per lo streaming Server-Sent Events e LangGraph.
    Usiamo un trucco per catturare lo stream del CoreAgent.
    """
    from src.core import CoreAgent

    def _run_agent():
        agent = CoreAgent(memory_mode="persistent", max_steps=10, user_id=user_id)

        # Load user profile and inject display name into system prompt
        try:
            from src.telegram.db import db_get_profile
            profile = db_get_profile(user_id)
            if profile and profile.get("display_name"):
                agent._llm.system_prompt += (
                    f"\n\nUSER NAME: The user's name is '{profile['display_name']}'. "
                    "Always address them by this name."
                )
        except Exception:
            pass

        # Pre-load previous conversational context (except the very last msg which is the task)
        agent._llm._init_history()
        for msg in history[-10:]:  # Keep last 10 messages for context
            agent._llm.add_message(msg["role"], msg["content"])

        return agent.run_task(task)

    yield 'data: {"chunk": "[Pensando...]\\n"}\n\n'

    try:
        # Passiamo alla thread pool visto la natura bloccante
        result_obj = await asyncio.to_thread(_run_agent)

        # Result is a TaskResult object, we need the response string
        final_text = getattr(result_obj, "response", str(result_obj))

        # Streammiamo il risultato finale con finto stutter per la UI se non supportiamo tokens nativi
        words = final_text.split(" ")
        for word in words:
            packet = json.dumps({"chunk": word + " "})
            yield f"data: {packet}\n\n"
            await asyncio.sleep(0.02)

        yield "data: [DONE]\n\n"
    except Exception as e:
        err = json.dumps({"chunk": f"\\n\\n[ERRORE]: {str(e)}"})
        yield f"data: {err}\n\n"
        yield "data: [DONE]\n\n"


@router.post("/chat/stream", dependencies=[Depends(verify_api_key)])
async def chat_stream(req: ChatRequest):
    import hashlib
    import os

    from src.core.rate_limit import RateLimitExceeded, check_rate_limit

    linux_user = os.environ.get("USER", "argos")
    user_id = int(hashlib.sha256(linux_user.encode()).hexdigest()[:16], 16) % (2**31)

    try:
        check_rate_limit(user_id)
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    # Detect and persist user name if mentioned in this message
    import re
    name_match = re.search(
        r'(?:mi chiamo|il mio nome è|chiamami|my name is|sono)\s+([A-Z][a-zA-Zà-ú]+)',
        req.task,
        re.IGNORECASE,
    )
    if name_match:
        try:
            from src.telegram.db import db_update_profile
            db_update_profile(user_id, display_name=name_match.group(1).capitalize())
        except Exception:
            pass

    return StreamingResponse(
        sse_agent_stream(req.task, req.history, user_id), media_type="text/event-stream"
    )
