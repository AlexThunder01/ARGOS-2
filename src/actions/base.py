"""
ActionResult e ActionStatus — Risposta strutturata di ogni azione eseguita.
Fornisce un'interfaccia consistente per il planner e il verifier.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class ActionStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_CONFIRMATION = "needs_confirmation"
    RETRYING = "retrying"
    SKIPPED = "skipped"


@dataclass
class ActionResult:
    """Risposta strutturata di un'azione. Usata dal planner per decidere il prossimo step."""

    status: ActionStatus
    message: str
    data: Optional[Any] = None
    should_retry: bool = False

    @property
    def success(self) -> bool:
        return self.status == ActionStatus.SUCCESS

    def __str__(self):
        return f"[{self.status.value.upper()}] {self.message}"
