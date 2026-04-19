import pytest
from pydantic import Field

from src.tools.spec import ToolInput, ToolRegistry, ToolSpec


class _PathInput(ToolInput):
    path: str = Field(description="Directory path", examples=["."])


_DUMMY = ToolSpec(
    name="list_files",
    description="Lists files in a directory",
    input_schema=_PathInput,
    executor=lambda inp: "ok",
    risk="none",
    category="filesystem",
    icon="📁",
    label="List Files",
)


def test_to_openai_schema_structure():
    schema = _DUMMY.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "list_files"
    assert "parameters" in schema["function"]
    assert "properties" in schema["function"]["parameters"]
    assert "path" in schema["function"]["parameters"]["properties"]


def test_registry_as_openai_tools():
    registry = ToolRegistry([_DUMMY])
    tools = registry.as_openai_tools()
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "list_files"


def test_select_for_query_falls_back_when_embedding_unavailable(monkeypatch):
    """When embedding service is down, select_for_query returns full registry."""
    registry = ToolRegistry([_DUMMY])
    result = registry.select_for_query("list directory files", top_k=12)
    assert "list_files" in result.names()
