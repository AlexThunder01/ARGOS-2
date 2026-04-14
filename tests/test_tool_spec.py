"""
Tests for ToolSpec and ToolRegistry (src/tools/spec.py).

Coverage:
  - ToolSpec.requires_confirmation() by risk level
  - ToolSpec.prompt_example() output format
  - ToolSpec.validate_input() with valid, invalid, and None input
  - ToolRegistry lookup, iteration, filtering
  - ToolRegistry.build_prompt_block() format
  - ToolRegistry.dashboard_whitelist()
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from pydantic import Field

from src.tools.spec import ToolInput, ToolRegistry, ToolSpec

# ==========================================================================
# Fixtures
# ==========================================================================


class DummyInput(ToolInput):
    query: str = Field(description="Search query", examples=["test query"])


class EmptyInput(ToolInput):
    pass


def _dummy_executor(inp: dict) -> str:
    return "ok"


def _make_spec(
    name="test_tool", risk="none", dashboard_allowed=False, category="web", group=None
):
    return ToolSpec(
        name=name,
        description="A test tool",
        input_schema=DummyInput,
        executor=_dummy_executor,
        risk=risk,
        category=category,
        icon="🔧",
        label="Test Tool",
        dashboard_allowed=dashboard_allowed,
        group=group,
    )


# ==========================================================================
# ToolSpec — requires_confirmation
# ==========================================================================


class TestToolSpecConfirmation:
    def test_none_risk_no_confirmation(self):
        assert _make_spec(risk="none").requires_confirmation() is False

    def test_low_risk_no_confirmation(self):
        assert _make_spec(risk="low").requires_confirmation() is False

    def test_medium_risk_requires_confirmation(self):
        assert _make_spec(risk="medium").requires_confirmation() is True

    def test_high_risk_requires_confirmation(self):
        assert _make_spec(risk="high").requires_confirmation() is True

    def test_critical_risk_requires_confirmation(self):
        assert _make_spec(risk="critical").requires_confirmation() is True


# ==========================================================================
# ToolSpec — prompt_example
# ==========================================================================


class TestToolSpecPromptExample:
    def test_prompt_example_contains_field_name(self):
        example = _make_spec().prompt_example()
        assert "query" in example

    def test_prompt_example_uses_field_example(self):
        example = _make_spec().prompt_example()
        assert "test query" in example

    def test_no_input_prompt_example(self):
        spec = ToolSpec(
            name="no_input",
            description="No input tool",
            input_schema=EmptyInput,
            executor=_dummy_executor,
            risk="none",
            category="system",
            icon="📊",
            label="No Input",
        )
        assert spec.prompt_example() == "(no input needed)"


# ==========================================================================
# ToolSpec — validate_input
# ==========================================================================


class TestToolSpecValidateInput:
    def test_valid_dict(self):
        result = _make_spec().validate_input({"query": "hello"})
        assert result["query"] == "hello"

    def test_none_input_returns_empty(self):
        result = _make_spec().validate_input(None)
        assert isinstance(result, dict)

    def test_json_string_input(self):
        result = _make_spec().validate_input('{"query": "from_string"}')
        assert result["query"] == "from_string"

    def test_invalid_json_string_fallback(self):
        result = _make_spec().validate_input("not json at all")
        assert isinstance(result, dict)

    def test_to_metadata_format(self):
        meta = _make_spec(risk="high", category="filesystem").to_metadata()
        assert meta["category"] == "filesystem"
        assert meta["risk"] == "high"
        assert "description" in meta
        assert "icon" in meta
        assert "label" in meta


# ==========================================================================
# ToolRegistry
# ==========================================================================


class TestToolRegistry:
    def _make_registry(self):
        return ToolRegistry(
            [
                _make_spec(
                    "tool_a", risk="none", dashboard_allowed=True, category="web"
                ),
                _make_spec(
                    "tool_b",
                    risk="high",
                    dashboard_allowed=False,
                    category="filesystem",
                ),
                _make_spec(
                    "tool_c", risk="critical", dashboard_allowed=True, category="code"
                ),
            ]
        )

    def test_len(self):
        reg = self._make_registry()
        assert len(reg) == 3

    def test_contains(self):
        reg = self._make_registry()
        assert "tool_a" in reg
        assert "nonexistent" not in reg

    def test_getitem(self):
        reg = self._make_registry()
        spec = reg["tool_a"]
        assert spec.name == "tool_a"

    def test_get_existing(self):
        reg = self._make_registry()
        assert reg.get("tool_b") is not None

    def test_get_missing_returns_none(self):
        reg = self._make_registry()
        assert reg.get("nonexistent") is None

    def test_names(self):
        reg = self._make_registry()
        names = reg.names()
        assert set(names) == {"tool_a", "tool_b", "tool_c"}

    def test_dashboard_whitelist(self):
        reg = self._make_registry()
        whitelist = reg.dashboard_whitelist()
        assert "tool_a" in whitelist
        assert "tool_c" in whitelist
        assert "tool_b" not in whitelist

    def test_filter_by_names(self):
        reg = self._make_registry()
        filtered = reg.filter({"tool_a", "tool_c"})
        assert len(filtered) == 2
        assert "tool_b" not in filtered

    def test_as_tools_dict(self):
        reg = self._make_registry()
        tools_dict = reg.as_tools_dict()
        assert callable(tools_dict["tool_a"])
        assert tools_dict["tool_a"]({}) == "ok"

    def test_build_prompt_block_contains_available_tools(self):
        reg = self._make_registry()
        block = reg.build_prompt_block()
        assert "AVAILABLE TOOLS" in block


# ==========================================================================
# Integration: real REGISTRY from registry.py
# ==========================================================================


class TestRealRegistry:
    def test_registry_has_tools(self):
        from src.tools.registry import REGISTRY

        assert len(REGISTRY) > 0

    def test_all_tools_have_executors(self):
        from src.tools.registry import REGISTRY

        for name in REGISTRY.names():
            spec = REGISTRY[name]
            assert callable(spec.executor), f"{name} has no callable executor"

    def test_web_search_in_registry(self):
        from src.tools.registry import REGISTRY

        assert "web_search" in REGISTRY

    def test_download_file_in_registry(self):
        from src.tools.registry import REGISTRY

        assert "download_file" in REGISTRY
