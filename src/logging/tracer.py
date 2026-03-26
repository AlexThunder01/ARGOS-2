"""
Tracer — Sistema di logging strutturato per ARGOS.
Scrive su file con timestamp e su console con colori.
Ogni sessione crea un file separato in logs/.
"""
import logging
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.world_model.state import WorldState


def setup_tracer(log_dir: str = "logs") -> logging.Logger:
    """
    Inizializza il logger per la sessione corrente.
    Creates a logs/argos_YYYYMMDD_HHMMSS.log file on each startup.
    """
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"argos_{ts}.log")

    logger = logging.getLogger("argos")
    logger.setLevel(logging.DEBUG)

    # Evita handler duplicati se chiamato più volte
    if logger.handlers:
        logger.handlers.clear()

    # Handler su file (tutto il dettaglio)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    # Handler su console (solo INFO e superiori)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))  # Console pulita, senza timestamp

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"📋 Log sessione: {log_file}")
    return logger


def log_step(logger: logging.Logger, state: "WorldState", tool: str, result: str, success: bool):
    """Logga un singolo step dell'agente in formato JSON strutturato."""
    entry = {
        "step": state.step_count,
        "tool": tool,
        "result_preview": str(result)[:200],
        "success": success,
        "task": state.current_task,
    }
    logger.debug(f"STEP: {json.dumps(entry, ensure_ascii=False)}")
    if not success:
        logger.warning(f"⚠️  Step {state.step_count} fallito — tool={tool} → {str(result)[:100]}")


def log_decision(logger: logging.Logger, thought: str, tool: str, confidence: float):
    """Logga la decisione del planner (reasoning + tool scelto)."""
    logger.debug(json.dumps({
        "event": "planner_decision",
        "thought": thought[:200],
        "tool_chosen": tool,
        "confidence": confidence
    }, ensure_ascii=False))
