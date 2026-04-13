"""
ARGOS-2 Tool Registry — Unica definizione di tutti i ToolSpec.

Questo modulo è l'unica sorgente di verità per: executor, schema input Pydantic,
metadati dashboard (icon, label, risk, category) e testo del system prompt.
Sostituisce TOOLS dict, TOOL_METADATA dict, _TOOL_INPUT_EXAMPLES e il blocco
AVAILABLE TOOLS hardcoded in agent.py.
"""

from typing import Optional

from pydantic import Field

from .automation import (
    describe_screen_tool,
    keyboard_type_tool,
    launch_app_tool,
    visual_click_tool,
)
from .browser import (
    browser_click_tool,
    browser_get_content_tool,
    browser_navigate_tool,
    browser_type_tool,
)
from .code_exec import bash_exec_tool, python_repl_tool
from .documents import (
    analyze_image_tool,
    query_table_tool,
    read_csv_tool,
    read_excel_tool,
    read_json_tool,
    read_pdf_tool,
    transcribe_audio_tool,
)
from .downloader import download_file_tool
from .filesystem import (
    create_directory_tool,
    create_file_tool,
    delete_directory_tool,
    delete_file_tool,
    list_files_tool,
    modify_file_tool,
    read_file_tool,
    rename_file_tool,
)
from .finance import crypto_price_tool, finance_price_tool
from .scraper import web_scrape_tool
from .spec import ToolInput, ToolRegistry, ToolSpec
from .web import get_weather_tool, system_stats_tool, web_search_tool

# ─── Input Schemas ────────────────────────────────────────────────────────────


class ListFilesInput(ToolInput):
    path: str = Field(default=".", description="Directory path to list")


class ReadFileInput(ToolInput):
    filename: str = Field(description="Path or name of the file to read")


class CreateFileInput(ToolInput):
    filename: str = Field(description="Path or name of the file to create")
    content: str = Field(default="", description="Text content to write")


class ModifyFileInput(ToolInput):
    filename: str = Field(description="Path or name of the file to modify")
    content: str = Field(default="", description="Content to write or append")
    mode: str = Field(
        default="write", description="'write' to overwrite, 'append' to add"
    )


class RenameFileInput(ToolInput):
    old_name: str = Field(description="Current filename or path")
    new_name: str = Field(description="New filename or path")


class DeleteFileInput(ToolInput):
    filename: str = Field(description="Path or name of the file to delete")


class CreateDirectoryInput(ToolInput):
    name: str = Field(description="Directory name or path to create")


class DeleteDirectoryInput(ToolInput):
    name: str = Field(description="Directory name or path to delete")


class WebSearchInput(ToolInput):
    query: str = Field(description="Search query string")


class WebScrapeInput(ToolInput):
    url: str = Field(description="Full URL of the page to scrape")


class DownloadFileInput(ToolInput):
    url: str = Field(
        description="URL of the file to download",
        examples=["https://arxiv.org/pdf/2311.12983"],
    )
    save_path: Optional[str] = Field(
        default=None,
        description="Local path to save the file (default: Desktop with auto-detected name)",
    )


class CryptoPriceInput(ToolInput):
    coin: str = Field(
        description="Coin name",
        examples=["bitcoin"],
    )


class FinancePriceInput(ToolInput):
    asset: str = Field(
        description="Asset ticker or name",
        examples=["gold"],
    )


class GetWeatherInput(ToolInput):
    location: str = Field(
        description="City name or location",
        examples=["Rome"],
    )


class NoInput(ToolInput):
    pass


class LaunchAppInput(ToolInput):
    app_name: str = Field(
        description="Application name or command to launch",
        examples=["firefox"],
    )


class KeyboardTypeInput(ToolInput):
    text: str = Field(description="Text to type")
    at_element: Optional[str] = Field(
        default=None, description="Visual description of the target element"
    )
    press_enter: bool = Field(default=False, description="Press Enter after typing")


class VisualClickInput(ToolInput):
    description: str = Field(description="Visual description of the element to click")
    click_type: str = Field(default="left", description="'left', 'right', or 'double'")


class DescribeScreenInput(ToolInput):
    question: str = Field(
        default="What do you see?", description="Question about the screen"
    )


class PythonReplInput(ToolInput):
    code: str = Field(description="Python code to execute in Docker sandbox")


class BashExecInput(ToolInput):
    command: str = Field(description="Bash command to execute in Docker sandbox")


class ReadPdfInput(ToolInput):
    filename: str = Field(
        description="PDF filename or path",
        examples=["report.pdf"],
    )


class ReadCsvInput(ToolInput):
    filename: str = Field(
        description="CSV filename or path",
        examples=["data.csv"],
    )
    rows: int = Field(default=10, description="Number of rows to read")


class ReadJsonInput(ToolInput):
    filename: str = Field(
        description="JSON filename or path",
        examples=["config.json"],
    )


class ReadExcelInput(ToolInput):
    filename: str = Field(
        description="Excel filename or path (.xlsx/.xls/.xlsm)",
        examples=["data.xlsx"],
    )
    sheet: Optional[str] = Field(
        default=None, description="Sheet name to read (defaults to active sheet)"
    )
    rows: int = Field(default=20, description="Number of rows to read (max 100)")


class AnalyzeImageInput(ToolInput):
    filename: str = Field(
        description="Image file path (PNG, JPEG, GIF, BMP, WEBP, TIFF)",
        examples=["chart.png"],
    )
    question: Optional[str] = Field(
        default=None,
        description="Question to answer about the image (default: describe in detail)",
    )


class BrowserNavigateInput(ToolInput):
    url: str = Field(
        description="Full URL to navigate to",
        examples=["https://en.wikipedia.org/wiki/Python"],
    )


class BrowserClickInput(ToolInput):
    text: Optional[str] = Field(
        default=None, description="Visible text of the element to click"
    )
    selector: Optional[str] = Field(
        default=None, description="CSS selector of the element to click"
    )


class BrowserTypeInput(ToolInput):
    selector: str = Field(
        description="CSS selector, placeholder, or aria-label of the input field"
    )
    text: str = Field(description="Text to type into the field")
    press_enter: bool = Field(default=False, description="Press Enter after typing")


class QueryTableInput(ToolInput):
    filename: str = Field(
        description="CSV or Excel file path",
        examples=["data.csv", "results.xlsx"],
    )
    filter: Optional[str] = Field(
        default=None,
        description='Pandas query string to filter rows, e.g. "year == 2020 and value > 100"',
    )
    select: Optional[list] = Field(
        default=None,
        description='List of columns to select, e.g. ["name", "value"]',
    )
    aggregate: Optional[str] = Field(
        default=None,
        description="Aggregation: sum, mean, count, max, min, median, std",
    )
    group_by: Optional[str] = Field(
        default=None,
        description="Column name to group by before aggregating",
    )
    sheet: Optional[str] = Field(
        default=None,
        description="Sheet name (Excel only)",
    )


class TranscribeAudioInput(ToolInput):
    filename: str = Field(
        description="Audio file path (.wav, .flac, .ogg, .aiff)",
        examples=["recording.wav"],
    )
    language: str = Field(
        default="en-US",
        description="BCP-47 language code, e.g. 'en-US', 'it-IT', 'fr-FR'",
    )


# ─── Registry ─────────────────────────────────────────────────────────────────

REGISTRY = ToolRegistry(
    [
        # ── Filesystem ──────────────────────────────────────────────────────
        ToolSpec(
            name="list_files",
            description="Lists files in a directory",
            input_schema=ListFilesInput,
            executor=list_files_tool,
            risk="low",
            category="filesystem",
            icon="📂",
            label="List Files",
            dashboard_allowed=True,
            group="coding",
        ),
        ToolSpec(
            name="read_file",
            description="Reads text content from a file",
            input_schema=ReadFileInput,
            executor=read_file_tool,
            risk="low",
            category="filesystem",
            icon="📄",
            label="Read File",
            dashboard_allowed=True,
            group="coding",
        ),
        ToolSpec(
            name="create_file",
            description="Creates a new file on disk",
            input_schema=CreateFileInput,
            executor=create_file_tool,
            risk="high",
            category="filesystem",
            icon="✏️",
            label="Create File",
            group="coding",
        ),
        ToolSpec(
            name="modify_file",
            description="Overwrites or appends to a file",
            input_schema=ModifyFileInput,
            executor=modify_file_tool,
            risk="high",
            category="filesystem",
            icon="🔧",
            label="Modify File",
            group="coding",
        ),
        ToolSpec(
            name="rename_file",
            description="Renames a file or directory",
            input_schema=RenameFileInput,
            executor=rename_file_tool,
            risk="high",
            category="filesystem",
            icon="🏷️",
            label="Rename File",
            group="coding",
        ),
        ToolSpec(
            name="delete_file",
            description="Deletes a file permanently",
            input_schema=DeleteFileInput,
            executor=delete_file_tool,
            risk="critical",
            category="filesystem",
            icon="🗑️",
            label="Delete File",
            group="coding",
        ),
        ToolSpec(
            name="create_directory",
            description="Creates a new directory",
            input_schema=CreateDirectoryInput,
            executor=create_directory_tool,
            risk="high",
            category="filesystem",
            icon="📁",
            label="Create Directory",
            group="coding",
        ),
        ToolSpec(
            name="delete_directory",
            description="Recursively deletes a directory",
            input_schema=DeleteDirectoryInput,
            executor=delete_directory_tool,
            risk="critical",
            category="filesystem",
            icon="💥",
            label="Delete Directory",
            group="coding",
        ),
        # ── Web ─────────────────────────────────────────────────────────────
        ToolSpec(
            name="web_search",
            description="DuckDuckGo / Tavily web search",
            input_schema=WebSearchInput,
            executor=web_search_tool,
            risk="none",
            category="web",
            icon="🔍",
            label="Web Search",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="web_scrape",
            description="Extracts text from a web page",
            input_schema=WebScrapeInput,
            executor=web_scrape_tool,
            risk="none",
            category="web",
            icon="🌐",
            label="Web Scrape",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="download_file",
            description="Downloads a file from a URL and saves it to disk (PDF, images, archives, etc.). HTTPS only. Blocked: executables (.exe, .sh, .bat, etc.). Max size: 100 MB.",
            input_schema=DownloadFileInput,
            executor=download_file_tool,
            risk="high",
            category="web",
            icon="⬇️",
            label="Download File",
            group="research",
        ),
        ToolSpec(
            name="get_weather",
            description="Weather forecast (Open-Meteo)",
            input_schema=GetWeatherInput,
            executor=get_weather_tool,
            risk="none",
            category="web",
            icon="🌤️",
            label="Weather",
            dashboard_allowed=True,
            group="research",
        ),
        # ── Finance ─────────────────────────────────────────────────────────
        ToolSpec(
            name="crypto_price",
            description="Real-time crypto prices (CoinGecko)",
            input_schema=CryptoPriceInput,
            executor=crypto_price_tool,
            risk="none",
            category="finance",
            icon="₿",
            label="Crypto Price",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="finance_price",
            description="Stocks & commodities (Yahoo Finance)",
            input_schema=FinancePriceInput,
            executor=finance_price_tool,
            risk="none",
            category="finance",
            icon="📈",
            label="Finance Price",
            dashboard_allowed=True,
            group="research",
        ),
        # ── System ──────────────────────────────────────────────────────────
        ToolSpec(
            name="system_stats",
            description="CPU & RAM usage via psutil",
            input_schema=NoInput,
            executor=system_stats_tool,
            risk="none",
            category="system",
            icon="📊",
            label="System Stats",
            dashboard_allowed=True,
            group="automation",
        ),
        ToolSpec(
            name="launch_app",
            description="Launches a process on the host",
            input_schema=LaunchAppInput,
            executor=launch_app_tool,
            risk="critical",
            category="system",
            icon="🚀",
            label="Launch App",
            group="automation",
        ),
        # ── GUI ─────────────────────────────────────────────────────────────
        ToolSpec(
            name="keyboard_type",
            description="Types text via pyautogui + OCR",
            input_schema=KeyboardTypeInput,
            executor=keyboard_type_tool,
            risk="critical",
            category="gui",
            icon="⌨️",
            label="Keyboard Type",
            group="automation",
        ),
        ToolSpec(
            name="visual_click",
            description="Clicks screen elements via vision",
            input_schema=VisualClickInput,
            executor=visual_click_tool,
            risk="critical",
            category="gui",
            icon="🖱️",
            label="Visual Click",
            group="automation",
        ),
        ToolSpec(
            name="describe_screen",
            description="Describes screen content via VLM",
            input_schema=DescribeScreenInput,
            executor=describe_screen_tool,
            risk="medium",
            category="gui",
            icon="👁️",
            label="Describe Screen",
            group="automation",
        ),
        # ── Code ────────────────────────────────────────────────────────────
        ToolSpec(
            name="python_repl",
            description="Executes Python in Docker sandbox. IMPORTANT: always use print() to output results, e.g. print(result). If no output, variables are auto-printed as fallback.",
            input_schema=PythonReplInput,
            executor=python_repl_tool,
            risk="medium",
            category="code",
            icon="🐍",
            label="Python REPL",
            dashboard_allowed=True,
            group="coding",
        ),
        ToolSpec(
            name="bash_exec",
            description="Executes Bash in Docker sandbox",
            input_schema=BashExecInput,
            executor=bash_exec_tool,
            risk="medium",
            category="code",
            icon="🖥️",
            label="Bash Exec",
            dashboard_allowed=True,
            group="coding",
        ),
        # ── Documents ───────────────────────────────────────────────────────
        ToolSpec(
            name="read_pdf",
            description="Extracts text from PDF files",
            input_schema=ReadPdfInput,
            executor=read_pdf_tool,
            risk="none",
            category="documents",
            icon="📑",
            label="Read PDF",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="read_csv",
            description="Parses and formats CSV data",
            input_schema=ReadCsvInput,
            executor=read_csv_tool,
            risk="none",
            category="documents",
            icon="📊",
            label="Read CSV",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="read_json",
            description="Pretty-prints JSON files",
            input_schema=ReadJsonInput,
            executor=read_json_tool,
            risk="none",
            category="documents",
            icon="📋",
            label="Read JSON",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="read_excel",
            description="Reads Excel files (.xlsx/.xls/.xlsm), supports sheet selection",
            input_schema=ReadExcelInput,
            executor=read_excel_tool,
            risk="none",
            category="documents",
            icon="📗",
            label="Read Excel",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="analyze_image",
            description="Analyzes an image file with the vision model (PNG, JPEG, GIF, BMP, WEBP, TIFF)",
            input_schema=AnalyzeImageInput,
            executor=analyze_image_tool,
            risk="none",
            category="documents",
            icon="🖼️",
            label="Analyze Image",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="query_table",
            description="Runs pandas filter/aggregate on a CSV or Excel file (filter, group_by, aggregate, select)",
            input_schema=QueryTableInput,
            executor=query_table_tool,
            risk="none",
            category="documents",
            icon="🔢",
            label="Query Table",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="transcribe_audio",
            description="Transcribes a WAV/FLAC/OGG/AIFF audio file to text via speech recognition",
            input_schema=TranscribeAudioInput,
            executor=transcribe_audio_tool,
            risk="none",
            category="documents",
            icon="🎤",
            label="Transcribe Audio",
            dashboard_allowed=True,
            group="research",
        ),
        # ── Browser ─────────────────────────────────────────────────────────
        ToolSpec(
            name="browser_navigate",
            description="Opens a URL in a headless browser and returns rendered page content (handles JS-heavy pages)",
            input_schema=BrowserNavigateInput,
            executor=browser_navigate_tool,
            risk="none",
            category="web",
            icon="🌍",
            label="Browser Navigate",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="browser_click",
            description="Clicks an element on the current browser page by visible text or CSS selector",
            input_schema=BrowserClickInput,
            executor=browser_click_tool,
            risk="low",
            category="web",
            icon="🖱️",
            label="Browser Click",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="browser_type",
            description="Types text into a form field on the current browser page; optionally presses Enter",
            input_schema=BrowserTypeInput,
            executor=browser_type_tool,
            risk="low",
            category="web",
            icon="⌨️",
            label="Browser Type",
            dashboard_allowed=True,
            group="research",
        ),
        ToolSpec(
            name="browser_get_content",
            description="Returns the text content of the current browser page (use after browser_click)",
            input_schema=NoInput,
            executor=browser_get_content_tool,
            risk="none",
            category="web",
            icon="📄",
            label="Browser Get Content",
            dashboard_allowed=True,
            group="research",
        ),
    ]
)
