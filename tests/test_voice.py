import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.voice.voice_manager import _transcribe_audio

@patch('src.voice.voice_manager.os.getenv')
@patch('src.voice.voice_manager.requests.post')
@patch('src.config.STT_BACKEND', 'groq')
def test_transcribe_groq(mock_post, mock_getenv, tmp_path):
    mock_getenv.return_value = "default_key"
    dummy_audio = tmp_path / "dummy.wav"
    dummy_audio.write_bytes(b"dummy")

    mock_response = mock_post.return_value
    mock_response.status_code = 200
    mock_response.json.return_value = {"text": "Transcribed by groq"}

    result = _transcribe_audio(str(dummy_audio), "en")
    assert result == "Transcribed by groq"
    
    args, kwargs = mock_post.call_args
    assert "api.groq.com" in args[0]
    assert kwargs["data"]["model"] == "distil-whisper-large-v3-en"

@patch('src.config.STT_CUSTOM_URL', 'http://localhost:9000/transcribe', create=True)
@patch('src.config.STT_BACKEND', 'custom')
@patch('src.voice.voice_manager.requests.post')
def test_transcribe_custom(mock_post, tmp_path):
    dummy_audio = tmp_path / "dummy.wav"
    dummy_audio.write_bytes(b"dummy")

    mock_response = mock_post.return_value
    mock_response.status_code = 200
    mock_response.json.return_value = {"text": "Custom transcription"}

    result = _transcribe_audio(str(dummy_audio), "it")
    assert result == "Custom transcription"
    
    args, kwargs = mock_post.call_args
    assert args[0] == "http://localhost:9000/transcribe"


@patch('src.config.STT_BACKEND', 'unknown')
def test_transcribe_unknown(tmp_path):
    dummy_audio = tmp_path / "dummy.wav"
    dummy_audio.write_bytes(b"dummy")

    with pytest.raises(ValueError):
        _transcribe_audio(str(dummy_audio), "it")
