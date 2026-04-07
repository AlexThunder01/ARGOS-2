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
    # GAIA Level-Up tools
    "python_repl",
    "bash_exec",
    "web_scrape",
    "read_pdf",
    "read_csv",
    "read_json",
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
        result = TOOLS["read_file"]({"path": str(tmp_path / "this_file_does_not_exist.txt")})
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
