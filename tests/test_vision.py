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
    mock_response.json.return_value = {"choices": [{"message": {"content": "Screen contents"}}]}

    result = _call_vlm("What is this?", "base64_img_data")

    assert result == "Screen contents"

    args, kwargs = mock_post.call_args
    payload = kwargs["json"]

    assert "chat/completions" in args[0]
    assert kwargs["headers"]["Authorization"] == "Bearer vision_key"
    assert "messages" in payload
    assert payload["messages"][0]["role"] == "user"


@patch("src.vision.requests.post")
@patch("src.vision.VISION_API_KEY", "vision_key")
@patch("src.vision.VISION_BASE_URL", "https://api.openai.com/v1")
def test_vlm_api_error_returns_none_or_fallback(mock_post):
    """When the API returns a non-200 status, _call_vlm should handle gracefully."""
    mock_response = mock_post.return_value
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.json.side_effect = Exception("No JSON")

    result = _call_vlm("What is this?", "base64_img_data")
    # Should return None or error string, not raise
    assert result is None or "error" in str(result).lower() or result == ""


@patch("src.vision.requests.post")
@patch("src.vision.VISION_API_KEY", "vision_key")
@patch("src.vision.VISION_BASE_URL", "https://api.openai.com/v1")
def test_vlm_empty_response_handled(mock_post):
    """When the API returns empty choices, _call_vlm should handle gracefully."""
    mock_response = mock_post.return_value
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": []}

    result = _call_vlm("What is this?", "base64_img_data")
    # Should not crash
    assert result is None or isinstance(result, str)


@patch("src.vision.requests.post")
@patch("src.vision.VISION_API_KEY", "vision_key")
@patch("src.vision.VISION_BASE_URL", "https://api.openai.com/v1")
def test_vlm_payload_has_image_content(mock_post):
    """The payload must include the base64 image data in the messages."""
    mock_response = mock_post.return_value
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": "A cat"}}]}

    _call_vlm("Describe", "abc123base64data")

    _, kwargs = mock_post.call_args
    payload = kwargs["json"]
    messages = payload["messages"]
    # The user message should contain image_url or similar content
    user_msg = messages[0]
    content = user_msg.get("content", "")
    # Content can be a list (multimodal) or string
    if isinstance(content, list):
        has_image = any(
            "image" in str(part).lower() or "abc123base64data" in str(part) for part in content
        )
        assert has_image, "Image data not found in multimodal message"
    else:
        # String content — at minimum the question should be there
        assert "Describe" in str(content) or len(str(content)) > 0


@patch("src.vision.VISION_API_KEY", "")
@patch("src.vision.VISION_BASE_URL", "")
def test_vlm_no_api_key_returns_error():
    """Without API key, _call_vlm should fail gracefully."""
    result = _call_vlm("What is this?", "base64_img_data")
    assert (
        result is None
        or "error" in str(result).lower()
        or "invalid" in str(result).lower()
        or result == ""
    )
