"""
Regression tests for LiteLLM provider-prefix routing with custom api_base.

These guard against three bugs found during live testing:

1. BUG: Models with a slash in the name (e.g. "openai/gpt-oss-120b") were
   being stripped to "gpt-oss-120b" by LiteLLM, causing 404 on endpoints that
   expect the full name (e.g. Groq).
   FIX: _build_kwargs always prepends "openai/" when api_base is set, so
   LiteLLM strips that outer prefix and the endpoint receives the full name.

2. BUG: Models without any prefix (e.g. "mistral-large-latest") caused
   LiteLLM to raise "LLM Provider NOT provided".
   FIX: Same prepend logic — bare name becomes "openai/mistral-large-latest",
   LiteLLM strips "openai/" and routes to api_base with "mistral-large-latest".

3. BUG: think_async() passed native tool schemas to the LLM even though the
   system prompt already describes tools as text. Models with built-in
   function-calling tools (e.g. "json") caused validation errors.
   FIX: think_async() passes tools=None; parse_litellm_response falls back to
   JSON content parsing.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.llm.client import LLMResponse, _build_kwargs

# ---------------------------------------------------------------------------
# Bug 1 & 2: _build_kwargs model prefix logic
# ---------------------------------------------------------------------------


def _kwargs(model: str, api_base: str | None) -> dict:
    return _build_kwargs(
        model=model,
        messages=[],
        tools=None,
        temperature=0.0,
        api_key="key",
        api_base=api_base,
    )


def _sent_model(model: str, api_base: str | None) -> str:
    """Returns the model string that _build_kwargs produces (what LiteLLM receives)."""
    return str(_kwargs(model, api_base)["model"])


class TestModelPrefixRouting:
    def test_bare_model_no_api_base_unchanged(self):
        """Without api_base, bare model names are passed as-is to LiteLLM."""
        result = _sent_model("gpt-4", api_base=None)
        assert result == "gpt-4"

    def test_provider_prefixed_model_no_api_base_unchanged(self):
        """Without api_base, provider-prefixed names are passed as-is."""
        result = _sent_model("openai/gpt-4", api_base=None)
        assert result == "openai/gpt-4"

    def test_bare_model_with_api_base_gets_prefix(self):
        """Bare model + custom api_base → prepend 'openai/' so LiteLLM routes correctly."""
        result = _sent_model("mistral-large-latest", api_base="https://api.example.com/v1")
        assert result == "openai/mistral-large-latest"

    def test_groq_slash_model_with_api_base_gets_double_prefix(self):
        """'openai/gpt-oss-120b' + api_base → 'openai/openai/gpt-oss-120b'.
        LiteLLM strips the outer 'openai/', sending 'openai/gpt-oss-120b' to Groq.
        """
        result = _sent_model("openai/gpt-oss-120b", api_base="https://api.groq.com/openai/v1")
        assert result == "openai/openai/gpt-oss-120b"

    def test_meta_slash_model_with_api_base_gets_prefix(self):
        """'meta-llama/llama-4-scout' + api_base → preserved after LiteLLM strips outer prefix."""
        result = _sent_model(
            "meta-llama/llama-4-scout-17b-16e-instruct",
            api_base="https://api.groq.com/openai/v1",
        )
        assert result == "openai/meta-llama/llama-4-scout-17b-16e-instruct"

    def test_llama_model_with_groq_api_base(self):
        """Standard Groq model: bare name gets prefixed."""
        result = _sent_model("llama-3.3-70b-versatile", api_base="https://api.groq.com/openai/v1")
        assert result == "openai/llama-3.3-70b-versatile"


# ---------------------------------------------------------------------------
# Bug 3: think_async must NOT pass native tools
# ---------------------------------------------------------------------------


class TestThinkAsyncNoNativeTools:
    @pytest.mark.asyncio
    async def test_think_async_passes_no_tools_to_llm(self):
        """think_async() must call llm_complete with tools=None.

        Passing native tool schemas conflicts with models that have built-in
        tools (e.g. 'json') and causes BadRequestError at LiteLLM validation.
        The system prompt already describes tools as text.
        """
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"thought":"x","response":"ok","done":true}',
                    tool_calls=None,
                )
            )
        ]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

        captured_kwargs: dict = {}

        async def fake_complete(**kwargs):
            captured_kwargs.update(kwargs)
            return LLMResponse(content='{"thought":"x","response":"ok","done":true}')

        with patch("src.agent.llm_complete", side_effect=fake_complete):
            from src.agent import ArgosAgent

            agent = ArgosAgent()
            await agent.think_async()

        assert captured_kwargs.get("tools") is None, (
            "think_async() must not pass native tools to the LLM — "
            f"got tools={captured_kwargs.get('tools')}"
        )


# ---------------------------------------------------------------------------
# Integration: complete() is called with the right model string
# ---------------------------------------------------------------------------


class TestCompleteModelRouting:
    @pytest.mark.asyncio
    async def test_complete_uses_api_base_prefix_logic(self):
        """complete() applies the prefix fix before calling acompletion."""
        from src.llm.client import complete

        captured: dict = {}

        mock_msg = MagicMock(content="ok", tool_calls=None)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_msg)]
        mock_response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)
            return mock_response

        with patch("src.llm.client.acompletion", side_effect=fake_acompletion):
            await complete(
                messages=[{"role": "user", "content": "hi"}],
                model="openai/gpt-oss-120b",
                api_key="key",
                api_base="https://api.groq.com/openai/v1",
            )

        # After double-prefix, LiteLLM strips outer "openai/" → Groq gets
        # "openai/gpt-oss-120b". We verify the model passed to acompletion.
        assert captured["model"] == "openai/openai/gpt-oss-120b"
