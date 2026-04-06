"""
ARGOS-2 Built-in Hooks — Hook preconfezionati pronti all'uso.

Nessuno è attivo di default: vanno registrati esplicitamente al boot
(es. in scripts/main.py o nel server FastAPI) oppure abilitati via config.

Utilizzo:
    from src.hooks.builtin import register_audit_log, register_telegram_alerts
    from src.config import AUDIT_LOG_PATH

    register_audit_log(path=AUDIT_LOG_PATH)
    register_telegram_alerts(bot_token="...", chat_id="...")
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.hooks.registry import HOOK_REGISTRY, HookEvent

logger = logging.getLogger("argos.hooks")


# ─── 1. Audit Log ─────────────────────────────────────────────────────────

def register_audit_log(path: Optional[str] = None) -> None:
    """
    Registra un hook che scrive ogni tool execution su file JSON Lines.

    Ogni riga del file è un oggetto JSON:
        {"ts": "...", "tool": "...", "input": {...}, "success": true, "result_preview": "..."}

    Args:
        path: Percorso del file di log. Default: logs/argos_audit.jsonl
    """
    log_path = Path(path or os.path.join("logs", "argos_audit.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _audit_post(tool_name: str, tool_input: dict, result: str, success: bool):
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "tool": tool_name,
            "input": tool_input,
            "success": success,
            "result_preview": result[:200],
        }
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[AuditLog] Failed to write: {e}")

    HOOK_REGISTRY.register(
        HookEvent.POST_TOOL_USE,
        _audit_post,
        name="audit_log_success",
    )
    HOOK_REGISTRY.register(
        HookEvent.POST_TOOL_FAILURE,
        _audit_post,
        name="audit_log_failure",
    )
    logger.info(f"[AuditLog] Writing to {log_path}")


# ─── 2. Telegram Alerts ───────────────────────────────────────────────────

def register_telegram_alerts(
    bot_token: str,
    chat_id: str,
    tools: Optional[list[str]] = None,
) -> None:
    """
    Registra un hook che invia un messaggio Telegram dopo ogni tool execution.

    Args:
        bot_token: Token del bot Telegram.
        chat_id: ID della chat/canale destinatario.
        tools: Lista di tool da monitorare. None = tutti.
              Consigliato: ["delete_file", "delete_directory", "bash_exec", "python_repl"]
    """
    import requests as _requests

    def _telegram_post(tool_name: str, tool_input: dict, result: str, success: bool):
        icon = "✅" if success else "❌"
        text = (
            f"{icon} <b>Argos — {tool_name}</b>\n"
            f"<code>{json.dumps(tool_input, ensure_ascii=False)[:200]}</code>\n"
            f"<i>{result[:150]}</i>"
        )
        try:
            _requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"[TelegramAlert] Failed: {e}")

    HOOK_REGISTRY.register(
        HookEvent.POST_TOOL_USE,
        _telegram_post,
        tools=tools,
        name="telegram_alert_success",
    )
    HOOK_REGISTRY.register(
        HookEvent.POST_TOOL_FAILURE,
        _telegram_post,
        tools=tools,
        name="telegram_alert_failure",
    )


# ─── 3. Rate Limiter per tool costosi ─────────────────────────────────────

def register_tool_rate_limit(
    tools: list[str],
    max_calls: int = 10,
    window_seconds: int = 60,
) -> None:
    """
    Registra un hook che limita il numero di chiamate per tool in una finestra temporale.

    Args:
        tools: Tool a cui applicare il rate limit.
        max_calls: Numero massimo di chiamate nella finestra.
        window_seconds: Durata della finestra in secondi.
    """
    import time
    from collections import deque

    call_times: deque = deque()

    def _rate_limit(tool_name: str, tool_input: dict) -> bool:
        now = time.monotonic()
        # Rimuovi chiamate fuori finestra
        while call_times and now - call_times[0] > window_seconds:
            call_times.popleft()

        if len(call_times) >= max_calls:
            logger.warning(
                f"[RateLimit] Tool '{tool_name}' rate limited "
                f"({max_calls}/{window_seconds}s)"
            )
            return False  # Blocca

        call_times.append(now)
        return True

    HOOK_REGISTRY.register(
        HookEvent.PRE_TOOL_USE,
        _rate_limit,
        tools=tools,
        name=f"rate_limit({'|'.join(tools)})",
    )


# ─── 4. Business Hours Guard ──────────────────────────────────────────────

def register_business_hours_guard(
    tools: Optional[list[str]] = None,
    allowed_hours: tuple[int, int] = (8, 20),
) -> None:
    """
    Blocca tool pericolosi fuori dall'orario di lavoro.

    Args:
        tools: Tool da bloccare. Default: tool critici.
        allowed_hours: Tupla (ora_inizio, ora_fine) in formato 24h.
    """
    guarded_tools = tools or [
        "delete_file", "delete_directory", "launch_app",
        "bash_exec", "python_repl",
    ]
    start_h, end_h = allowed_hours

    def _hours_guard(tool_name: str, tool_input: dict) -> bool:
        hour = datetime.now().hour
        if not (start_h <= hour < end_h):
            logger.warning(
                f"[BusinessHours] Blocked '{tool_name}' outside "
                f"{start_h}:00-{end_h}:00 (current: {hour}:xx)"
            )
            return False
        return True

    HOOK_REGISTRY.register(
        HookEvent.PRE_TOOL_USE,
        _hours_guard,
        tools=guarded_tools,
        name="business_hours_guard",
    )
