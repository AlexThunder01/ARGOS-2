"""
HookRegistry — Registro globale degli hook di ARGOS.

Ogni hook è una funzione Python registrata per un tipo di evento e,
opzionalmente, per uno o più nomi di tool.

Tipi di evento:
    PRE_TOOL_USE   — Prima dell'esecuzione. Ritorno False = blocca il tool.
    POST_TOOL_USE  — Dopo esecuzione riuscita.
    POST_TOOL_FAILURE — Dopo esecuzione fallita.
    SESSION_START  — All'inizializzazione di CoreAgent.
    SESSION_END    — Al termine di run_task().
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("argos.hooks")


class HookEvent(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_FAILURE = "post_tool_failure"
    SESSION_START = "session_start"
    SESSION_END = "session_end"


@dataclass
class HookResult:
    """Risultato aggregato dell'esecuzione di tutti gli hook per un evento."""

    allowed: bool = True  # False se almeno un PreToolUse hook ha bloccato
    block_reason: str = ""  # Messaggio del hook che ha bloccato
    errors: list[str] = field(default_factory=list)  # Eccezioni non fatali


@dataclass
class _HookEntry:
    fn: Callable
    tools: Optional[set[str]]  # None = tutti i tool
    event: HookEvent
    name: str


class HookRegistry:
    """
    Registry globale degli hook di ARGOS.

    Thread-safe per lettura (i.e. fire_* sono read-only sul registry).
    La registrazione avviene tipicamente a import-time, non durante l'esecuzione.
    """

    def __init__(self):
        self._hooks: list[_HookEntry] = []

    def register(
        self,
        event: HookEvent,
        fn: Callable,
        tools: Optional[list[str]] = None,
        name: Optional[str] = None,
    ) -> None:
        """
        Registra un hook per un evento.

        Args:
            event: Tipo di evento (PRE_TOOL_USE, POST_TOOL_USE, ecc.)
            fn: Funzione da eseguire.
            tools: Lista di nomi tool a cui si applica. None = tutti.
            name: Nome leggibile per logging/debug.
        """
        entry = _HookEntry(
            fn=fn,
            tools=set(tools) if tools else None,
            event=event,
            name=name or fn.__name__,
        )
        self._hooks.append(entry)
        logger.debug(
            f"[Hooks] Registered '{entry.name}' for {event.value} "
            f"(tools={tools or 'all'})"
        )

    def _matching(self, event: HookEvent, tool_name: str) -> list[_HookEntry]:
        """Restituisce gli hook che matchano evento e nome tool."""
        return [
            h
            for h in self._hooks
            if h.event == event and (h.tools is None or tool_name in h.tools)
        ]

    # ─── Fire methods ─────────────────────────────────────────────────────

    def fire_pre_tool(self, tool_name: str, tool_input: dict) -> HookResult:
        """
        Esegue tutti i PRE_TOOL_USE hook per il tool dato.

        Se un hook ritorna esplicitamente False, il tool viene bloccato.
        Eccezioni nei hook non bloccano l'esecuzione (logged as warning).

        Returns:
            HookResult con allowed=False se almeno un hook ha bloccato.
        """
        result = HookResult()
        for hook in self._matching(HookEvent.PRE_TOOL_USE, tool_name):
            try:
                ret = hook.fn(tool_name=tool_name, tool_input=tool_input)
                if ret is False:
                    result.allowed = False
                    result.block_reason = f"Blocked by hook '{hook.name}'"
                    logger.warning(f"[Hooks] '{hook.name}' blocked tool '{tool_name}'")
                    break  # Il primo blocco è sufficiente
            except Exception as e:
                msg = f"Hook '{hook.name}' raised {type(e).__name__}: {e}"
                result.errors.append(msg)
                logger.warning(f"[Hooks] {msg}")
        return result

    def fire_post_tool(
        self,
        tool_name: str,
        tool_input: dict,
        result: str,
        success: bool,
    ) -> HookResult:
        """
        Esegue tutti i POST_TOOL_USE o POST_TOOL_FAILURE hook.
        Le eccezioni non sono fatali.
        """
        event = HookEvent.POST_TOOL_USE if success else HookEvent.POST_TOOL_FAILURE
        hook_result = HookResult()
        for hook in self._matching(event, tool_name):
            try:
                hook.fn(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result=result,
                    success=success,
                )
            except Exception as e:
                msg = f"Hook '{hook.name}' raised {type(e).__name__}: {e}"
                hook_result.errors.append(msg)
                logger.warning(f"[Hooks] {msg}")
        return hook_result

    def fire_session(self, event: HookEvent, **kwargs: Any) -> None:
        """Esegue gli hook SESSION_START o SESSION_END."""
        for hook in self._matching(event, tool_name=""):
            try:
                hook.fn(**kwargs)
            except Exception as e:
                logger.warning(
                    f"[Hooks] Session hook '{hook.name}' raised {type(e).__name__}: {e}"
                )

    def clear(self) -> None:
        """Rimuove tutti gli hook (utile nei test)."""
        self._hooks.clear()

    def list_hooks(self) -> list[dict]:
        """Restituisce un sommario degli hook registrati (per il dashboard)."""
        return [
            {
                "name": h.name,
                "event": h.event.value,
                "tools": sorted(h.tools) if h.tools else "all",
            }
            for h in self._hooks
        ]


# ── Istanza globale ────────────────────────────────────────────────────────
HOOK_REGISTRY = HookRegistry()


# ── Decorator ─────────────────────────────────────────────────────────────


def on(
    event: HookEvent,
    tools: Optional[list[str]] = None,
    name: Optional[str] = None,
) -> Callable:
    """
    Decorator per registrare un hook.

    Esempi:

        @on(HookEvent.POST_TOOL_USE, tools=["delete_file"])
        def log_delete(tool_name, tool_input, result, success):
            print(f"Deleted: {tool_input}")

        @on(HookEvent.PRE_TOOL_USE, tools=["launch_app"])
        def blocca_di_notte(tool_name, tool_input) -> bool:
            from datetime import datetime
            return datetime.now().hour >= 8
    """

    def decorator(fn: Callable) -> Callable:
        HOOK_REGISTRY.register(
            event=event,
            fn=fn,
            tools=tools,
            name=name or fn.__name__,
        )
        return fn

    return decorator
