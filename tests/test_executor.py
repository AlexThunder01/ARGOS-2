"""
Test dell'Executor — verifica retry, classificazione errori e successo.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.executor.executor import execute_with_retry, _classify_error
from src.actions.base import ActionStatus


def test_execute_success():
    """Un tool che ritorna stringa normale → SUCCESS."""
    result = execute_with_retry(lambda inp: "✅ Ok", None, "mock_tool", max_retries=1)
    assert result.status == ActionStatus.SUCCESS
    assert result.success is True


def test_execute_fatal_error_no_retry():
    """Fatal error (file not found) → FAILED without retry."""
    calls = []
    def tool(inp):
        calls.append(1)
        return "Error: file not found"
    result = execute_with_retry(tool, None, "delete_file", max_retries=3)
    assert result.status == ActionStatus.FAILED
    assert len(calls) == 1  # mai fatto retry


def test_execute_exception_retries():
    """Eccezione Python → retry fino a max_retries."""
    calls = []
    def tool(inp):
        calls.append(1)
        raise ConnectionError("timeout")
    result = execute_with_retry(tool, None, "web_search", max_retries=2)
    assert result.status == ActionStatus.FAILED
    assert len(calls) == 2  # ha riprovato


def test_execute_succeeds_on_second_try():
    """Tool che fallisce al primo tentativo poi riesce."""
    calls = []
    def tool(inp):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("timeout")
        return "✅ Successo al secondo tentativo"
    result = execute_with_retry(tool, None, "api_call", max_retries=3)
    assert result.status == ActionStatus.SUCCESS
    assert len(calls) == 2


def test_classify_error_fatal():
    assert _classify_error("Error: file not found") is False
    assert _classify_error("Target is a directory, use list_files instead") is False


def test_classify_error_retryable():
    assert _classify_error("API Error timeout") is True
    assert _classify_error("Connection Error network") is True


if __name__ == "__main__":
    test_execute_success()
    test_execute_fatal_error_no_retry()
    test_execute_exception_retries()
    test_execute_succeeds_on_second_try()
    test_classify_error_fatal()
    test_classify_error_retryable()
    print("✅ Tutti i test Executor passati.")
