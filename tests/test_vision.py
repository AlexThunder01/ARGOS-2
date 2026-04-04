import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.vision import _call_vlm


@patch("src.vision.requests.post")
@patch("src.vision.VISION_API_KEY", "vision_key")
@patch("src.vision.VISION_BASE_URL", "https://api.openai.com/v1")
def test_vlm_openai_payload(mock_post):
    mock_response = mock_post.return_value
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Screen contents"}}]
    }

    result = _call_vlm("What is this?", "base64_img_data")

    assert result == "Screen contents"

    args, kwargs = mock_post.call_args
    payload = kwargs["json"]

    assert "chat/completions" in args[0]
    assert kwargs["headers"]["Authorization"] == "Bearer vision_key"
    assert "messages" in payload
    assert payload["messages"][0]["role"] == "user"
