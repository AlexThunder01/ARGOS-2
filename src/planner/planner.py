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
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.client import LLMResponse

logger = logging.getLogger("argos")

# Strip <analysis>...</analysis> scratchpad blocks before parsing.
# The LLM may use this block as a chain-of-thought scratch area; it is never
# part of the structured output and must not reach the parser or the user.
_ANALYSIS_RE = re.compile(r"<analysis>.*?</analysis>", re.DOTALL | re.IGNORECASE)

PLANNER_RESPONSE_SCHEMA = """
MANDATORY RESPONSE FORMAT — ALWAYS use one of these two JSON structures:

OPTIONAL: You may prepend an <analysis> block for complex reasoning before the JSON.
It is stripped automatically and never shown to the user.

<analysis>
Your private chain-of-thought here. Think through the problem step by step.
Consider which tool to use and why. This block is ignored by the parser.
</analysis>

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
  "response": "<your response>",
  "done": true
}

NEVER write any text outside the <analysis> block and the JSON block.
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
    tool: str | None
    tool_input: dict[str, object] | None
    confidence: float
    done: bool
    response: str | None  # Final textual reply (when done=True)
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

    # Strip <analysis>...</analysis> scratchpad before any JSON extraction.
    # The model may use this for chain-of-thought; it must never reach the parser.
    if "<analysis>" in text:
        text = _ANALYSIS_RE.sub("", text).strip()
        if not text:
            # Model returned only an <analysis> block — treat as no structured output
            logger.debug("[Planner] Response was only <analysis> — treating as final text")
            return PlannerDecision(
                thought="(analysis block only, no JSON)",
                tool=None,
                tool_input=None,
                confidence=1.0,
                done=True,
                response=raw_response,
                raw=raw_response,
            )

    # Tenta il parse diretto usando il nuovo estrattore basato sul conteggio parentesi
    from src.utils import extract_json

    data = extract_json(text)  # type: ignore[no-untyped-call]

    if data:
        try:
            thought = data.get("thought", "")
            done = bool(data.get("done", False))

            if done or "response" in data:
                # If done=True but no response text and an action is present,
                # the model is confused — treat it as an action, not a final answer.
                if done and "response" not in data and "action" in data:
                    # INTENTIONAL: Model sent done=True with only action; fallback to action handling
                    # This handles confused LLM output gracefully without losing the user's intent
                    pass  # fall through to action handling below
                else:
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

            # Garantisce che tool_name sia sempre una stringa
            # (il LLM può hallucinate un dict nested come tool name)
            if tool_name is not None and not isinstance(tool_name, str):
                logger.warning(
                    f"[Planner] tool_name non è una stringa "
                    f"({type(tool_name).__name__}={str(tool_name)[:60]}) — ignored"
                )
                tool_name = None

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

    # Fallback: no valid JSON found.
    # If the text looks like a truncated/malformed JSON action (starts with "{" and
    # contains "action" or "tool"), do NOT treat it as a final answer — the LLM is
    # mid-action and just failed to close the JSON properly. Signal the engine to
    # inject a format-correction message and retry.
    import re as _re

    _looks_like_action = text.startswith("{") and _re.search(r'"(action|tool)"\s*:', text)
    if _looks_like_action:
        # Try regex to salvage tool name even from truncated JSON
        _tool_match = _re.search(r'"tool"\s*:\s*"([^"]+)"', text)
        if _tool_match:
            _salvaged_tool = _tool_match.group(1)
            # Try to find input dict (may be incomplete — use empty dict as fallback)
            _input_match = _re.search(r'"input"\s*:\s*(\{[^}]*\})', text)
            try:
                import json as _json

                _salvaged_input = _json.loads(_input_match.group(1)) if _input_match else {}
            except Exception:
                _salvaged_input = {}
            logger.warning(
                f"[Planner] Truncated JSON action salvaged via regex: "
                f"tool={_salvaged_tool!r} input={str(_salvaged_input)[:60]}"
            )
            return PlannerDecision(
                thought="(salvaged from truncated JSON)",
                tool=_salvaged_tool,
                tool_input=_salvaged_input,
                confidence=0.5,
                done=False,
                response=None,
                raw=raw_response,
            )
        # Looks like action JSON but couldn't salvage the tool name — ask LLM to retry
        logger.warning(
            f"[Planner] Response looks like truncated/malformed action JSON — "
            f"returning format error signal (raw={raw_response[:80]!r})"
        )
        return PlannerDecision(
            thought="(malformed action JSON — LLM must retry with valid format)",
            tool="__format_error__",  # sentinel: engine will inject correction message
            tool_input={},
            confidence=0.0,
            done=False,
            response=None,
            raw=raw_response,
        )

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


def parse_litellm_response(response: "LLMResponse") -> list[PlannerDecision]:
    """
    Converts a LLMResponse (from src/llm/client.py) into a list of PlannerDecisions.

    Primary path: if response.tool_calls is non-empty, each call becomes a
    PlannerDecision with done=False. Parallel calls produce multiple decisions.

    Fallback path: if response.content is set (no tool calls), delegates to the
    legacy parse_planner_response() so JSON-format responses still work.
    """
    if response.tool_calls:
        return [
            PlannerDecision(
                thought="",
                tool=tc.name,
                tool_input=tc.arguments,
                confidence=1.0,
                done=False,
                response=None,
                raw=f"tool_call:{tc.id}",
            )
            for tc in response.tool_calls
        ]

    # No native tool calls — fall back to text/JSON planner
    content = response.content or ""
    decision = parse_planner_response(content)
    return [decision]


def build_system_prompt_suffix() -> str:
    """Ritorna il suffisso da aggiungere al system prompt per vincolare il formato."""
    return PLANNER_RESPONSE_SCHEMA
