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

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("argos")

PLANNER_RESPONSE_SCHEMA = """
MANDATORY RESPONSE FORMAT — ALWAYS use one of these two JSON structures:

1. To execute a tool action:
{
  "thought": "<brief internal reasoning>",
  "action": {"tool": "<tool_name>", "input": <parameters>},
  "confidence": <0.0-1.0>,
  "done": false
}

2. To reply to the user or signal completion:
{
  "thought": "<motivation>",
  "response": "<your response — use the same language the user wrote in>",
  "done": true
}

NEVER write any text outside the JSON block.
"""


@dataclass
class PlannerDecision:
    """
    Structured output of a single LLM reasoning step.

    Fields map 1-to-1 with PLANNER_RESPONSE_SCHEMA above.
    If you add or rename a field here, update the schema string accordingly
    so the prompt stays in sync with the parser.
    """

    thought: str
    tool: Optional[str]
    tool_input: Optional[dict]
    confidence: float
    done: bool
    response: Optional[str]  # Final textual reply (when done=True)
    raw: str  # Raw model output (for debugging)


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
            try:
                confidence = float(data.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0
            confidence = min(1.0, max(0.0, confidence))

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
        except Exception as parse_exc:
            logger.debug(
                f"[Planner] JSON found but failed to parse into PlannerDecision "
                f"(error={parse_exc!r}, raw={raw_response[:120]!r})"
            )

    # Fallback: no JSON found — treat as raw textual response
    logger.debug(
        f"[Planner] No valid JSON in LLM response — treating as final text "
        f"(raw={raw_response[:120]!r})"
    )
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
