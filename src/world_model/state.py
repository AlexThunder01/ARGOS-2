"""
WorldState — Rappresentazione esplicita dello stato del sistema.
Viene aggiornato a ogni ciclo e alimenta il planner con contesto strutturato.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ActionRecord:
    """Registro di un'azione eseguita."""

    step: int
    tool: str
    input: Any
    result: str
    success: bool
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


@dataclass
class WorldState:
    """
    Stato esplicito del mondo percepito da ARGOS.
    Centralizza tutto il contesto necessario al planner.

    Cost tracking (NEW):
    - tokens_used: Cumulative token count for current task (rough estimate: len(response)/4)
    - estimated_cost_usd: Computed as tokens_used * COST_PER_TOKEN from config
    - Updated only during reasoning loop, reset per task
    """

    current_task: str = ""
    step_count: int = 0
    active_windows: list[str] = field(default_factory=list)
    last_screenshot_path: str | None = None
    action_history: list[ActionRecord] = field(default_factory=list)
    last_error: str | None = None
    confidence: float = 1.0
    task_done: bool = False
    # NEW: Cost tracking and observability
    tokens_used: int = 0  # Total tokens consumed in this task (rough estimate: len(response)/4)
    estimated_cost_usd: float = 0.0  # Cost = tokens_used * COST_PER_TOKEN (read from config)

    def record_action(self, tool: str, input: Any, result: str, success: bool):
        """Registra un'azione nel history e incrementa lo step counter."""
        self.step_count += 1
        if success:
            self.last_error = None
        else:
            self.last_error = result

        self.action_history.append(
            ActionRecord(
                step=self.step_count,
                tool=tool,
                input=input,
                result=result,
                success=success,
            )
        )

    def to_context_string(self) -> str:
        """
        Genera una stringa di contesto compatta da iniettare nel prompt del planner.
        Mostra solo gli ultimi 3 step per non saturare il context window.
        """
        lines = [
            "[STATO ARGOS]",
            f"  Current task: {self.current_task or 'none'}",
            f"  Step: {self.step_count}",
        ]

        recent = self.action_history[-3:]
        if recent:
            lines.append("  Ultimi step:")
            for a in recent:
                status = "✅" if a.success else "❌"
                result_preview = str(a.result)[:100].replace("\n", " ")
                lines.append(f"    {status} [{a.timestamp}] {a.tool} → {result_preview}")

        if self.last_error:
            lines.append(f"  ⚠️  Last error: {self.last_error[:100]}")

        # NEW: Include tokens/cost only if present (optional observability)
        if self.tokens_used > 0:
            lines.append(f"  Tokens used: {self.tokens_used}")
            lines.append(f"  Estimated cost: ${self.estimated_cost_usd:.4f}")

        return "\n".join(lines)

    def reset(self):
        """Resetta lo stato per un nuovo task."""
        self.step_count = 0
        self.action_history = []
        self.last_error = None
        self.confidence = 1.0
        self.task_done = False
        self.last_screenshot_path = None
