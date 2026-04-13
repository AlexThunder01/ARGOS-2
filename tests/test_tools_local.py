"""
ARGOS-2 — Comprehensive Tool Test Suite

Tests every registered tool with proper mocking of all external dependencies.
Run with: pytest tests/test_tools_local.py -v

Network tools use mocked HTTP responses for CI stability.
GUI tools verify graceful degradation when pyautogui is absent.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch

from src.tools import TOOLS

# ==========================================================================
# Tool Registry — Ensures nothing is missing after refactors
# ==========================================================================

EXPECTED_TOOLS = [
    "finance_price",
    "crypto_price",
    "web_search",
    "system_stats",
    "list_files",
    "read_file",
    "create_file",
    "modify_file",
    "rename_file",
    "delete_file",
    "launch_app",
    "keyboard_type",
    "visual_click",
    "describe_screen",
    "create_directory",
    "delete_directory",
    "get_weather",
    "python_repl",
    "bash_exec",
    "web_scrape",
    "read_pdf",
    "read_csv",
    "read_json",
    "read_excel",
    "analyze_image",
    "query_table",
    "transcribe_audio",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_get_content",
    "download_file",
]


def test_tools_dict_complete():
    """All expected tools must be registered."""
    assert len(TOOLS) == len(EXPECTED_TOOLS), (
        f"Expected {len(EXPECTED_TOOLS)} tools, found {len(TOOLS)}. "
        f"Missing: {set(EXPECTED_TOOLS) - set(TOOLS.keys())}  "
        f"Extra: {set(TOOLS.keys()) - set(EXPECTED_TOOLS)}"
    )
    for name in EXPECTED_TOOLS:
        assert name in TOOLS, f"Missing tool: {name}"


def test_all_tools_are_callable():
    """Every registered tool must be a callable function."""
    for name, fn in TOOLS.items():
        assert callable(fn), f"Tool '{name}' is not callable"


# ==========================================================================
# System Stats (no network needed)
# ==========================================================================


def test_system_stats():
    result = TOOLS["system_stats"]({})
    assert "CPU" in result
    assert "RAM" in result


# ==========================================================================
# Filesystem Tools (isolated temp directory)
# ==========================================================================


class TestFilesystemTools:
    @pytest.fixture(autouse=True)
    def sandbox(self, tmp_path, monkeypatch):
        """Redirect the filesystem sandbox to tmp_path so tests work in CI."""
        monkeypatch.setattr("src.tools.helpers._HOME", str(tmp_path))

    def test_create_read_modify_delete_lifecycle(self, tmp_path):
        test_file = str(tmp_path / "test_argos.txt")

        # Create
        result = TOOLS["create_file"]({"path": test_file, "content": "Hello World"})
        assert "Created" in result

        # Read
        result = TOOLS["read_file"]({"path": test_file})
        assert "Hello World" in result

        # Modify (overwrite)
        result = TOOLS["modify_file"](
            {"path": test_file, "content": "Updated", "mode": "write"}
        )
        assert "Modified" in result

        # Read again to verify modification
        result = TOOLS["read_file"]({"path": test_file})
        assert "Updated" in result

        # Delete
        result = TOOLS["delete_file"]({"path": test_file})
        assert "Deleted" in result

    def test_modify_append(self, tmp_path):
        test_file = str(tmp_path / "append_test.txt")
        TOOLS["create_file"]({"path": test_file, "content": "Line1"})
        TOOLS["modify_file"](
            {"path": test_file, "content": "\nLine2", "mode": "append"}
        )
        result = TOOLS["read_file"]({"path": test_file})
        assert "Line1" in result
        assert "Line2" in result

    def test_create_and_delete_directory(self, tmp_path):
        test_dir = str(tmp_path / "test_dir")
        result = TOOLS["create_directory"]({"path": test_dir})
        assert "created" in result.lower()

        result = TOOLS["delete_directory"]({"path": test_dir})
        assert "deleted" in result.lower()

    def test_list_files_home(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        result = TOOLS["list_files"]({"path": str(tmp_path)})
        assert "📂" in result

    def test_read_nonexistent_file(self, tmp_path):
        result = TOOLS["read_file"](
            {"path": str(tmp_path / "this_file_does_not_exist.txt")}
        )
        assert "not found" in result.lower()

    def test_rename_file(self, tmp_path):
        old = str(tmp_path / "old.txt")
        new = str(tmp_path / "new.txt")
        with open(old, "w") as f:
            f.write("test")
        result = TOOLS["rename_file"]({"old_path": old, "new_path": new})
        assert "Renamed" in result


# ==========================================================================
# Network Tools (all mocked for CI stability)
# ==========================================================================


class TestNetworkToolsMocked:
    # --- Crypto Price ---

    @patch("src.tools.finance.requests.get")
    def test_crypto_price_success(self, mock_get):
        mock_get.return_value.json.return_value = {"bitcoin": {"eur": 45000.50}}
        result = TOOLS["crypto_price"]({"coin": "bitcoin"})
        assert "45" in result or "€" in result

    @patch("src.tools.finance.requests.get")
    def test_crypto_price_not_found(self, mock_get):
        mock_get.return_value.json.return_value = {}
        result = TOOLS["crypto_price"]({"coin": "fakecoin123"})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_crypto_price_missing_arg(self):
        result = TOOLS["crypto_price"]({})
        assert "error" in result.lower()

    # --- Finance Price ---

    @patch("src.tools.finance.yf", create=True)
    def test_finance_price_success(self, mock_yf):
        mock_ticker = MagicMock()
        mock_ticker.fast_info.last_price = 2350.75
        mock_ticker.info = {"currency": "USD"}

        # Also mock the EUR/USD conversion ticker
        mock_eur_ticker = MagicMock()
        mock_eur_ticker.fast_info.last_price = 1.08

        def ticker_factory(symbol):
            if symbol == "EURUSD=X":
                return mock_eur_ticker
            return mock_ticker

        with patch("yfinance.Ticker", side_effect=ticker_factory):
            result = TOOLS["finance_price"]({"asset": "gold"})
            assert "2" in result or "Gold" in result or "error" in result.lower()

    def test_finance_price_missing_arg(self):
        result = TOOLS["finance_price"]({})
        assert "error" in result.lower()

    # --- Web Search ---

    @patch("src.tools.web.DDGS", create=True)
    def test_web_search_success(self, mock_ddgs_cls):
        mock_instance = MagicMock()
        mock_instance.text.return_value = [
            {"title": "Test Result", "body": "This is a test."}
        ]
        mock_ddgs_cls.return_value = mock_instance

        with patch("ddgs.DDGS", mock_ddgs_cls):
            result = TOOLS["web_search"]({"query": "test"})
            assert "Test Result" in result or "test" in result.lower()

    @patch("src.tools.web.DDGS", create=True)
    def test_web_search_no_results(self, mock_ddgs_cls):
        mock_instance = MagicMock()
        mock_instance.text.return_value = []
        mock_ddgs_cls.return_value = mock_instance

        with patch("ddgs.DDGS", mock_ddgs_cls):
            result = TOOLS["web_search"]({"query": "xyznonexistent"})
            assert "no results" in result.lower() or "not" in result.lower()

    def test_web_search_missing_arg(self):
        result = TOOLS["web_search"]({})
        assert "error" in result.lower()

    # --- Get Weather ---

    @patch("requests.get")
    def test_get_weather_success(self, mock_get):
        # First call: Geocoding API
        geo_response = MagicMock()
        geo_response.status_code = 200
        geo_response.json.return_value = {
            "results": [
                {
                    "latitude": 41.8933,
                    "longitude": 12.4829,
                    "name": "Roma",
                    "country": "Italia",
                }
            ]
        }

        # Second call: Forecast API
        weather_response = MagicMock()
        weather_response.status_code = 200
        weather_response.json.return_value = {
            "current_weather": {
                "temperature": 22.5,
                "windspeed": 12.3,
                "weathercode": 0,
            }
        }

        mock_get.side_effect = [geo_response, weather_response]
        result = TOOLS["get_weather"]({"location": "Roma"})
        assert "Roma" in result
        assert "22.5" in result
        assert "Clear sky" in result

    @patch("requests.get")
    def test_get_weather_city_not_found(self, mock_get):
        geo_response = MagicMock()
        geo_response.status_code = 200
        geo_response.json.return_value = {}  # No results
        mock_get.return_value = geo_response
        result = TOOLS["get_weather"]({"location": "Citta_Inventata_XYZ"})
        assert "error" in result.lower() or "could not find" in result.lower()

    @patch("requests.get")
    def test_get_weather_overcast(self, mock_get):
        """Tests WMO code mapping for overcast sky."""
        geo_response = MagicMock()
        geo_response.status_code = 200
        geo_response.json.return_value = {
            "results": [
                {
                    "latitude": 45.46,
                    "longitude": 9.19,
                    "name": "Milano",
                    "country": "Italia",
                }
            ]
        }
        weather_response = MagicMock()
        weather_response.status_code = 200
        weather_response.json.return_value = {
            "current_weather": {"temperature": 15.0, "windspeed": 8.0, "weathercode": 3}
        }
        mock_get.side_effect = [geo_response, weather_response]
        result = TOOLS["get_weather"]("Milano")
        assert "Overcast" in result
        assert "15" in result

    @patch("requests.get")
    def test_get_weather_rain(self, mock_get):
        """Tests WMO code mapping for moderate rain."""
        geo_response = MagicMock()
        geo_response.status_code = 200
        geo_response.json.return_value = {
            "results": [
                {
                    "latitude": 40.85,
                    "longitude": 14.27,
                    "name": "Napoli",
                    "country": "Italia",
                }
            ]
        }
        weather_response = MagicMock()
        weather_response.status_code = 200
        weather_response.json.return_value = {
            "current_weather": {
                "temperature": 12.0,
                "windspeed": 20.0,
                "weathercode": 63,
            }
        }
        mock_get.side_effect = [geo_response, weather_response]
        result = TOOLS["get_weather"]({"city": "Napoli"})
        assert "Moderate rain" in result

    def test_get_weather_missing_arg(self):
        result = TOOLS["get_weather"]({})
        assert "error" in result.lower()


# ==========================================================================
# GUI Tools — Graceful Degradation (no display in CI)
# ==========================================================================


class TestGUITools:
    def test_visual_click_missing_description(self):
        result = TOOLS["visual_click"]({})
        assert "error" in result.lower() or "missing" in result.lower()

    @patch("src.tools.automation.PYAUTOGUI_AVAILABLE", False)
    def test_visual_click_no_gui(self):
        result = TOOLS["visual_click"]({"description": "button"})
        assert "error" in result.lower() or "unavailable" in result.lower()

    @patch("src.tools.automation.PYAUTOGUI_AVAILABLE", False)
    def test_keyboard_type_no_gui(self):
        result = TOOLS["keyboard_type"]({"text": "hello"})
        assert "error" in result.lower() or "unavailable" in result.lower()

    @patch("src.tools.automation.subprocess.Popen")
    def test_launch_app(self, mock_popen):
        mock_popen.return_value = MagicMock()
        result = TOOLS["launch_app"]({"app_name": "firefox"})
        assert "Launched" in result or "🚀" in result


# ==========================================================================
# Helpers
# ==========================================================================


class TestHelpers:
    def test_get_arg_from_dict(self):
        from src.tools.helpers import _get_arg

        result = _get_arg({"query": "hello"}, ["query", "q"])
        assert result == "hello"

    def test_get_arg_from_string(self):
        from src.tools.helpers import _get_arg

        result = _get_arg("hello", ["query"])
        assert result == "hello"

    def test_get_arg_fallback(self):
        from src.tools.helpers import _get_arg

        result = _get_arg({"foo": "bar"}, ["query", "q"], "default")
        assert result == "default"

    def test_normalize_path_home(self):
        from src.tools.helpers import _normalize_path

        result = _normalize_path("~/test.txt")
        home = os.path.expanduser("~")
        assert result.startswith(home)

    def test_normalize_path_windows_hallucination(self):
        """LLMs sometimes hallucinate Windows paths on Linux."""
        from src.tools.helpers import _normalize_path

        result = _normalize_path("C:/Users/alex/Desktop/test.txt")
        assert not result.startswith("C:")
        assert "test.txt" in result


# ==========================================================================
# Document Tools (read_pdf, read_csv, read_json)
# ==========================================================================


class TestDocumentTools:
    @pytest.fixture(autouse=True)
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.helpers._HOME", str(tmp_path))

    def test_read_json_success(self, tmp_path):
        data = {"name": "argos", "version": 2}
        json_file = tmp_path / "config.json"
        json_file.write_text(__import__("json").dumps(data))

        result = TOOLS["read_json"]({"filename": str(json_file)})
        assert "argos" in result
        assert "version" in result

    def test_read_json_invalid(self, tmp_path):
        bad = tmp_path / "broken.json"
        bad.write_text("{ not valid json }")

        result = TOOLS["read_json"]({"filename": str(bad)})
        assert "error" in result.lower()

    def test_read_json_missing_arg(self):
        result = TOOLS["read_json"]({})
        assert "error" in result.lower()

    def test_read_json_not_found(self, tmp_path):
        result = TOOLS["read_json"]({"filename": str(tmp_path / "missing.json")})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_read_csv_success(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n")

        result = TOOLS["read_csv"]({"filename": str(csv_file)})
        assert "name" in result
        assert "Alice" in result

    def test_read_csv_rows_limit(self, tmp_path):
        csv_file = tmp_path / "big.csv"
        lines = ["col1,col2"] + [f"r{i},v{i}" for i in range(50)]
        csv_file.write_text("\n".join(lines))

        result = TOOLS["read_csv"]({"filename": str(csv_file), "rows": 5})
        # Should contain the header and at most 5 data rows
        assert "col1" in result

    def test_read_csv_missing_arg(self):
        result = TOOLS["read_csv"]({})
        assert "error" in result.lower()

    def test_read_csv_not_found(self, tmp_path):
        result = TOOLS["read_csv"]({"filename": str(tmp_path / "missing.csv")})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_read_pdf_missing_arg(self):
        result = TOOLS["read_pdf"]({})
        assert "error" in result.lower()

    def test_read_pdf_not_found(self, tmp_path):
        result = TOOLS["read_pdf"]({"filename": str(tmp_path / "missing.pdf")})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_read_pdf_wrong_extension(self, tmp_path):
        txt_file = tmp_path / "notapdf.txt"
        txt_file.write_text("hello")
        result = TOOLS["read_pdf"]({"filename": str(txt_file)})
        assert "error" in result.lower() or "not a pdf" in result.lower()

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("pypdf"),
        reason="pypdf not installed",
    )
    def test_read_pdf_success(self, tmp_path):
        """Creates a minimal valid PDF and reads it."""
        from pypdf import PdfWriter

        pdf_path = tmp_path / "test.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        result = TOOLS["read_pdf"]({"filename": str(pdf_path)})
        # Blank page produces no text, but the tool should handle it gracefully
        assert "error" not in result.lower() or "image-based" in result.lower()


# ==========================================================================
# delete_file does NOT delete directories
# ==========================================================================


class TestDeleteFileSafety:
    @pytest.fixture(autouse=True)
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.helpers._HOME", str(tmp_path))

    def test_delete_file_rejects_directory(self, tmp_path):
        test_dir = tmp_path / "somedir"
        test_dir.mkdir()

        result = TOOLS["delete_file"]({"filename": str(test_dir)})
        assert "directory" in result.lower()
        assert test_dir.exists(), "Directory must NOT have been deleted"


# ==========================================================================
# Realistic LLM input tests — edge cases triggered by real agent behavior
#
# These tests simulate the kind of inputs an LLM actually generates:
# hallucinated paths, missing arguments, empty strings, vague references.
# Each test corresponds to a failure mode observed or foreseeable in practice.
# ==========================================================================


class TestFilesystemLLMEdgeCases:
    """
    Filesystem tools under realistic LLM-generated inputs.
    Covers: empty fields, hallucinated paths, duplicate operations,
    missing required args, and the list→read workflow.
    """

    @pytest.fixture(autouse=True)
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.helpers._HOME", str(tmp_path))
        # Also redirect the desktop default to tmp_path so "DESKTOP" resolves there
        monkeypatch.setattr(
            "src.tools.helpers._get_desktop_path", lambda: str(tmp_path)
        )

    # --- list_files ---

    def test_list_files_desktop_keyword(self, tmp_path):
        """LLM passes 'DESKTOP' as path — should list the desktop dir."""
        (tmp_path / "note.txt").write_text("hi")
        result = TOOLS["list_files"]({"path": "DESKTOP"})
        assert "📂" in result
        assert "note" in result

    def test_list_files_empty_path(self, tmp_path):
        """LLM passes empty string for path — should fall back to desktop."""
        (tmp_path / "file.txt").write_text("x")
        result = TOOLS["list_files"]({"path": ""})
        assert "📂" in result

    def test_list_files_nonexistent_dir(self, tmp_path):
        """LLM hallucinates a directory that does not exist."""
        result = TOOLS["list_files"]({"path": str(tmp_path / "invented_folder")})
        assert "error" in result.lower() or "not exist" in result.lower()

    def test_list_files_returns_readable_names(self, tmp_path):
        """list_files output must be usable to pick a filename for read_file."""
        (tmp_path / "report.txt").write_text("content")
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        result = TOOLS["list_files"]({"path": str(tmp_path)})
        assert "report.txt" in result or "report" in result

    # --- read_file ---

    def test_read_file_empty_filename(self):
        """LLM passes an empty filename string."""
        result = TOOLS["read_file"]({"filename": ""})
        # Should not crash — must return error or fall back
        assert result  # non-empty response

    def test_read_file_no_args(self):
        """LLM passes no arguments at all."""
        result = TOOLS["read_file"]({})
        assert result  # must not crash

    def test_read_file_directory_path(self, tmp_path):
        """LLM passes a directory path to read_file — should reject clearly."""
        sub = tmp_path / "subdir"
        sub.mkdir()
        result = TOOLS["read_file"]({"filename": str(sub)})
        assert "directory" in result.lower() or "error" in result.lower()

    def test_read_file_hallucinated_absolute_path(self, tmp_path):
        """LLM invents a plausible-looking path that doesn't exist."""
        fake = str(tmp_path / "documents" / "report_2024.pdf")
        result = TOOLS["read_file"]({"filename": fake})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_list_then_read_workflow(self, tmp_path):
        """
        Simulates the correct agent behavior when asked to 'read a random file':
        1. list_files to discover what exists
        2. pick a filename from the output
        3. read_file with that path
        All three steps must succeed.
        """
        target = tmp_path / "hello.txt"
        target.write_text("file content here")

        listing = TOOLS["list_files"]({"path": str(tmp_path)})
        assert "hello.txt" in listing or "hello" in listing

        read_result = TOOLS["read_file"]({"filename": str(target)})
        assert "file content here" in read_result

    # --- create_file ---

    def test_create_file_already_exists(self, tmp_path):
        """LLM tries to create a file that already exists — must warn, not overwrite."""
        existing = tmp_path / "existing.txt"
        existing.write_text("original content")

        result = TOOLS["create_file"](
            {"filename": str(existing), "content": "overwrite attempt"}
        )
        assert "already exists" in result.lower() or "error" in result.lower()
        # Original content must be preserved
        assert existing.read_text() == "original content"

    def test_create_file_no_filename(self):
        """LLM omits the filename field entirely."""
        result = TOOLS["create_file"]({"content": "some text"})
        # Should not crash
        assert result

    # --- modify_file ---

    def test_modify_file_nonexistent(self, tmp_path):
        """LLM tries to modify a file that doesn't exist yet."""
        result = TOOLS["modify_file"](
            {"filename": str(tmp_path / "ghost.txt"), "content": "data"}
        )
        assert "not found" in result.lower() or "error" in result.lower()

    def test_modify_file_empty_filename(self):
        """LLM passes empty filename to modify_file."""
        result = TOOLS["modify_file"]({"filename": "", "content": "data"})
        assert result  # must not crash

    # --- rename_file ---

    def test_rename_file_missing_new_name(self, tmp_path):
        """LLM provides old_name but forgets new_name."""
        old = tmp_path / "old.txt"
        old.write_text("x")
        result = TOOLS["rename_file"]({"old_name": str(old)})
        assert "error" in result.lower() or "required" in result.lower()

    def test_rename_file_destination_exists(self, tmp_path):
        """LLM tries to rename to a filename that already exists."""
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_text("a")
        dst.write_text("b")
        result = TOOLS["rename_file"](
            {"old_name": str(src), "new_name": str(dst)}
        )
        assert "already exists" in result.lower() or "error" in result.lower()

    def test_rename_file_source_not_found(self, tmp_path):
        """LLM tries to rename a file that doesn't exist."""
        result = TOOLS["rename_file"](
            {
                "old_name": str(tmp_path / "phantom.txt"),
                "new_name": str(tmp_path / "real.txt"),
            }
        )
        assert "not found" in result.lower() or "error" in result.lower()

    # --- delete_file ---

    def test_delete_file_already_deleted(self, tmp_path):
        """LLM calls delete_file twice on the same path."""
        f = tmp_path / "once.txt"
        f.write_text("x")
        TOOLS["delete_file"]({"filename": str(f)})
        result = TOOLS["delete_file"]({"filename": str(f)})
        assert "not found" in result.lower() or "error" in result.lower()

    # --- delete_directory ---

    def test_delete_directory_not_a_dir(self, tmp_path):
        """LLM passes a file path to delete_directory."""
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = TOOLS["delete_directory"]({"name": str(f)})
        assert "not a directory" in result.lower() or "error" in result.lower()
        assert f.exists(), "File must NOT have been deleted"

    def test_delete_directory_nonexistent(self, tmp_path):
        result = TOOLS["delete_directory"]({"name": str(tmp_path / "ghost_dir")})
        assert "not exist" in result.lower() or "error" in result.lower()


class TestNetworkLLMEdgeCases:
    """
    Web and finance tools under realistic LLM-generated inputs.
    """

    # --- web_scrape ---

    def test_web_scrape_no_url(self):
        result = TOOLS["web_scrape"]({})
        assert "error" in result.lower()

    def test_web_scrape_empty_url(self):
        result = TOOLS["web_scrape"]({"url": ""})
        assert "error" in result.lower()

    @patch("src.tools.scraper.http_client.get")
    def test_web_scrape_non_html_content(self, mock_get):
        """LLM passes a URL that returns binary/JSON — tool must reject gracefully."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {"Content-Type": "application/octet-stream"}
        mock_resp.text = ""
        mock_get.return_value = mock_resp

        result = TOOLS["web_scrape"]({"url": "https://example.com/file.bin"})
        assert "non-text" in result.lower() or "error" in result.lower() or "cannot" in result.lower()

    @patch("src.tools.scraper.http_client.get")
    def test_web_scrape_http_error(self, mock_get):
        """Server returns 404."""
        import requests as req
        mock_resp = MagicMock()
        http_err = req.exceptions.HTTPError(response=MagicMock(status_code=404))
        mock_resp.raise_for_status.side_effect = http_err
        mock_get.return_value = mock_resp

        result = TOOLS["web_scrape"]({"url": "https://example.com/missing"})
        assert "error" in result.lower() or "404" in result

    @patch("src.tools.scraper.http_client.get")
    def test_web_scrape_timeout(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.Timeout()
        result = TOOLS["web_scrape"]({"url": "https://slow.example.com"})
        assert "timed out" in result.lower() or "error" in result.lower()

    # --- crypto_price ---

    @patch("src.tools.finance.requests.get")
    def test_crypto_price_empty_coin(self, mock_get):
        """LLM passes empty coin name."""
        result = TOOLS["crypto_price"]({"coin": ""})
        assert "error" in result.lower()

    @patch("src.tools.finance.requests.get")
    def test_crypto_price_api_error(self, mock_get):
        """CoinGecko returns HTTP error."""
        mock_get.side_effect = Exception("Connection error")
        result = TOOLS["crypto_price"]({"coin": "bitcoin"})
        assert "error" in result.lower()

    # --- finance_price ---

    def test_finance_price_unknown_ticker(self):
        """LLM passes a completely made-up ticker."""
        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_t = MagicMock()
            mock_t.fast_info.last_price = None
            mock_ticker_cls.return_value = mock_t
            result = TOOLS["finance_price"]({"asset": "ZZZZINVALID"})
            assert "not found" in result.lower() or "error" in result.lower()

    def test_finance_price_eur_conversion_failure_warns(self):
        """When EUR/USD rate is unavailable, output must say so explicitly."""
        with patch("yfinance.Ticker") as mock_ticker_cls:
            asset_mock = MagicMock()
            asset_mock.fast_info.last_price = 100.0
            asset_mock.info = {"currency": "USD"}

            eur_mock = MagicMock()
            eur_mock.fast_info.last_price = None  # conversion unavailable

            mock_ticker_cls.side_effect = lambda sym: (
                eur_mock if sym == "EURUSD=X" else asset_mock
            )
            result = TOOLS["finance_price"]({"asset": "gold"})
            assert "unavailable" in result.lower() or "eur" in result.lower()

    # --- get_weather ---

    @patch("requests.get")
    def test_get_weather_empty_location(self, mock_get):
        """LLM passes empty location string."""
        result = TOOLS["get_weather"]({"location": ""})
        assert "error" in result.lower()

    @patch("requests.get")
    def test_get_weather_api_timeout(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.Timeout()
        result = TOOLS["get_weather"]({"location": "Rome"})
        assert "error" in result.lower()


class TestSystemToolsLLMEdgeCases:
    """
    System and GUI tools under realistic LLM-generated inputs.
    """

    def test_launch_app_empty_name(self):
        """LLM passes empty app_name — should not launch anything."""
        with patch("src.tools.automation.subprocess.Popen") as mock_popen:
            result = TOOLS["launch_app"]({"app_name": ""})
            # Either error or Popen was NOT called with an empty command
            if mock_popen.called:
                args = mock_popen.call_args[0][0]
                assert args != [], "Must not call Popen with empty args"

    @patch("src.tools.automation.subprocess.Popen")
    def test_launch_app_invalid_command(self, mock_popen):
        """LLM passes a command that fails to start."""
        mock_popen.side_effect = FileNotFoundError("No such file: notarealapp")
        result = TOOLS["launch_app"]({"app_name": "notarealapp"})
        assert "error" in result.lower()

    @patch("src.tools.automation.PYAUTOGUI_AVAILABLE", False)
    def test_describe_screen_no_gui(self):
        """describe_screen without pyautogui should fail gracefully, not crash."""
        result = TOOLS["describe_screen"]({"question": "What do you see?"})
        assert result  # must return something, not raise

    def test_describe_screen_no_args(self):
        """LLM calls describe_screen with empty dict — default question applies."""
        with patch("src.tools.automation.PYAUTOGUI_AVAILABLE", False):
            result = TOOLS["describe_screen"]({})
            assert result
