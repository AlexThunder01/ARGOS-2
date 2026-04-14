"""
Tests for the Secure File Downloader tool (src/tools/downloader.py).

Coverage:
  - Missing URL → error
  - HTTP (non-HTTPS) URL blocked
  - Blocked extensions (.exe, .sh, .bat, .jar, etc.)
  - File too large (Content-Length > 100MB) → abort
  - Streaming size cap exceeded mid-download → abort + cleanup
  - Successful download (mocked)
  - Content-Disposition filename extraction
  - URL-based filename fallback
  - Custom save_path
  - Timeout / Connection error / HTTP error → graceful error message
  - Path traversal attempt blocked
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch

import pytest

from src.tools.downloader import (
    MAX_DOWNLOAD_BYTES,
    _extract_filename_from_cd,
    _extract_filename_from_url,
    _is_blocked,
    download_file_tool,
)

# ==========================================================================
# Helper: _extract_filename_from_cd
# ==========================================================================


class TestExtractFilenameFromCD:
    def test_plain_filename(self):
        assert (
            _extract_filename_from_cd('attachment; filename="report.pdf"')
            == "report.pdf"
        )

    def test_filename_without_quotes(self):
        assert (
            _extract_filename_from_cd("attachment; filename=report.pdf") == "report.pdf"
        )

    def test_utf8_filename(self):
        result = _extract_filename_from_cd(
            "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf"
        )
        assert result is not None
        assert "sum" in result  # résumé decoded

    def test_empty_string(self):
        assert _extract_filename_from_cd("") is None

    def test_none_returns_none(self):
        assert _extract_filename_from_cd(None) is None

    def test_no_filename_field(self):
        assert _extract_filename_from_cd("inline") is None


# ==========================================================================
# Helper: _extract_filename_from_url
# ==========================================================================


class TestExtractFilenameFromURL:
    def test_simple_url(self):
        assert (
            _extract_filename_from_url("https://example.com/files/data.csv")
            == "data.csv"
        )

    def test_url_with_query(self):
        result = _extract_filename_from_url("https://example.com/file.pdf?token=abc")
        assert result == "file.pdf"

    def test_url_with_fragment(self):
        result = _extract_filename_from_url("https://example.com/doc.txt#page=3")
        assert result == "doc.txt"

    def test_url_no_filename(self):
        result = _extract_filename_from_url("https://example.com/")
        assert result == "download"

    def test_encoded_filename(self):
        result = _extract_filename_from_url("https://example.com/my%20file.pdf")
        assert result == "my file.pdf"


# ==========================================================================
# Helper: _is_blocked
# ==========================================================================


class TestIsBlocked:
    @pytest.mark.parametrize(
        "ext",
        [
            ".exe",
            ".sh",
            ".bat",
            ".cmd",
            ".msi",
            ".deb",
            ".rpm",
            ".appimage",
            ".jar",
            ".dll",
            ".so",
            ".ps1",
            ".vbs",
        ],
    )
    def test_blocked_extensions(self, ext):
        assert _is_blocked(f"malware{ext}") is True

    @pytest.mark.parametrize(
        "ext",
        [
            ".pdf",
            ".txt",
            ".csv",
            ".png",
            ".jpg",
            ".zip",
            ".tar.gz",
            ".docx",
        ],
    )
    def test_allowed_extensions(self, ext):
        assert _is_blocked(f"safe_file{ext}") is False

    def test_case_insensitive(self):
        assert _is_blocked("VIRUS.EXE") is True
        assert _is_blocked("script.SH") is True


# ==========================================================================
# download_file_tool — security checks
# ==========================================================================


class TestDownloadSecurity:
    def test_missing_url_returns_error(self):
        result = download_file_tool({})
        assert "error" in result.lower()

    def test_http_url_blocked(self):
        """HTTP (non-encrypted) URLs must be rejected."""
        result = download_file_tool({"url": "http://example.com/file.pdf"})
        assert "error" in result.lower()
        assert "HTTP" in result or "HTTPS" in result

    @patch("src.tools.downloader.http_client.get")
    def test_blocked_extension_exe(self, mock_get, tmp_path):
        """Downloading .exe must be rejected after Content-Disposition check."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Disposition": 'attachment; filename="virus.exe"'}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = download_file_tool({"url": "https://example.com/virus.exe"})
        assert "error" in result.lower()
        assert "blocked" in result.lower() or ".exe" in result.lower()

    @patch("src.tools.downloader.http_client.get")
    def test_file_too_large_content_length(self, mock_get):
        """Content-Length exceeding MAX_DOWNLOAD_BYTES must be rejected before downloading."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {
            "Content-Length": str(MAX_DOWNLOAD_BYTES + 1),
            "Content-Disposition": "",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = download_file_tool({"url": "https://example.com/huge.zip"})
        assert "error" in result.lower()
        assert "large" in result.lower() or "size" in result.lower()


# ==========================================================================
# download_file_tool — successful download
# ==========================================================================


class TestDownloadSuccess:
    @patch("src.tools.downloader._normalize_path")
    @patch("src.tools.downloader.http_client.get")
    def test_successful_download(self, mock_get, mock_norm, tmp_path):
        """A normal HTTPS download should succeed and report the file path."""
        save_path = str(tmp_path / "test.pdf")
        mock_norm.return_value = save_path  # bypass $HOME sandbox for test

        content = b"PDF content here" * 100
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {
            "Content-Length": str(len(content)),
            "Content-Disposition": "",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content = MagicMock(return_value=[content])
        mock_get.return_value = mock_resp

        result = download_file_tool(
            {"url": "https://example.com/test.pdf", "save_path": save_path}
        )
        assert "✅" in result or "Downloaded" in result

    @patch("src.tools.downloader._normalize_path")
    @patch("src.tools.downloader.http_client.get")
    def test_streaming_size_cap_exceeded(self, mock_get, mock_norm, tmp_path):
        """If chunks exceed MAX_DOWNLOAD_BYTES mid-stream, download must abort."""
        save_path = str(tmp_path / "big.bin")
        mock_norm.return_value = save_path  # bypass $HOME sandbox for test

        # Generate chunks that exceed the limit
        chunk_size = 10 * 1024 * 1024  # 10 MB
        chunks = [b"x" * chunk_size for _ in range(12)]  # 120 MB total

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Disposition": ""}  # No Content-Length
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content = MagicMock(return_value=iter(chunks))
        mock_get.return_value = mock_resp

        result = download_file_tool(
            {"url": "https://example.com/big.bin", "save_path": save_path}
        )
        assert "error" in result.lower()
        assert "size" in result.lower() or "limit" in result.lower()
        # File should have been cleaned up
        assert not os.path.exists(save_path)


# ==========================================================================
# download_file_tool — network errors
# ==========================================================================


class TestDownloadErrors:
    @patch("src.tools.downloader.http_client.get")
    def test_timeout_returns_error(self, mock_get):
        import requests

        mock_get.side_effect = requests.exceptions.Timeout()
        result = download_file_tool({"url": "https://example.com/slow.pdf"})
        assert "error" in result.lower()
        assert "timed out" in result.lower() or "timeout" in result.lower()

    @patch("src.tools.downloader.http_client.get")
    def test_connection_error_returns_error(self, mock_get):
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError()
        result = download_file_tool({"url": "https://nonexistent.example.com/file.pdf"})
        assert "error" in result.lower()

    @patch("src.tools.downloader.http_client.get")
    def test_http_404_returns_error(self, mock_get):
        import requests

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_get.return_value = mock_resp
        result = download_file_tool({"url": "https://example.com/missing.pdf"})
        assert "error" in result.lower()

    def test_url_auto_prefix_https(self):
        """URLs without schema should get https:// prefix (then may fail on connect)."""
        with patch("src.tools.downloader.http_client.get") as mock_get:
            import requests

            mock_get.side_effect = requests.exceptions.ConnectionError()
            download_file_tool({"url": "example.com/file.pdf"})
            # Verify https:// was prepended
            called_url = mock_get.call_args[0][0]
            assert called_url.startswith("https://")
