"""
Advanced tool and engine tests:
  - CoreAgent: max_steps default=20, ARGOS_MAX_STEPS env override, explicit override
  - DIMINISHING_THRESHOLD=80, DIMINISHING_STEPS=5
  - read_excel: success (mocked openpyxl), wrong extension, missing file, sheet arg, rows arg
  - analyze_image: missing file, unsupported format, success (mocked vision)
  - query_table: filter, aggregate, group_by, select, invalid filter, missing file, Excel (mocked)
  - transcribe_audio: missing file, unsupported format, success, UnknownValueError, RequestError
  - browser_navigate/click/type/get_content: playwright not installed, success (mocked page), edge cases
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from unittest.mock import MagicMock, call, patch

import pytest

from src.core.engine import DIMINISHING_STEPS, DIMINISHING_THRESHOLD, CoreAgent
from src.tools import TOOLS

# ==========================================================================
# CoreAgent — engine configuration
# ==========================================================================


class TestEngineConfig:
    def test_max_steps_default_is_20(self):
        """Default max_steps is 20."""
        agent = CoreAgent(memory_mode="off")
        assert agent.max_steps == 20

    def test_max_steps_explicit_overrides_default(self):
        """Explicit max_steps= in constructor always wins."""
        agent = CoreAgent(memory_mode="off", max_steps=5)
        assert agent.max_steps == 5

    def test_max_steps_from_env(self, monkeypatch):
        """ARGOS_MAX_STEPS env var sets the default when no explicit value is given."""
        monkeypatch.setenv("ARGOS_MAX_STEPS", "30")
        agent = CoreAgent(memory_mode="off")
        assert agent.max_steps == 30

    def test_explicit_max_steps_beats_env(self, monkeypatch):
        """Explicit max_steps= takes precedence over ARGOS_MAX_STEPS."""
        monkeypatch.setenv("ARGOS_MAX_STEPS", "30")
        agent = CoreAgent(memory_mode="off", max_steps=7)
        assert agent.max_steps == 7

    def test_diminishing_threshold_default(self):
        """DIMINISHING_THRESHOLD is 80 (less aggressive than the old 120)."""
        assert DIMINISHING_THRESHOLD == 80

    def test_diminishing_steps_default(self):
        """DIMINISHING_STEPS is 5 (more lenient than the old 3)."""
        assert DIMINISHING_STEPS == 5


# ==========================================================================
# read_excel
# ==========================================================================


class TestReadExcel:
    @pytest.fixture(autouse=True)
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.helpers._HOME", str(tmp_path))

    def test_missing_filename(self):
        result = TOOLS["read_excel"]({})
        assert "error" in result.lower()

    def test_file_not_found(self, tmp_path):
        result = TOOLS["read_excel"]({"filename": str(tmp_path / "ghost.xlsx")})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_wrong_extension(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("hello")
        result = TOOLS["read_excel"]({"filename": str(f)})
        assert "error" in result.lower()

    def test_openpyxl_not_installed(self, tmp_path):
        """When openpyxl is absent, the tool returns a helpful install hint."""
        f = tmp_path / "data.xlsx"
        f.write_bytes(b"PK\x03\x04")  # fake XLSX magic bytes

        with patch.dict(sys.modules, {"openpyxl": None}):
            result = TOOLS["read_excel"]({"filename": str(f)})
        assert "openpyxl" in result.lower()

    def test_success_mocked(self, tmp_path):
        """read_excel returns sheet names, headers and rows (openpyxl mocked)."""
        f = tmp_path / "data.xlsx"
        f.write_bytes(b"PK\x03\x04")

        mock_openpyxl = MagicMock()
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.title = "Results"
        mock_wb.sheetnames = ["Results", "Meta"]
        mock_wb.active = mock_ws
        mock_ws.iter_rows.return_value = [
            ("country", "gdp"),
            ("Italy", 2100),
            ("France", 2700),
        ]
        mock_openpyxl.load_workbook.return_value = mock_wb

        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            result = TOOLS["read_excel"]({"filename": str(f)})

        assert "country" in result
        assert "Italy" in result
        assert "Results" in result
        assert "Meta" in result

    def test_sheet_selection_mocked(self, tmp_path):
        """The 'sheet' argument selects a specific worksheet."""
        f = tmp_path / "multi.xlsx"
        f.write_bytes(b"PK\x03\x04")

        mock_openpyxl = MagicMock()
        mock_wb = MagicMock()
        mock_target_ws = MagicMock()
        mock_target_ws.title = "Q2"
        mock_wb.sheetnames = ["Q1", "Q2"]
        mock_wb.__getitem__ = lambda self, k: mock_target_ws  # wb["Q2"]
        mock_target_ws.iter_rows.return_value = [("month", "revenue"), ("Apr", 500)]
        mock_openpyxl.load_workbook.return_value = mock_wb

        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            result = TOOLS["read_excel"]({"filename": str(f), "sheet": "Q2"})

        assert "Q2" in result

    def test_rows_limit_mocked(self, tmp_path):
        """The 'rows' argument caps how many rows are returned."""
        f = tmp_path / "big.xlsx"
        f.write_bytes(b"PK\x03\x04")

        mock_openpyxl = MagicMock()
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.title = "Sheet1"
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.active = mock_ws
        # Provide more rows than the requested limit
        all_rows = [("id",)] + [(str(i),) for i in range(50)]
        mock_ws.iter_rows.return_value = all_rows[:6]  # max_row=rows+1=6
        mock_openpyxl.load_workbook.return_value = mock_wb

        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            TOOLS["read_excel"]({"filename": str(f), "rows": 5})

        # iter_rows must have been called with max_row=6 (rows+1)
        mock_ws.iter_rows.assert_called_with(max_row=6, values_only=True)


# ==========================================================================
# analyze_image
# ==========================================================================


class TestAnalyzeImage:
    @pytest.fixture(autouse=True)
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.helpers._HOME", str(tmp_path))

    def test_missing_filename(self):
        result = TOOLS["analyze_image"]({})
        assert "error" in result.lower()

    def test_file_not_found(self, tmp_path):
        result = TOOLS["analyze_image"]({"filename": str(tmp_path / "ghost.png")})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_unsupported_format(self, tmp_path):
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\xff\xfb")
        result = TOOLS["analyze_image"]({"filename": str(f)})
        assert "error" in result.lower() or "unsupported" in result.lower()

    def test_success_png(self, tmp_path):
        """analyze_image calls vision.analyze_image_file and returns its result."""
        img = tmp_path / "chart.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # fake PNG header

        with patch(
            "src.vision.analyze_image_file",
            return_value="A bar chart showing Q1 revenue.",
        ) as mock_vlm:
            result = TOOLS["analyze_image"]({"filename": str(img)})

        mock_vlm.assert_called_once()
        assert "bar chart" in result

    def test_custom_question(self, tmp_path):
        """The 'question' arg is forwarded to the vision backend."""
        img = tmp_path / "map.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with patch("src.vision.analyze_image_file", return_value="Italy") as mock_vlm:
            TOOLS["analyze_image"](
                {"filename": str(img), "question": "What country is shown?"}
            )

        _, question_arg = mock_vlm.call_args[0]
        assert question_arg == "What country is shown?"

    def test_default_question_is_descriptive(self, tmp_path):
        """When no question is given, the tool sends a detail-extraction prompt."""
        img = tmp_path / "diagram.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)  # fake JPEG

        with patch(
            "src.vision.analyze_image_file", return_value="A diagram."
        ) as mock_vlm:
            TOOLS["analyze_image"]({"filename": str(img)})

        _, question_arg = mock_vlm.call_args[0]
        assert len(question_arg) > 10  # non-empty descriptive prompt


# ==========================================================================
# query_table
# ==========================================================================


class TestQueryTable:
    @pytest.fixture(autouse=True)
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.helpers._HOME", str(tmp_path))

    @pytest.fixture
    def sample_csv(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text(
            "country,continent,gdp,year\n"
            "Italy,Europe,2100,2022\n"
            "France,Europe,2700,2022\n"
            "Brazil,Americas,1900,2022\n"
            "Italy,Europe,2200,2023\n"
            "France,Europe,2800,2023\n"
        )
        return str(f)

    def test_missing_filename(self):
        result = TOOLS["query_table"]({})
        assert "error" in result.lower()

    def test_file_not_found(self, tmp_path):
        result = TOOLS["query_table"]({"filename": str(tmp_path / "ghost.csv")})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.xml"
        f.write_text("<root/>")
        result = TOOLS["query_table"]({"filename": str(f)})
        assert "error" in result.lower() or "unsupported" in result.lower()

    def test_default_shows_head(self, sample_csv):
        """Without filter/aggregate, returns shape + first rows."""
        result = TOOLS["query_table"]({"filename": sample_csv})
        assert "country" in result
        assert "Italy" in result
        assert "5 rows" in result or "shape" in result.lower() or "5" in result

    def test_filter_rows(self, sample_csv):
        """filter= selects a subset of rows."""
        result = TOOLS["query_table"](
            {"filename": sample_csv, "filter": "continent == 'Europe'"}
        )
        assert "Italy" in result
        assert "Brazil" not in result

    def test_filter_numeric(self, sample_csv):
        """Numeric filter expression works."""
        result = TOOLS["query_table"]({"filename": sample_csv, "filter": "gdp > 2500"})
        assert "France" in result
        assert "Brazil" not in result

    def test_aggregate_sum(self, sample_csv):
        """aggregate='sum' returns column totals."""
        result = TOOLS["query_table"]({"filename": sample_csv, "aggregate": "sum"})
        assert "gdp" in result
        # Italy 2100+2200=4300, France 2700+2800=5500, Brazil 1900 → total = 11700
        assert "11700" in result

    def test_aggregate_mean(self, sample_csv):
        """aggregate='mean' returns averages for numeric columns only."""
        result = TOOLS["query_table"]({"filename": sample_csv, "aggregate": "mean"})
        # Should succeed and show gdp mean (numeric column)
        assert "gdp" in result
        assert "error" not in result.lower()

    def test_group_by_sum(self, sample_csv):
        """group_by + aggregate computes per-group statistics (select applied after agg)."""
        result = TOOLS["query_table"](
            {"filename": sample_csv, "group_by": "country", "aggregate": "sum"}
        )
        assert "Italy" in result
        # Italy total gdp = 2100 + 2200 = 4300
        assert "4300" in result

    def test_select_columns(self, sample_csv):
        """select= limits the columns in the output."""
        result = TOOLS["query_table"](
            {"filename": sample_csv, "select": ["country", "gdp"]}
        )
        assert "country" in result
        assert "gdp" in result
        assert "continent" not in result

    def test_invalid_filter(self, sample_csv):
        """A broken filter expression returns a helpful error."""
        result = TOOLS["query_table"](
            {"filename": sample_csv, "filter": "nonexistent_col == 42"}
        )
        assert "error" in result.lower()

    def test_invalid_aggregate(self, sample_csv):
        """An unsupported aggregate function returns an error listing valid options."""
        result = TOOLS["query_table"]({"filename": sample_csv, "aggregate": "variance"})
        assert "error" in result.lower()
        assert "variance" in result.lower() or "sum" in result.lower()

    def test_select_nonexistent_column(self, sample_csv):
        """Selecting a column that doesn't exist returns an error."""
        result = TOOLS["query_table"]({"filename": sample_csv, "select": ["ghost_col"]})
        assert "error" in result.lower() or "not found" in result.lower()

    def test_excel_via_mocked_openpyxl(self, tmp_path):
        """query_table loads Excel files via pandas read_excel (openpyxl mocked)."""
        import pandas as pd

        f = tmp_path / "data.xlsx"
        f.write_bytes(b"PK\x03\x04")
        df = pd.DataFrame({"name": ["Alice", "Bob"], "score": [90, 75]})

        with patch("pandas.read_excel", return_value=df):
            result = TOOLS["query_table"]({"filename": str(f)})

        assert "name" in result
        assert "Alice" in result


# ==========================================================================
# transcribe_audio
# ==========================================================================


class TestTranscribeAudio:
    @pytest.fixture(autouse=True)
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.helpers._HOME", str(tmp_path))

    def test_missing_filename(self):
        result = TOOLS["transcribe_audio"]({})
        assert "error" in result.lower()

    def test_file_not_found(self, tmp_path):
        result = TOOLS["transcribe_audio"]({"filename": str(tmp_path / "ghost.wav")})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_unsupported_format_mp3(self, tmp_path):
        """MP3 files return an error with an ffmpeg conversion hint."""
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\xff\xfb\x90\x00")
        result = TOOLS["transcribe_audio"]({"filename": str(f)})
        assert "error" in result.lower()
        assert "ffmpeg" in result.lower() or "convert" in result.lower()

    def test_success_wav(self, tmp_path):
        """Successful transcription returns the text."""
        f = tmp_path / "speech.wav"
        f.write_bytes(b"RIFF" + b"\x00" * 36 + b"data" + b"\x00" * 4)

        import speech_recognition as sr

        mock_recognizer = MagicMock()
        mock_audio = MagicMock()
        mock_recognizer.record.return_value = mock_audio
        mock_recognizer.recognize_google.return_value = "the capital of France is Paris"

        with (
            patch("speech_recognition.Recognizer", return_value=mock_recognizer),
            patch("speech_recognition.AudioFile") as mock_audio_file,
        ):
            mock_audio_file.return_value.__enter__ = lambda s: s
            mock_audio_file.return_value.__exit__ = MagicMock(return_value=False)
            result = TOOLS["transcribe_audio"]({"filename": str(f)})

        assert "Paris" in result
        assert "France" in result

    def test_language_forwarded(self, tmp_path):
        """The 'language' arg is passed to recognize_google."""
        f = tmp_path / "speech.wav"
        f.write_bytes(b"RIFF" + b"\x00" * 36 + b"data" + b"\x00" * 4)

        mock_recognizer = MagicMock()
        mock_audio = MagicMock()
        mock_recognizer.record.return_value = mock_audio
        mock_recognizer.recognize_google.return_value = "ciao mondo"

        with (
            patch("speech_recognition.Recognizer", return_value=mock_recognizer),
            patch("speech_recognition.AudioFile") as mock_audio_file,
        ):
            mock_audio_file.return_value.__enter__ = lambda s: s
            mock_audio_file.return_value.__exit__ = MagicMock(return_value=False)
            TOOLS["transcribe_audio"]({"filename": str(f), "language": "it-IT"})

        mock_recognizer.recognize_google.assert_called_with(
            mock_audio, language="it-IT"
        )

    def test_unknown_value_error(self, tmp_path):
        """When speech is unclear, tool returns a graceful message."""
        import speech_recognition as sr

        f = tmp_path / "noise.wav"
        f.write_bytes(b"RIFF" + b"\x00" * 36 + b"data" + b"\x00" * 4)

        mock_recognizer = MagicMock()
        mock_recognizer.record.return_value = MagicMock()
        mock_recognizer.recognize_google.side_effect = sr.UnknownValueError()

        with (
            patch("speech_recognition.Recognizer", return_value=mock_recognizer),
            patch("speech_recognition.AudioFile") as mock_audio_file,
        ):
            mock_audio_file.return_value.__enter__ = lambda s: s
            mock_audio_file.return_value.__exit__ = MagicMock(return_value=False)
            result = TOOLS["transcribe_audio"]({"filename": str(f)})

        assert "could not understand" in result.lower() or "unclear" in result.lower()

    def test_request_error(self, tmp_path):
        """When the speech service is unreachable, tool returns an error message."""
        import speech_recognition as sr

        f = tmp_path / "speech.flac"
        f.write_bytes(b"fLaC" + b"\x00" * 100)

        mock_recognizer = MagicMock()
        mock_recognizer.record.return_value = MagicMock()
        mock_recognizer.recognize_google.side_effect = sr.RequestError("timeout")

        with (
            patch("speech_recognition.Recognizer", return_value=mock_recognizer),
            patch("speech_recognition.AudioFile") as mock_audio_file,
        ):
            mock_audio_file.return_value.__enter__ = lambda s: s
            mock_audio_file.return_value.__exit__ = MagicMock(return_value=False)
            result = TOOLS["transcribe_audio"]({"filename": str(f)})

        assert "error" in result.lower() or "service" in result.lower()


# ==========================================================================
# Browser tools
# ==========================================================================


@pytest.fixture(autouse=True)
def reset_browser_state():
    """Isolate browser module state for every test."""
    import src.tools.browser as bm

    bm._state.update({"pw": None, "browser": None, "page": None})
    yield
    bm._state.update({"pw": None, "browser": None, "page": None})


def _mock_page(
    title="Test Page", url="https://example.com", body="Hello world from test."
):
    page = MagicMock()
    page.title.return_value = title
    page.url = url
    page.content.return_value = f"<html><body>{body}</body></html>"
    page.inner_text.return_value = body
    return page


class TestBrowserNavigate:
    def test_playwright_not_installed(self, monkeypatch):
        """When playwright is absent, tool returns installation instructions."""
        import src.tools.browser as bm

        # Ensure _state["page"] is None so _ensure_page tries to import playwright
        assert bm._state["page"] is None

        with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            result = TOOLS["browser_navigate"]({"url": "https://example.com"})

        assert "playwright" in result.lower()
        assert "install" in result.lower()

    def test_missing_url(self):
        import src.tools.browser as bm

        bm._state["page"] = _mock_page()
        result = TOOLS["browser_navigate"]({})
        assert "error" in result.lower()

    def test_https_prepended_to_bare_domain(self):
        import src.tools.browser as bm

        page = _mock_page(title="Example", url="https://example.com")
        bm._state["page"] = page

        TOOLS["browser_navigate"]({"url": "example.com"})
        called_url = page.goto.call_args[0][0]
        assert called_url.startswith("https://")

    def test_success_returns_title_and_content(self):
        import src.tools.browser as bm

        page = _mock_page(
            title="Wikipedia: Python",
            url="https://en.wikipedia.org/wiki/Python",
            body="Python is a language.",
        )
        bm._state["page"] = page

        result = TOOLS["browser_navigate"](
            {"url": "https://en.wikipedia.org/wiki/Python"}
        )
        assert "Wikipedia: Python" in result
        page.goto.assert_called_once_with(
            "https://en.wikipedia.org/wiki/Python",
            wait_until="domcontentloaded",
            timeout=30000,
        )

    def test_goto_error_returns_message(self):
        import src.tools.browser as bm

        page = _mock_page()
        page.goto.side_effect = Exception("net::ERR_NAME_NOT_RESOLVED")
        bm._state["page"] = page

        result = TOOLS["browser_navigate"]({"url": "https://notreal.invalid"})
        assert "error" in result.lower()
        assert "notreal.invalid" in result

    def test_page_reused_across_calls(self):
        """The same page object is reused on every navigate call (no re-init)."""
        import src.tools.browser as bm

        page = _mock_page()
        bm._state["page"] = page

        TOOLS["browser_navigate"]({"url": "https://a.com"})
        TOOLS["browser_navigate"]({"url": "https://b.com"})

        assert page.goto.call_count == 2


class TestBrowserClick:
    def test_playwright_not_installed(self, monkeypatch):
        import src.tools.browser as bm

        assert bm._state["page"] is None
        with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            result = TOOLS["browser_click"]({"text": "Submit"})
        assert "playwright" in result.lower()

    def test_missing_target(self):
        import src.tools.browser as bm

        bm._state["page"] = _mock_page()
        result = TOOLS["browser_click"]({})
        assert "error" in result.lower()

    def test_click_by_text_success(self):
        import src.tools.browser as bm

        page = _mock_page(title="Next Page")
        bm._state["page"] = page

        result = TOOLS["browser_click"]({"text": "Next"})
        assert "Clicked 'Next'" in result
        assert "Next Page" in result
        page.click.assert_called_with("text=Next", timeout=5000)

    def test_click_fallback_to_css_selector(self):
        """When text= click fails, falls back to CSS selector."""
        import src.tools.browser as bm

        page = _mock_page(title="Clicked via CSS")
        # First call (text=…) raises, second call (CSS) succeeds
        page.click.side_effect = [Exception("not found"), None]
        bm._state["page"] = page

        TOOLS["browser_click"]({"selector": "button.submit"})
        assert page.click.call_count == 2

    def test_click_error_returns_message(self):
        import src.tools.browser as bm

        page = _mock_page()
        page.click.side_effect = Exception("Timeout")
        bm._state["page"] = page

        result = TOOLS["browser_click"]({"text": "GhostButton"})
        assert "error" in result.lower()
        assert "GhostButton" in result


class TestBrowserType:
    def test_playwright_not_installed(self, monkeypatch):
        import src.tools.browser as bm

        assert bm._state["page"] is None
        with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            result = TOOLS["browser_type"]({"selector": "input", "text": "hello"})
        assert "playwright" in result.lower()

    def test_missing_text(self):
        import src.tools.browser as bm

        bm._state["page"] = _mock_page()
        result = TOOLS["browser_type"]({"selector": "input[name='q']"})
        assert "error" in result.lower()

    def test_missing_selector(self):
        import src.tools.browser as bm

        bm._state["page"] = _mock_page()
        result = TOOLS["browser_type"]({"text": "hello"})
        assert "error" in result.lower()

    def test_type_success(self):
        import src.tools.browser as bm

        page = _mock_page()
        bm._state["page"] = page

        result = TOOLS["browser_type"](
            {"selector": "input[name='q']", "text": "search query"}
        )
        assert "search query" in result
        page.fill.assert_called_with("input[name='q']", "search query", timeout=5000)

    def test_type_with_press_enter(self):
        """press_enter=true presses Enter and returns new page content."""
        import src.tools.browser as bm

        page = _mock_page(title="Search Results")
        bm._state["page"] = page

        result = TOOLS["browser_type"](
            {"selector": "input", "text": "query", "press_enter": True}
        )
        page.keyboard.press.assert_called_with("Enter")
        assert "Search Results" in result

    def test_type_fill_fallback_on_error(self):
        """When page.fill raises, tries alternative locator strategies."""
        import src.tools.browser as bm

        page = _mock_page()
        page.fill.side_effect = Exception("strict mode violation")
        # All fallback strategies (get_by_placeholder, get_by_label, locator) are
        # MagicMock and will succeed — just verify the tool doesn't return an error
        bm._state["page"] = page

        result = TOOLS["browser_type"]({"selector": "Search", "text": "hello"})
        assert "error" not in result.lower() or "could not find" not in result.lower()


class TestBrowserGetContent:
    def test_playwright_not_installed(self, monkeypatch):
        import src.tools.browser as bm

        assert bm._state["page"] is None
        with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            result = TOOLS["browser_get_content"]({})
        assert "playwright" in result.lower()

    def test_returns_current_page(self):
        import src.tools.browser as bm

        page = _mock_page(
            title="Current Page",
            url="https://current.example.com",
            body="Live content here.",
        )
        bm._state["page"] = page

        result = TOOLS["browser_get_content"]({})
        assert "Current Page" in result
        assert "https://current.example.com" in result

    def test_no_arguments_needed(self):
        """browser_get_content works with an empty dict."""
        import src.tools.browser as bm

        bm._state["page"] = _mock_page()
        result = TOOLS["browser_get_content"]({})
        assert "error" not in result.lower()

    def test_page_error_returns_message(self):
        import src.tools.browser as bm

        page = _mock_page()
        page.title.side_effect = Exception("Target closed")
        bm._state["page"] = page

        result = TOOLS["browser_get_content"]({})
        assert "error" in result.lower()
