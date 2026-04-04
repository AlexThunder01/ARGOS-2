import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.security import verify_api_key
from src.db.connection import DB_BACKEND, get_connection, return_pg_connection

router = APIRouter(tags=["Email HITL"])
logger = logging.getLogger("argos")


def _ph(q: str) -> str:
    """Convert ?-placeholders to %s for PostgreSQL."""
    return q.replace("?", "%s") if DB_BACKEND == "postgres" else q


class EmailAnalyzeRequest(BaseModel):
    sender: str
    subject: str
    body: str


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
        regex_pattern = pattern.replace("*", ".*")
        if re.search(regex_pattern, req.sender, re.IGNORECASE):
            logger.info(
                f"🚫 Email ignored: sender {req.sender} matches blacklist pattern {pattern}"
            )
            return {"status": "ignored", "reason": "sender_blacklisted"}

    prompt = f"""Analyze the following email. Respond EXACTLY in this textual format (DO NOT use JSON):

PRIORITY: [high/medium/low/spam]
SUMMARY: [summarize the sender's request in 1-2 sentences. If spam, write 'Spam detected.']
DRAFT RESPONSE:
[draft a polite response in the SAME LANGUAGE as the original email. Tone: {config.tone_of_voice}. End the response with: {config.custom_signature}. If spam, write 'ignored'.]

### GREETING & PERSONA INSTRUCTIONS:
1. You are responding on behalf of the owner of this inbox. Speak natively in the first person.
2. ALWAYS greet the sender by their actual Name if available.
3. NEVER address the sender by their raw email address.
4. If no human name is found, use a generic polite greeting without a name.

"""
    if config.allowed_languages:
        prompt += f"IMPORTANT: Only process this if the email is primarily in one of these languages: {', '.join(config.allowed_languages)}. If not, set PRIORITY: low and DRAFT RESPONSE: ignored.\n\n"

    prompt += f"Do not hallucinate information. Base your response strictly on the provided text.\n\nSENDER: {req.sender}\nSUBJECT: {req.subject}\nBODY: {req.body}"

    from api.routes.agent import _run_task_sync

    try:
        result = await asyncio.to_thread(_run_task_sync, prompt, False, 3)
        result_text = result.result

        import re as regex

        imp_match = regex.search(r"PRIORITY:\s*(\S+)", result_text, regex.IGNORECASE)
        importanza = imp_match.group(1).upper() if imp_match else "MEDIUM"

        allowed_priorities = {"HIGH", "MEDIUM", "LOW", "SPAM"}
        if importanza not in allowed_priorities:
            logger.warning(
                f"⚠️ LLM hallucinated priority '{importanza}'. Falling back to LOW."
            )
            importanza = "LOW"

        priority_map = {"HIGH": 4, "MEDIUM": 3, "LOW": 2, "SPAM": 1}
        email_prio_val = priority_map.get(importanza, 3)
        min_prio_val = priority_map.get(config.min_priority, 2)

        if email_prio_val < min_prio_val:
            logger.info(
                f"🚫 Email ignored: Priority '{importanza}' is below threshold '{config.min_priority}'"
            )
            return {
                "status": "ignored",
                "reason": f"priority_below_threshold ({importanza})",
            }

        rias_match = regex.search(
            r"SUMMARY:\s*(.+?)(?=\nDRAFT|$)",
            result_text,
            regex.IGNORECASE | regex.DOTALL,
        )
        riassunto = rias_match.group(1).strip() if rias_match else ""

        draft_match = regex.search(
            r"DRAFT RESPONSE:\s*\n?([\s\S]*)", result_text, regex.IGNORECASE
        )
        draft = draft_match.group(1).strip() if draft_match else result_text

        return {
            "status": "success",
            "priority": importanza.lower(),
            "summary": riassunto,
            "draft": draft,
        }
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
                _ph(
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
            _ph("SELECT payload FROM pending_emails WHERE msg_id = ?"), (message_id,)
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=404, detail="Email context not found or already consumed."
            )

        payload = row[0] if not isinstance(row, dict) else row["payload"]
        data = _json.loads(payload)
        cursor.execute(
            _ph("DELETE FROM pending_emails WHERE msg_id = ?"), (message_id,)
        )
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
