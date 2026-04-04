import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import JarvisAgent


@patch("src.agent.requests.post")
def test_call_openai_compatible(mock_post):
    # Setup mock
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello OpenAI!"}}]
    }
    mock_post.return_value = mock_response

    # Setup agent
    agent = JarvisAgent()
    agent.backend = "openai-compatible"
    agent.add_message("user", "Hello")

    # Call
    result = agent.think()

    # Assertions
    assert result == "Hello OpenAI!"
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "chat/completions" in args[0]
    assert kwargs["json"]["messages"][-1]["content"] == "Hello"


@patch("src.agent.requests.post")
def test_call_anthropic(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"content": [{"text": "Hello Anthropic!"}]}
    mock_post.return_value = mock_response

    agent = JarvisAgent()
    agent.backend = "anthropic"
    agent.add_message("user", "Hi")

    result = agent.think()

    assert result == "Hello Anthropic!"
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "messages" in args[0]
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"


@patch("src.agent.time.sleep")
@patch("src.agent.requests.post")
def test_openai_compatible_key_rotation(mock_post, mock_sleep):
    # Simulate first call getting 429
    call_1 = MagicMock()
    call_1.status_code = 429

    # Simulate second call matching
    call_2 = MagicMock()
    call_2.status_code = 200
    call_2.json.return_value = {
        "choices": [{"message": {"content": "Hello on retry!"}}]
    }

    mock_post.side_effect = [call_1, call_2]

    agent = JarvisAgent()
    # Mock config to have 2 keys
    with (
        patch("src.agent.LLM_API_KEY_2", "second_key", create=True),
        patch("src.agent.LLM_API_KEY", "first_key", create=True),
    ):
        # We need to mock module-level locals imported in _call_openai_compatible
        pass

    # Python 3 mock dict trick
    with patch.multiple(
        sys.modules["src.agent"], LLM_API_KEY="f", LLM_API_KEY_2="s", create=True
    ):
        # We actually modified local imports in agent.py methods
        pass

    # The safest way is to mock requests directly
    from src import config

    config.LLM_API_KEY = "f"
    config.LLM_API_KEY_2 = "s"

    result = agent._call_openai_compatible([], temperature=0.0, retries=0)
    assert result == "Hello on retry!"
    assert mock_post.call_count == 2
