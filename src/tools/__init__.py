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
