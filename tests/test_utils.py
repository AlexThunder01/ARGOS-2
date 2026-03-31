"""
Test delle utility — extract_json e normalize_path.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import extract_json


def test_extract_json_clean():
    raw = '{"tool": "web_search", "input": {"query": "test"}}'
    result = extract_json(raw)
    assert result == {"tool": "web_search", "input": {"query": "test"}}


def test_extract_json_embedded_in_text():
    raw = 'Sto per eseguire: {"tool": "launch_app", "input": "firefox"} ora.'
    result = extract_json(raw)
    assert result is not None
    assert result["tool"] == "launch_app"


def test_extract_json_no_json():
    raw = "Ciao! Come posso aiutarti?"
    result = extract_json(raw)
    assert result is None


def test_extract_json_malformed():
    raw = '{"tool": "web_search", "input": {ROTTO'
    result = extract_json(raw)
    assert result is None


def test_extract_json_nested():
    raw = '{"thought": "ok", "action": {"tool": "read_file", "input": {"filename": "test.txt"}}, "done": false}'
    result = extract_json(raw)
    assert result["action"]["tool"] == "read_file"


def test_detect_backend():
    from unittest.mock import patch
    with patch('src.utils.LLM_BACKEND', 'openai-compatible'):
        from src.utils import detect_backend
        assert detect_backend() == "openai-compatible"

if __name__ == "__main__":
    test_extract_json_clean()
    test_extract_json_embedded_in_text()
    test_extract_json_no_json()
    test_extract_json_malformed()
    test_extract_json_nested()
    test_detect_backend()
    print("✅ Tutti i test utils passati.")
