"""
ARGOS-2 Hook System — Punti di aggancio sul ciclo di vita dell'agente.

Permette di iniettare logica custom prima/dopo ogni tool execution senza
toccare il core di engine.py.

Utilizzo base:
    from src.hooks import on, HookEvent

    @on(HookEvent.POST_TOOL_USE, tools=["delete_file", "bash_exec"])
    def notifica(tool_name, tool_input, result, success):
        print(f"Tool eseguito: {tool_name}")

    # Oppure per bloccare un tool:
    @on(HookEvent.PRE_TOOL_USE, tools=["launch_app"])
    def blocca_di_notte(tool_name, tool_input) -> bool:
        from datetime import datetime
        return datetime.now().hour >= 8  # False = bloccato

Registrazione programmatica (senza decorator):
    HOOK_REGISTRY.register(HookEvent.POST_TOOL_USE, my_fn, tools=["bash_exec"])

Hook built-in:
    from src.hooks.builtin import register_audit_log, register_telegram_alerts
"""

from .registry import HOOK_REGISTRY, HookEvent, HookResult, on

__all__ = ["HOOK_REGISTRY", "HookEvent", "HookResult", "on"]
