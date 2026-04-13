"""
Test del WorldState — verifica il tracking delle azioni e la generazione del contesto.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.world_model.state import WorldState


def test_initial_state():
    s = WorldState()
    assert s.step_count == 0
    assert s.action_history == []
    assert s.current_task == ""
    assert s.task_done is False


def test_record_action_success():
    s = WorldState()
    s.current_task = "Test"
    s.record_action("web_search", {"q": "test"}, "Result ok", True)
    assert s.step_count == 1
    assert len(s.action_history) == 1
    assert s.action_history[0].success is True
    assert s.last_error is None


def test_record_action_failure():
    s = WorldState()
    s.record_action("delete_file", "foo.txt", "Error: file not found", False)
    assert s.step_count == 1
    assert s.last_error == "Error: file not found"


def test_to_context_string_contains_task():
    s = WorldState()
    s.current_task = "Apri Firefox"
    s.record_action("launch_app", "firefox", "🚀 Lanciato: firefox", True)
    ctx = s.to_context_string()
    assert "Apri Firefox" in ctx
    assert "launch_app" in ctx


def test_to_context_string_max_3_steps():
    s = WorldState()
    s.current_task = "Test"
    for i in range(6):
        s.record_action(f"tool_{i}", {}, f"result_{i}", True)
    ctx = s.to_context_string()
    # Solo gli ultimi 3 devono apparire
    assert "tool_5" in ctx
    assert "tool_0" not in ctx


def test_reset():
    s = WorldState()
    s.current_task = "Test"
    s.record_action("web_search", {}, "ok", True)
    s.reset()
    assert s.step_count == 0
    assert s.action_history == []
    assert s.last_error is None



