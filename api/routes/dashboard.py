import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse

from api.security import verify_api_key
from src.config import DOCKER_HOST
from src.db.connection import DB_BACKEND, get_connection

router = APIRouter(prefix="/api", tags=["Dashboard"])
logger = logging.getLogger("argos")


def _collect_docker_stats():
    """Blocking function that collects Docker container stats."""
    import docker

    client = docker.DockerClient(base_url=DOCKER_HOST)
    containers = client.containers.list()

    stats = {}
    for c in containers:
        c_stats = c.stats(stream=False)

        cpu_delta = (
            c_stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - c_stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_cpu_delta = c_stats["cpu_stats"].get("system_cpu_usage", 0) - c_stats[
            "precpu_stats"
        ].get("system_cpu_usage", 0)

        cpu_percent = 0.0
        if system_cpu_delta > 0.0 and cpu_delta > 0.0:
            cpu_percent = (cpu_delta / system_cpu_delta) * 100.0

        mem_usage = c_stats["memory_stats"].get("usage", 0)

        stats[c.name] = {
            "state": c.status,
            "cpu_usage": f"{cpu_percent:.2f}%",
            "mem_usage": f"{mem_usage / 1024 / 1024:.2f}MB",
        }
    return stats


@router.get("/stats/docker", dependencies=[Depends(verify_api_key)])
async def docker_stats():
    """
    Recupera risorse container Docker via thread pool (non blocca l'event loop).
    """
    try:
        stats = await asyncio.to_thread(_collect_docker_stats)
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
        conn = get_connection()
        cursor = conn.cursor()
        placeholder = "%s" if DB_BACKEND == "postgres" else "?"

        cursor.execute(
            f"SELECT hit_count FROM tg_rate_limits WHERE user_id=0 AND window_start={placeholder}",
            (minute_win,),
        )
        row = cursor.fetchone()
        min_used = row[0] if row else 0

        cursor.execute(
            f"SELECT hit_count FROM tg_rate_limits WHERE user_id=0 AND window_start={placeholder}",
            (hour_win,),
        )
        row = cursor.fetchone()
        hr_used = row[0] if row else 0

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


from pydantic import BaseModel


class ChatRequest(BaseModel):
    task: str
    max_steps: int = 10


async def sse_agent_stream(task: str):
    """
    Generatore asincrono per lo streaming Server-Sent Events e LangGraph.
    Usiamo un trucco per catturare lo stream del CoreAgent.
    """
    import io
    import sys

    from src.core.engine import run_task

    # Per ora che il Core non ha un Async Streaming Nativo token-by-token (richiederebbe refactoring Async callback di LLM),
    # simuliamo l'aggiornamento testuale ritornando la soluzione calcolata o iterazioni se disponibile.
    # In una versione avanzata: passeremo un handler custom all'LLM.

    yield 'data: {"chunk": "[Pensando...]\\n"}\n\n'

    try:
        # Passiamo alla thread pool visto la natura bloccante
        result = await asyncio.to_thread(run_task, task, False, 10, False)

        # Streammiamo il risultato finale con finto stutter per la UI se non supportiamo tokens nativi
        words = result.split(" ")
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
    return StreamingResponse(sse_agent_stream(req.task), media_type="text/event-stream")
