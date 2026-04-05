"""
ARGOS-2 Tools Package — Modular tool registry.

All tools are imported from their focused submodules and re-exported
via the TOOLS dict for backward compatibility.

Usage (unchanged from before):
    from src.tools import TOOLS
"""

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
from .web import get_weather_tool, system_stats_tool, web_search_tool

TOOLS = {
    # --- File System ---
    "list_files": list_files_tool,
    "read_file": read_file_tool,
    "create_file": create_file_tool,
    "modify_file": modify_file_tool,
    "rename_file": rename_file_tool,
    "delete_file": delete_file_tool,
    "create_directory": create_directory_tool,
    "delete_directory": delete_directory_tool,
    # --- Web & Finance ---
    "web_search": web_search_tool,
    "web_scrape": web_scrape_tool,
    "crypto_price": crypto_price_tool,
    "finance_price": finance_price_tool,
    "get_weather": get_weather_tool,
    # --- System & GUI ---
    "system_stats": system_stats_tool,
    "launch_app": launch_app_tool,
    "keyboard_type": keyboard_type_tool,
    "visual_click": visual_click_tool,
    "describe_screen": describe_screen_tool,
    # --- Code Execution ---
    "python_repl": python_repl_tool,
    "bash_exec": bash_exec_tool,
    # --- Document Parsing ---
    "read_pdf": read_pdf_tool,
    "read_csv": read_csv_tool,
    "read_json": read_json_tool,
}

# ──────────────────────────────────────────────────────────────────────
# Dashboard Tool Whitelist — Only safe, read-only or sandboxed tools
# are allowed when the request originates from the web dashboard.
# ──────────────────────────────────────────────────────────────────────
DASHBOARD_TOOLS_WHITELIST: set[str] = {
    # Read-only web/data
    "web_search",
    "web_scrape",
    "crypto_price",
    "finance_price",
    "get_weather",
    # Monitoring
    "system_stats",
    # Document analysis (read-only)
    "read_pdf",
    "read_csv",
    "read_json",
    # Sandboxed execution (Docker isolated)
    "python_repl",
    "bash_exec",
    # File browsing (read-only)
    "list_files",
    "read_file",
}

# ──────────────────────────────────────────────────────────────────────
# Tool Metadata — Used by the dashboard Tools Panel widget
# ──────────────────────────────────────────────────────────────────────
TOOL_METADATA: dict[str, dict] = {
    "list_files": {
        "category": "filesystem",
        "icon": "📂",
        "label": "List Files",
        "risk": "low",
        "description": "Lists files in a directory",
    },
    "read_file": {
        "category": "filesystem",
        "icon": "📄",
        "label": "Read File",
        "risk": "low",
        "description": "Reads text content from a file",
    },
    "create_file": {
        "category": "filesystem",
        "icon": "✏️",
        "label": "Create File",
        "risk": "high",
        "description": "Creates a new file on disk",
    },
    "modify_file": {
        "category": "filesystem",
        "icon": "🔧",
        "label": "Modify File",
        "risk": "high",
        "description": "Overwrites or appends to a file",
    },
    "rename_file": {
        "category": "filesystem",
        "icon": "🏷️",
        "label": "Rename File",
        "risk": "high",
        "description": "Renames a file or directory",
    },
    "delete_file": {
        "category": "filesystem",
        "icon": "🗑️",
        "label": "Delete File",
        "risk": "critical",
        "description": "Deletes a file permanently",
    },
    "create_directory": {
        "category": "filesystem",
        "icon": "📁",
        "label": "Create Directory",
        "risk": "high",
        "description": "Creates a new directory",
    },
    "delete_directory": {
        "category": "filesystem",
        "icon": "💥",
        "label": "Delete Directory",
        "risk": "critical",
        "description": "Recursively deletes a directory",
    },
    "web_search": {
        "category": "web",
        "icon": "🔍",
        "label": "Web Search",
        "risk": "none",
        "description": "DuckDuckGo / Tavily web search",
    },
    "web_scrape": {
        "category": "web",
        "icon": "🌐",
        "label": "Web Scrape",
        "risk": "none",
        "description": "Extracts text from a web page",
    },
    "crypto_price": {
        "category": "finance",
        "icon": "₿",
        "label": "Crypto Price",
        "risk": "none",
        "description": "Real-time crypto prices (CoinGecko)",
    },
    "finance_price": {
        "category": "finance",
        "icon": "📈",
        "label": "Finance Price",
        "risk": "none",
        "description": "Stocks & commodities (Yahoo Finance)",
    },
    "get_weather": {
        "category": "web",
        "icon": "🌤️",
        "label": "Weather",
        "risk": "none",
        "description": "Weather forecast (Open-Meteo)",
    },
    "system_stats": {
        "category": "system",
        "icon": "📊",
        "label": "System Stats",
        "risk": "none",
        "description": "CPU & RAM usage via psutil",
    },
    "launch_app": {
        "category": "system",
        "icon": "🚀",
        "label": "Launch App",
        "risk": "critical",
        "description": "Launches a process on the host",
    },
    "keyboard_type": {
        "category": "gui",
        "icon": "⌨️",
        "label": "Keyboard Type",
        "risk": "critical",
        "description": "Types text via pyautogui + OCR",
    },
    "visual_click": {
        "category": "gui",
        "icon": "🖱️",
        "label": "Visual Click",
        "risk": "critical",
        "description": "Clicks screen elements via vision",
    },
    "describe_screen": {
        "category": "gui",
        "icon": "👁️",
        "label": "Describe Screen",
        "risk": "medium",
        "description": "Describes screen content via VLM",
    },
    "python_repl": {
        "category": "code",
        "icon": "🐍",
        "label": "Python REPL",
        "risk": "medium",
        "description": "Executes Python in Docker sandbox",
    },
    "bash_exec": {
        "category": "code",
        "icon": "🖥️",
        "label": "Bash Exec",
        "risk": "medium",
        "description": "Executes Bash in Docker sandbox",
    },
    "read_pdf": {
        "category": "documents",
        "icon": "📑",
        "label": "Read PDF",
        "risk": "none",
        "description": "Extracts text from PDF files",
    },
    "read_csv": {
        "category": "documents",
        "icon": "📊",
        "label": "Read CSV",
        "risk": "none",
        "description": "Parses and formats CSV data",
    },
    "read_json": {
        "category": "documents",
        "icon": "📋",
        "label": "Read JSON",
        "risk": "none",
        "description": "Pretty-prints JSON files",
    },
}


def get_dashboard_tools() -> dict:
    """Returns only the tools allowed on the web dashboard."""
    return {k: v for k, v in TOOLS.items() if k in DASHBOARD_TOOLS_WHITELIST}
