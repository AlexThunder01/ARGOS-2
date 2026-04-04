"""
IntentParser — Trasforma linguaggio naturale in intenti strutturati.

Pipeline: audio → STT → IntentParser → task JSON → Planner ARGOS

Invece di passare il testo trascritto direttamente come comando,
questo modulo lo analizza per estrarre:
- azione principale
- parametri
- livello di ambiguità
- necessità di conferma
"""

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class ParsedIntent:
    """Intent strutturato estratto dal linguaggio naturale."""

    action: str  # es. "web_search", "launch_app", "create_file"
    params: dict = field(default_factory=dict)
    raw_text: str = ""  # testo originale trascritto
    confidence: float = 1.0  # 0.0–1.0
    needs_confirmation: bool = False
    ambiguous: bool = False
    alternatives: List[str] = field(
        default_factory=list
    )  # azioni alternative possibili


# Pattern di intenti comuni — regole deterministiche PRIMA dell'LLM
# Ordine: i pattern più specifici vanno per primi
INTENT_PATTERNS = [
    # --- Browser / Web ---
    {
        "patterns": [r"apri\s+(firefox|chrome|browser|il browser)", r"vai su internet"],
        "action": "launch_app",
        "params_fn": lambda m: {"app_name": "firefox"},
    },
    {
        "patterns": [
            r"cerca\s+(.+?)(?:\s+su(?:l)?\s+(?:internet|web|google))?$",
            r"cercare\s+(.+)",
        ],
        "action": "web_search",
        "params_fn": lambda m: {"query": m.group(1).strip()},
    },
    # --- App ---
    {
        "patterns": [r"apri\s+(\w[\w\s]*)", r"lancia\s+(\w[\w\s]*)"],
        "action": "launch_app",
        "params_fn": lambda m: {"app_name": m.group(1).strip().lower()},
    },
    # --- File System ---
    {
        "patterns": [r"crea\s+(?:un\s+)?file\s+(?:chiamato\s+)?(\S+)"],
        "action": "create_file",
        "params_fn": lambda m: {"filename": m.group(1)},
    },
    {
        "patterns": [
            r"elimina\s+(?:il\s+)?file\s+(\S+)",
            r"cancella\s+(?:il\s+)?file\s+(\S+)",
        ],
        "action": "delete_file",
        "params_fn": lambda m: {"filename": m.group(1)},
    },
    {
        "patterns": [
            r"leggi\s+(?:il\s+)?file\s+(\S+)",
            r"mostra(?:mi)?\s+(?:il\s+)?file\s+(\S+)",
        ],
        "action": "read_file",
        "params_fn": lambda m: {"filename": m.group(1)},
    },
    {
        "patterns": [
            r"(?:mostra(?:mi)?|elenca)\s+(?:i\s+)?file",
            r"cosa c'è\s+(?:sul|nel)\s+desktop",
            r"lista\s+(?:i\s+)?file",
        ],
        "action": "list_files",
        "params_fn": lambda m: {"path": "."},
    },
    # --- Sistema ---
    {
        "patterns": [r"stato\s+(?:del\s+)?sistema", r"cpu", r"ram", r"risorse"],
        "action": "system_stats",
        "params_fn": lambda m: {},
    },
    {
        "patterns": [r"prezzo\s+(?:di\s+)?(\w+)", r"quanto\s+vale\s+(?:il\s+)?(\w+)"],
        "action": "crypto_price",
        "params_fn": lambda m: {"coin": m.group(1).lower()},
    },
    # --- Visione / Schermo ---
    {
        "patterns": [
            r"cosa\s+vedi",
            r"descrivi\s+(?:lo\s+)?schermo",
            r"che\s+(?:cosa\s+)?c'è\s+sullo\s+schermo",
        ],
        "action": "describe_screen",
        "params_fn": lambda m: {"question": "Cosa vedi sullo schermo?"},
    },
    {
        "patterns": [r"(?:clicca|premi|fai\s+click)\s+(?:su(?:l|lla|llo)?\s+)?(.+)"],
        "action": "visual_click",
        "params_fn": lambda m: {"description": m.group(1).strip()},
    },
    {
        "patterns": [r"scrivi\s+(.+)"],
        "action": "keyboard_type",
        "params_fn": lambda m: {"text": m.group(1).strip()},
    },
]

# Azioni che richiedono sempre conferma vocale
CONFIRM_ACTIONS = {
    "delete_file",
    "delete_directory",
    "modify_file",
    "visual_click",
    "keyboard_type",
}


def parse_intent(text: str) -> ParsedIntent:
    """
    Parsa il testo trascritto in un intento strutturato.

    Strategia ibrida:
    1. Prova match deterministico (regole regex) — veloce e predicibile
    2. If no match → return generic intent "ask_llm" (da processare dal planner)

    Args:
        text: testo trascritto dallo STT

    Returns:
        ParsedIntent con azione, parametri e metadata
    """
    if not text or not text.strip():
        return ParsedIntent(
            action="none",
            raw_text=text or "",
            confidence=0.0,
            ambiguous=True,
        )

    clean = text.strip().lower()
    # Rimuovi punteggiatura finale
    clean = re.sub(r"[.!?]+$", "", clean).strip()

    # Cerca match deterministico
    for pattern_group in INTENT_PATTERNS:
        for pattern in pattern_group["patterns"]:
            match = re.search(pattern, clean, re.IGNORECASE)
            if match:
                action = pattern_group["action"]
                try:
                    params = pattern_group["params_fn"](match)
                except Exception:
                    params = {}

                return ParsedIntent(
                    action=action,
                    params=params,
                    raw_text=text,
                    confidence=0.85,
                    needs_confirmation=action in CONFIRM_ACTIONS,
                    ambiguous=False,
                )

    # Nessun pattern matched → passa al planner LLM
    return ParsedIntent(
        action="ask_llm",
        params={"text": text},
        raw_text=text,
        confidence=0.5,
        needs_confirmation=False,
        ambiguous=True,
    )


def format_confirmation_prompt(intent: ParsedIntent) -> str:
    """Genera la domanda di conferma vocale per l'utente."""
    action_names = {
        "delete_file": "eliminare il file",
        "delete_directory": "delete the directory",
        "modify_file": "modificare il file",
        "visual_click": "cliccare su",
        "keyboard_type": "scrivere",
    }
    action_desc = action_names.get(intent.action, intent.action)
    target = (
        intent.params.get("filename")
        or intent.params.get("description")
        or intent.params.get("text", "")
    )
    return f"Vuoi che procedo a {action_desc} '{target}'?"
