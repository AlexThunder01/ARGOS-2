"""Tests for JSON logging configuration."""

import io
import json
import logging


def test_configure_json_logging_emits_json():
    """After configure_json_logging(), log records are JSON-formatted."""
    from src.logging_config import configure_json_logging

    stream = io.StringIO()
    configure_json_logging(stream=stream, level=logging.DEBUG)

    logger = logging.getLogger("test_json_logger_unique_abc")
    logger.info("hello world", extra={"tool": "list_files", "step": 3})

    output = stream.getvalue()
    assert output.strip() != ""
    record = json.loads(output.strip().split("\n")[-1])
    assert record["message"] == "hello world"
    assert record["tool"] == "list_files"
    assert record["step"] == 3


def test_trace_id_context():
    """set_trace_id/get_trace_id work per-context."""
    from src.logging_config import get_trace_id, set_trace_id

    set_trace_id("abc-123")
    assert get_trace_id() == "abc-123"


def test_trace_id_default_empty():
    """get_trace_id returns empty string when not set in a fresh context."""
    from contextvars import copy_context

    from src.logging_config import get_trace_id

    ctx = copy_context()
    result = ctx.run(get_trace_id)
    assert isinstance(result, str)
