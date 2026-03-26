"""
Planner — Gestisce il loop osserva→pianifica→agisce per ARGOS.

L'output del modello LLM viene vincolato a questo schema JSON:
{
    "thought": "ragionamento interno breve",
    "action": {"tool": "nome_tool", "input": {...}},
    "confidence": 0.9,
    "done": false
}

If the model produces free-form text (final response), it is treated as "done: true".
"""
import json
import re
from typing import Optional, Tuple
from dataclasses import dataclass


PLANNER_RESPONSE_SCHEMA = """
FORMATO RISPOSTA OBBLIGATORIO — usa SEMPRE uno di questi due formati:

1. Se devi eseguire un'azione:
{
  "thought": "<ragionamento brevissimo>",
  "action": {"tool": "<nome_tool>", "input": <parametri>},
  "confidence": <0.0-1.0>,
  "done": false
}

2. Se hai terminato o vuoi rispondere all'utente:
{
  "thought": "<motivazione>",
  "response": "<tua risposta in italiano>",
  "done": true
}

NON scrivere MAI testo al di fuori del JSON.
"""


@dataclass
class PlannerDecision:
    """Decisione strutturata del planner, parsata dalla risposta LLM."""
    thought: str
    tool: Optional[str]
    tool_input: Optional[dict]
    confidence: float
    done: bool
    response: Optional[str]  # Risposta testuale finale (se done=True)
    raw: str  # Risposta grezza del modello (per debug)


def parse_planner_response(raw_response: str) -> PlannerDecision:
    """
    Parsa la risposta del modello LLM secondo lo schema vincolato.
    
    Gestisce tre casi:
    1. JSON valido secondo lo schema → PlannerDecision strutturata
    2. JSON parziale/corrotto → fallback su extract_json best-effort
    3. Testo puro → trattato come risposta finale (done=True)
    """
    text = raw_response.strip()

    # Tenta il parse diretto usando il nuovo estrattore basato sul conteggio parentesi
    from src.utils import extract_json
    data = extract_json(text)
    
    if data:
        try:
            thought = data.get("thought", "")
            done = bool(data.get("done", False))

            if done or "response" in data:
                # Risposta finale
                return PlannerDecision(
                    thought=thought,
                    tool=None,
                    tool_input=None,
                    confidence=1.0,
                    done=True,
                    response=data.get("response") or text,
                    raw=raw_response,
                )

            # Azione da eseguire
            action = data.get("action", {})
            tool_name = action.get("tool") if isinstance(action, dict) else None
            tool_input = action.get("input") if isinstance(action, dict) else None
            confidence = float(data.get("confidence", 1.0))

            # Compatibilità retroattiva: vecchio formato {"tool": ..., "input": ...}
            if not tool_name and "tool" in data:
                tool_name = data["tool"]
                tool_input = data.get("input")

            # Se dopo tutto non c'è un tool valido, è una risposta finale mascherata
            if not tool_name:
                return PlannerDecision(
                    thought=thought,
                    tool=None,
                    tool_input=None,
                    confidence=1.0,
                    done=True,
                    response=data.get("response") or thought or text,
                    raw=raw_response,
                )

            return PlannerDecision(
                thought=thought,
                tool=tool_name,
                tool_input=tool_input,
                confidence=confidence,
                done=False,
                response=None,
                raw=raw_response,
            )
        except Exception:
            pass

    # Fallback: no JSON found — treat as raw textual response
    return PlannerDecision(
        thought="(free-form text, no JSON found)",
        tool=None,
        tool_input=None,
        confidence=1.0,
        done=True,
        response=text,
        raw=raw_response,
    )


def build_system_prompt_suffix() -> str:
    """Ritorna il suffisso da aggiungere al system prompt per vincolare il formato."""
    return PLANNER_RESPONSE_SCHEMA
