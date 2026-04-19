"""
Tests for the CoreAgent unified engine (src/core/engine.py).

Verifies:
  - Initialization with all memory modes
  - User ID generation from Linux username
  - Authorization callback logic
  - Security pipeline integration
  - Memory mode switching
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock

import pytest

from src.core.engine import CoreAgent, TaskResult

# ==========================================================================
# CoreAgent Initialization
# ==========================================================================


class TestCoreAgentInit:
    """Tests for CoreAgent initialization and configuration."""

    def test_init_default_memory_off(self):
        """Default memory mode should be 'off'."""
        agent = CoreAgent()
        assert agent.memory_mode == "off"

    def test_init_session_memory(self):
        agent = CoreAgent(memory_mode="session")
        assert agent.memory_mode == "session"
        assert len(agent._session_memories) == 0

    def test_init_persistent_memory(self):
        agent = CoreAgent(memory_mode="persistent")
        assert agent.memory_mode == "persistent"

    def test_init_invalid_memory_mode(self):
        with pytest.raises(ValueError, match="Invalid memory_mode"):
            CoreAgent(memory_mode="invalid")

    def test_init_custom_user_id(self):
        agent = CoreAgent(user_id=42)
        assert agent.user_id == 42

    def test_init_auto_user_id_from_env(self):
        """User ID should be derived from $USER via sha256 hash."""
        linux_user = os.environ.get("USER", "argos")
        expected = int(hashlib.sha256(linux_user.encode()).hexdigest()[:16], 16) % (2**31)
        agent = CoreAgent()
        assert agent.user_id == expected

    def test_init_max_steps(self):
        agent = CoreAgent(max_steps=20)
        assert agent.max_steps == 20

    def test_init_require_confirmation(self):
        agent = CoreAgent(require_confirmation=True)
        assert agent.require_confirmation is True

    def test_backend_property(self):
        agent = CoreAgent()
        assert isinstance(agent.backend, str)
        assert len(agent.backend) > 0

    def test_model_property(self):
        agent = CoreAgent()
        assert isinstance(agent.model, str)
        assert len(agent.model) > 0


# ==========================================================================
# Authorization Logic
# ==========================================================================


class TestAuthorization:
    """Tests for the security gate / authorization callback."""

    def test_safe_tool_always_allowed(self):
        """Tools not in the dangerous list should always pass."""
        agent = CoreAgent(require_confirmation=True)
        assert agent._authorize_tool("web_search", {"query": "test"}) is True
        assert agent._authorize_tool("system_stats", {}) is True

    def test_dangerous_tool_blocked_by_require_confirmation(self):
        """When require_confirmation=True, dangerous tools should be auto-blocked."""
        agent = CoreAgent(require_confirmation=True)
        assert agent._authorize_tool("create_file", {"filename": "test.txt"}) is False
        assert agent._authorize_tool("delete_file", {"filename": "test.txt"}) is False

    def test_dangerous_tool_allowed_with_callback_yes(self):
        """When a callback returns True, the tool should proceed."""
        callback = MagicMock(return_value=True)
        agent = CoreAgent(confirmation_callback=callback)
        assert agent._authorize_tool("create_file", {"filename": "test.txt"}) is True
        callback.assert_called_once_with("create_file", {"filename": "test.txt"})

    def test_dangerous_tool_denied_with_callback_no(self):
        """When a callback returns False, the tool should be denied."""
        callback = MagicMock(return_value=False)
        agent = CoreAgent(confirmation_callback=callback)
        assert agent._authorize_tool("delete_file", {"filename": "test.txt"}) is False

    def test_dangerous_tool_allowed_by_default(self):
        """When no confirmation is required and no callback, dangerous tools should pass."""
        agent = CoreAgent()
        assert agent._authorize_tool("create_file", {"filename": "test.txt"}) is True


# ==========================================================================
# Memory Modes
# ==========================================================================


class TestMemoryModes:
    """Tests for the three memory modes (off, session, persistent)."""

    def test_off_mode_returns_empty(self):
        agent = CoreAgent(memory_mode="off")
        memories = agent._retrieve_memories("anything")
        assert memories == []

    def test_session_mode_stores_and_retrieves(self):
        agent = CoreAgent(memory_mode="session")
        agent._session_memories = [
            {"content": "User likes Python programming", "category": "interest"},
            {"content": "User works at ACME Corp", "category": "fact"},
        ]
        results = agent._retrieve_memories("Tell me about Python")
        assert len(results) > 0
        assert any("Python" in m["content"] for m in results)

    def test_session_mode_no_match(self):
        agent = CoreAgent(memory_mode="session")
        agent._session_memories = [
            {"content": "User likes pizza", "category": "preference"},
        ]
        # Short words (<=3 chars) are filtered out
        results = agent._retrieve_memories("What is AI?")
        assert results == []


# ==========================================================================
# TaskResult Data Model
# ==========================================================================


class TestTaskResult:
    """Tests for the TaskResult dataclass."""

    def test_task_result_creation(self):
        result = TaskResult(
            success=True,
            task="test",
            response="done",
            steps_executed=1,
        )
        assert result.success is True
        assert result.task == "test"
        assert result.steps_executed == 1
        assert result.history == []
        assert result.memories_used == 0
