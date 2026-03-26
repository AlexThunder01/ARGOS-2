"""
WorldState — Rappresentazione esplicita dello stato del sistema.
Viene aggiornato a ogni ciclo e alimenta il planner con contesto strutturato.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Any
from datetime import datetime


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
    """
    current_task: str = ""
    step_count: int = 0
    active_windows: List[str] = field(default_factory=list)
    last_screenshot_path: Optional[str] = None
    action_history: List[ActionRecord] = field(default_factory=list)
    last_error: Optional[str] = None
    confidence: float = 1.0
    task_done: bool = False

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
            f"[STATO ARGOS]",
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

        return "\n".join(lines)

    def reset(self):
        """Resetta lo stato per un nuovo task."""
        self.step_count = 0
        self.action_history = []
        self.last_error = None
        self.confidence = 1.0
        self.task_done = False
        self.last_screenshot_path = None
