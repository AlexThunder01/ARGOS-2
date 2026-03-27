"""
Tracer — Structured logging system for ARGOS.
Writes to file with timestamps and to console with clean formatting.
Each session creates a separate file in logs/.
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
    Initializes the logger for the current session.
    Creates a logs/argos_YYYYMMDD_HHMMSS.log file on each startup.
    """
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"argos_{ts}.log")

    logger = logging.getLogger("argos")
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        logger.handlers.clear()

    # File handler (full verbosity)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    # Console handler (INFO and above only)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))  # Clean console, no timestamp

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"📋 Session Log: {log_file}")
    return logger


def log_step(logger: logging.Logger, state: "WorldState", tool: str, result: str, success: bool):
    """Logs a single agent execution step in structured JSON format."""
    entry = {
        "step": state.step_count,
        "tool": tool,
        "result_preview": str(result)[:200],
        "success": success,
        "task": state.current_task,
    }
    logger.debug(f"STEP: {json.dumps(entry, ensure_ascii=False)}")
    if not success:
        logger.warning(f"⚠️  Step {state.step_count} failed — tool={tool} → {str(result)[:100]}")


def log_decision(logger: logging.Logger, thought: str, tool: str, confidence: float):
    """Logs the planner's decision mapping (reasoning + chosen tool)."""
    logger.debug(json.dumps({
        "event": "planner_decision",
        "thought": thought[:200],
        "tool_chosen": tool,
        "confidence": confidence
    }, ensure_ascii=False))
