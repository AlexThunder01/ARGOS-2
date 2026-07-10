"""Tests for ArgosSettings — Pydantic Settings config."""

import os
from unittest.mock import patch


def test_default_values():
    """ArgosSettings has sensible defaults without any env vars."""
    from src.settings import ArgosSettings

    settings = ArgosSettings()
    assert settings.llm_model != ""
    assert settings.tool_rag_top_k > 0
    assert settings.rate_limit_per_hour > 0


def test_env_var_override():
    """Environment variables override defaults."""
    with patch.dict(os.environ, {"TOOL_RAG_TOP_K": "7"}):
        import importlib

        import src.settings as mod

        importlib.reload(mod)
        from src.settings import ArgosSettings

        settings = ArgosSettings()
    assert settings.tool_rag_top_k == 7


def test_llm_backend_default():
    """LLM_BACKEND has a sensible default."""
    from src.settings import ArgosSettings

    settings = ArgosSettings()
    assert settings.llm_backend in ("openai-compatible", "anthropic", "groq")


def test_get_settings_is_cached():
    """get_settings() returns the same instance on repeated calls."""
    from src.settings import get_settings

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
