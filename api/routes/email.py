import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from api.security import verify_api_key
from src.db.connection import DB_BACKEND, get_connection, ph, return_pg_connection

router = APIRouter(tags=["Email HITL"])
logger = logging.getLogger("argos")


class EmailAnalyzeRequest(BaseModel):
    sender: str
    subject: str
    body: str


class _EmailAnalysis(BaseModel):
    priority: Literal["high", "medium", "low", "spam"]
    summary: str
    draft: str


@router.post("/analyze_email", dependencies=[Depends(verify_api_key)])
async def analyze_email(req: EmailAnalyzeRequest):
    import re

    from src.workflows_config import get_workflows_config

    config = get_workflows_config()

    if not config.is_enabled:
        return {
            "status": "ignored",
            "reason": "gmail_assistant is disabled in config.yaml",
        }

    for pattern in config.ignore_senders:
        # Escape the pattern first, then restore the glob wildcard as .*
        regex_pattern = re.escape(pattern).replace(r"\*", ".*")
        if re.search(regex_pattern, req.sender, re.IGNORECASE):
            logger.info(
                f"🚫 Email ignored: sender {req.sender} matches blacklist pattern {pattern}"
            )
            return {"status": "ignored", "reason": "sender_blacklisted"}

    lang_instruction = ""
    if config.allowed_languages:
        lang_instruction = (
            f"IMPORTANT: Only process this if the email is primarily in one of these "
            f"languages: {', '.join(config.allowed_languages)}. "
            f'If not, set priority to "low" and draft to "ignored".\n\n'
        )

    prompt = (
        f"Analyze the following email and respond with a JSON object containing exactly "
        f'three keys: "priority" (one of: "high", "medium", "low", "spam"), '
        f'"summary" (1-2 sentences summarising the sender\'s request; if spam write '
        f'"Spam detected."), and "draft" (a polite response in the SAME LANGUAGE as the '
        f"original email; tone: {config.tone_of_voice}; end with: {config.custom_signature}; "
        f'if spam write "ignored"). Output ONLY the JSON object, no extra text.\n\n'
        f"GREETING & PERSONA: You respond on behalf of the inbox owner (first person). "
        f"Always greet the sender by their actual name if available; never use a raw email address.\n\n"
        f"{lang_instruction}"
        f"Do not hallucinate. Base your response strictly on the provided text.\n\n"
        f"SENDER: {req.sender}\nSUBJECT: {req.subject}\nBODY: {req.body}"
    )

    from api.routes.agent import _run_task_sync

    try:
        result = await asyncio.to_thread(_run_task_sync, prompt, False, 3)
        result_text = result.result

        # Strip markdown code fences if the LLM wrapped the JSON
        stripped = result_text.strip()
        if stripped.startswith("```"):
            stripped = (
                stripped.split("```")[-2] if "```" in stripped[3:] else stripped[3:]
            )
            stripped = stripped.lstrip("json").strip()

        try:
            analysis = _EmailAnalysis.model_validate(json.loads(stripped))
        except (json.JSONDecodeError, ValidationError) as parse_err:
            logger.warning(
                f"[email] Failed to parse LLM JSON response: {parse_err}. Raw: {stripped[:200]}"
            )
            raise HTTPException(
                status_code=502, detail="LLM returned an unparseable response."
            )

        priority_map = {"high": 4, "medium": 3, "low": 2, "spam": 1}
        email_prio_val = priority_map.get(analysis.priority, 3)
        min_prio_val = priority_map.get(config.min_priority.lower(), 2)

        if email_prio_val < min_prio_val:
            logger.info(
                f"🚫 Email ignored: Priority '{analysis.priority}' is below threshold '{config.min_priority}'"
            )
            return {
                "status": "ignored",
                "reason": f"priority_below_threshold ({analysis.priority})",
            }

        return {
            "status": "success",
            "priority": analysis.priority,
            "summary": analysis.summary,
            "draft": analysis.draft,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /analyze_email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pending_email", dependencies=[Depends(verify_api_key)])
async def store_pending_email(data: dict):
    import json as _json

    msg_id = data.get("messageId", "default")
    payload_str = _json.dumps(data, ensure_ascii=False)

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        if DB_BACKEND == "postgres":
            cursor.execute(
                ph(
                    "INSERT INTO pending_emails (msg_id, payload) VALUES (?, ?) "
                    "ON CONFLICT (msg_id) DO UPDATE SET payload = EXCLUDED.payload"
                ),
                (msg_id, payload_str),
            )
        else:
            cursor.execute(
                "INSERT OR REPLACE INTO pending_emails (msg_id, payload) VALUES (?, ?)",
                (msg_id, payload_str),
            )
        conn.commit()
    except Exception as e:
        logger.error(f"DB Write Error: {e}")
        return {"status": "error", "reason": "database_write_error"}
    finally:
        if DB_BACKEND == "postgres" and conn:
            return_pg_connection(conn)

    logger.info(f"📧 Active Context Queued: ID {msg_id}")
    return {"status": "saved", "sender": data.get("sender", "")}


@router.post(
    "/pending_email/{message_id}/consume", dependencies=[Depends(verify_api_key)]
)
async def consume_pending_email(message_id: str):
    import json as _json

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            ph("SELECT payload FROM pending_emails WHERE msg_id = ?"), (message_id,)
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=404, detail="Email context not found or already consumed."
            )

        payload = row[0] if not isinstance(row, dict) else row["payload"]
        data = _json.loads(payload)
        cursor.execute(ph("DELETE FROM pending_emails WHERE msg_id = ?"), (message_id,))
        conn.commit()

        return {**data, "status": "deleted_and_consumed"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DB Read/Delete Error: {e}")
        raise HTTPException(status_code=500, detail="State architecture failure")
    finally:
        if DB_BACKEND == "postgres" and conn:
            return_pg_connection(conn)
