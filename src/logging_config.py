"""
JSON structured logging configuration for Argos.

Call configure_json_logging() once at application startup (in lifespan or main()).
All loggers under 'argos' namespace emit JSON records with trace_id injected.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import IO, Any

from pythonjsonlogger.json import JsonFormatter

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


class _TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()  # type: ignore[attr-defined]
        return True


def configure_json_logging(
    stream: IO[Any] | None = None,
    level: int = logging.INFO,
) -> None:
    """
    Configure root logger to emit JSON records with trace_id.

    Args:
        stream: Output stream (default: sys.stdout). Pass io.StringIO in tests.
        level: Log level threshold (default: INFO).
    """
    formatter = JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s %(trace_id)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        rename_fields={
            "asctime": "timestamp",
            "name": "logger",
            "levelname": "level",
        },
    )

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(_TraceIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for noisy in ("httpx", "httpcore", "litellm", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
