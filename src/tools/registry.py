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
from .code_exec import bash_exec_tool, python_repl_tool
from .documents import read_csv_tool, read_json_tool, read_pdf_tool
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
    mode: str = Field(default="write", description="'write' to overwrite, 'append' to add")


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
    click_type: str = Field(
        default="left", description="'left', 'right', or 'double'"
    )


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
        ),
        # ── Code ────────────────────────────────────────────────────────────
        ToolSpec(
            name="python_repl",
            description="Executes Python in Docker sandbox",
            input_schema=PythonReplInput,
            executor=python_repl_tool,
            risk="medium",
            category="code",
            icon="🐍",
            label="Python REPL",
            dashboard_allowed=True,
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
        ),
    ]
)
