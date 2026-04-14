import asyncio
import logging
import os
import re

import httpx
import pybreaker
import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from api.security import verify_api_key

router = APIRouter(prefix="/telegram", tags=["Telegram"])
logger = logging.getLogger("argos")
telegram_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60)

# Singleton — think_with_context and call_lightweight are stateless (no shared history),
# so one instance is safe across all concurrent requests.
_telegram_agent = None


def _get_telegram_agent():
    global _telegram_agent
    if _telegram_agent is None:
        from src.core import CoreAgent

        _telegram_agent = CoreAgent(memory_mode="off")
    return _telegram_agent


class TelegramAttachRequest(BaseModel):
    file_id: str = Field(..., description="Telegram file_id to download")
    filename: str = Field(..., description="Original filename (e.g. document.pdf, voice.ogg)")
    user_id: int = Field(..., description="Telegram user_id (used for upload directory)")


class TelegramChatRequest(BaseModel):
    user_id: int = Field(..., description="Telegram user_id")
    chat_id: int = Field(..., description="Telegram chat_id")
    text: str = Field(..., description="User message text")
    attachments: list[str] = Field(
        default_factory=list,
        description="Optional upload_id UUIDs from /telegram/attach",
    )
    first_name: str = Field(default="", description="Telegram first name")
    username: str = Field(default="", description="Telegram @username")


class TelegramChatResponse(BaseModel):
    status: str
    reply: str
    user_id: int
    memories_used: int = 0
    is_new_user: bool = False


def _notify_admin_new_user(user_id: int, first_name: str, username: str):
    admin_chat_id = os.getenv("ADMIN_CHAT_ID", "").strip()
    bot_token = os.getenv("TELEGRAM_CHAT_BOT_TOKEN", "").strip()
    if not admin_chat_id or not bot_token:
        return
    text = (
        f"🆕 <b>New chat access request</b>\n\n"
        f"👤 Name: {first_name}\n"
        f"🔗 Username: @{username or 'none'}\n"
        f"🆔 User ID: <code>{user_id}</code>\n\n"
        f"✅ To approve, tap:\n/approve_{user_id}\n\n"
        f"❌ To reject, tap:\n/reject_{user_id}"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": admin_chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"[Telegram] Admin notification failed: {e}")


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).strip("`"), text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    return text


def _handle_telegram_command(text: str, user_id: int, config) -> str | None:
    from src.telegram.db import (
        db_clear_conversation_window,
        db_delete_user_data,
        db_get_open_tasks,
        db_get_user_stats,
        db_update_profile,
    )

    if not text.startswith("/"):
        return None

    parts = text.split()
    cmd = parts[0].lower().split("@")[0]

    if cmd == "/start":
        return config.telegram_welcome_message
    elif cmd == "/help":
        return (
            "📋 *Available commands:*\n/reset — Clear current session context\n"
            "/status — View your statistics\n/language it|en|... — Change language\n"
            "/tone formal|casual|neutral — Change tone\n/name <name> — Set your preferred name\n"
            "/tasks — Your open tasks\n/deleteme CONFIRM — Delete all your data"
        )
    elif cmd == "/reset":
        db_clear_conversation_window(user_id)
        return "✅ Session context cleared. Let's start fresh."
    elif cmd == "/status":
        stats = db_get_user_stats(user_id)
        return (
            f"👤 *Your profile:*\nStatus: ✅ Approved\nTotal messages: {stats['msg_count']}\n"
            f"Saved memories: {stats['memory_count']}\nOpen tasks: {stats['open_tasks']}\nMember since: {stats['registered_at']}"
        )
    elif cmd == "/deleteme":
        if len(parts) > 1 and parts[1].upper() == "CONFIRM":
            db_delete_user_data(user_id)
            return "🗑️ All your data has been permanently deleted.\nYour access has been revoked."
        else:
            return "⚠️ This will *permanently delete ALL* your data.\n\nType `/deleteme CONFIRM` to proceed."
    elif cmd == "/language" and len(parts) > 1:
        db_update_profile(user_id, language=parts[1][:5])
        return f"✅ Language set to: {parts[1][:5]}"
    elif cmd == "/tone" and len(parts) > 1:
        if parts[1].lower() not in ("formal", "casual", "neutral"):
            return "❌ Invalid tone. Use: formal | casual | neutral"
        db_update_profile(user_id, preferred_tone=parts[1].lower())
        return f"✅ Tone set to: {parts[1].lower()}"
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
    elif cmd.startswith("/approve_") or cmd.startswith("/reject_"):
        admin_id = int(os.getenv("ADMIN_CHAT_ID", "0"))
        if user_id != admin_id:
            return "❌ Unauthorized. Only the admin can use this command."

        target_id_str = cmd.split("_")[1]
        if not target_id_str.isdigit():
            return "❌ Invalid user ID."

        target_id = int(target_id_str)
        from src.telegram.db import db_get_user

        target_user = db_get_user(target_id)
        if not target_user:
            return "❌ User not found in database."
        if target_user["status"] != "pending":
            return (
                f"⚠️ Action already taken. User is currently `{target_user['status']}`."
            )

        if cmd.startswith("/approve_"):
            from src.telegram.db import db_approve_user

            db_approve_user(target_id, approved_by=admin_id)
            return f"✅ User `{target_id}` has been fiercely approved."
        else:
            from src.telegram.db import db_ban_user

            db_ban_user(target_id, reason="Rejected by admin via chat command")
            return f"🚫 User `{target_id}` has been successfully rejected."
    return None


_TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


@router.post("/attach", dependencies=[Depends(verify_api_key)])
async def telegram_attach(req: TelegramAttachRequest):
    """
    Download a file from Telegram (by file_id) and register it as an upload.
    Returns an opaque upload_id to be passed in TelegramChatRequest.attachments.

    The n8n workflow calls this endpoint before /telegram/chat so that all
    file-handling logic stays in Python (testable) rather than in n8n JS nodes.
    """
    if not _TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not configured")

    from src.upload import save_upload, validate_upload

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/getFile",
                params={"file_id": req.file_id},
            )
            if not r.is_success:
                raise HTTPException(
                    status_code=502,
                    detail=f"Telegram getFile failed: {r.status_code}",
                )
            tg_path = r.json()["result"]["file_path"]
            dl = await client.get(
                f"https://api.telegram.org/file/bot{_TELEGRAM_BOT_TOKEN}/{tg_path}"
            )
            dl.raise_for_status()

        try:
            validate_upload(req.filename, len(dl.content))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        upload_id = save_upload(
            user_id=req.user_id,
            filename=req.filename,
            content=dl.content,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[Telegram] attach failed for file_id={req.file_id}: {exc}")
        raise HTTPException(status_code=502, detail=f"File download error: {exc}")

    return {"upload_id": upload_id, "filename": req.filename}


@router.post(
    "/chat", response_model=TelegramChatResponse, dependencies=[Depends(verify_api_key)]
)
async def telegram_chat(req: TelegramChatRequest, background_tasks: BackgroundTasks):
    from src.telegram.db import (
        db_approve_user,
        db_gc_memories,
        db_get_conversation_window,
        db_get_open_tasks,
        db_get_profile,
        db_get_user,
        db_increment_msg_count,
        db_register_user,
        db_save_conversation_turn,
    )
    from src.telegram.memory import (
        extract_memories_from_text,
        retrieve_relevant_memories,
        save_extracted_memories,
        should_extract_memory,
        should_run_gc,
    )
    from src.telegram.prompt import build_telegram_system_prompt
    from src.workflows_config import get_workflows_config

    config = get_workflows_config()

    if not config.is_telegram_enabled:
        return TelegramChatResponse(
            status="disabled",
            reply="The bot is temporarily disabled.",
            user_id=req.user_id,
        )

    max_len = config.telegram_max_input_length
    if len(req.text) > max_len:
        return TelegramChatResponse(
            status="ok",
            reply=f"⚠️ Message too long ({len(req.text)} chars). Maximum: {max_len}.",
            user_id=req.user_id,
        )

    from src.core.rate_limit import RateLimitExceeded, check_rate_limit

    try:
        check_rate_limit(req.user_id)
    except RateLimitExceeded as e:
        return TelegramChatResponse(
            status="error",
            reply=f"🛑 {str(e)}",
            user_id=req.user_id,
        )

    user = db_get_user(req.user_id)

    if user is None:
        db_register_user(req.user_id, req.first_name, req.username)
        if config.telegram_auto_approve:
            db_approve_user(req.user_id)
        else:
            if config.telegram_notify_on_new_user:
                background_tasks.add_task(
                    _notify_admin_new_user, req.user_id, req.first_name, req.username
                )
            return TelegramChatResponse(
                status="pending",
                reply=config.telegram_unauthorized_message,
                user_id=req.user_id,
                is_new_user=True,
            )
        user = db_get_user(req.user_id)

    elif user["status"] == "pending":
        return TelegramChatResponse(
            status="pending",
            reply="Your access request is still pending approval.",
            user_id=req.user_id,
        )

    elif user["status"] == "banned":
        logger.info(f"[Telegram] Message from banned user {req.user_id} — silenced.")
        return TelegramChatResponse(status="banned", reply="", user_id=req.user_id)

    cmd_response = _handle_telegram_command(req.text, req.user_id, config)
    if cmd_response is not None:
        return TelegramChatResponse(
            status="ok", reply=cmd_response, user_id=req.user_id
        )

    db_increment_msg_count(req.user_id)
    msg_count = (user.get("msg_count_total", 0) or 0) + 1

    user_profile = db_get_profile(req.user_id)
    recent_history = db_get_conversation_window(
        req.user_id, limit=config.telegram_conversation_window
    )
    relevant_memories = retrieve_relevant_memories(
        req.user_id,
        req.text,
        top_k=config.telegram_max_memories,
        min_similarity=config.telegram_rag_threshold,
    )
    open_tasks = db_get_open_tasks(req.user_id)

    system_prompt = build_telegram_system_prompt(
        bot_config=config.telegram_config,
        user_profile=user_profile,
        memories=relevant_memories,
        tasks=open_tasks,
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": req.text})

    if req.attachments:
        from src.upload import build_attachment_context

        attachment_ctx = build_attachment_context(req.attachments)
        messages.append({"role": "system", "content": attachment_ctx})

    agent = _get_telegram_agent()

    try:
        raw_reply = await asyncio.to_thread(
            telegram_breaker.call, agent.think_with_context, messages
        )
    except pybreaker.CircuitBreakerError:
        return TelegramChatResponse(
            status="ok",
            reply="⚠️ Servizio temporaneamente non disponibile. Riprova tra un minuto.",
            user_id=req.user_id,
        )
    except Exception as e:
        logger.error(f"[Telegram] LLM call failed for user {req.user_id}: {e}")
        return TelegramChatResponse(
            status="ok",
            reply="⚠️ Non riesco a connettermi al servizio AI in questo momento. Riprova tra qualche secondo.",
            user_id=req.user_id,
        )

    background_tasks.add_task(
        db_save_conversation_turn, req.user_id, req.text, raw_reply
    )

    if should_extract_memory(req.text, msg_count):
        tg_cfg = getattr(config, "telegram_config", {})
        beh_cfg = tg_cfg.get("behavior", {}) if isinstance(tg_cfg, dict) else {}
        mem_cfg = beh_cfg.get("memory", {})
        _poisoning_on = mem_cfg.get("enable_poisoning_detection", True)
        _risk_thresh = mem_cfg.get("risk_threshold", 0.5)
        _susp_ret = mem_cfg.get("suspicious_retention", 500)

        def _do_extraction():
            existing = [
                {"content": m["content"], "category": m["category"]}
                for m in relevant_memories
            ]
            facts = extract_memories_from_text(
                req.text, existing, agent.call_lightweight
            )
            if facts:
                save_extracted_memories(
                    req.user_id,
                    facts,
                    llm_call_fn=agent.call_lightweight,
                    poisoning_enabled=_poisoning_on,
                    risk_threshold=_risk_thresh,
                    suspicious_retention=_susp_ret,
                )

        background_tasks.add_task(_do_extraction)

    if should_run_gc(msg_count):
        background_tasks.add_task(db_gc_memories, req.user_id)

    clean_reply = _strip_markdown(raw_reply)

    return TelegramChatResponse(
        status="ok",
        reply=clean_reply,
        user_id=req.user_id,
        memories_used=len(relevant_memories),
    )
