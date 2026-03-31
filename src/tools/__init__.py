"""
ARGOS-2 Tools Package — Modular tool registry.

All tools are imported from their focused submodules and re-exported
via the TOOLS dict for backward compatibility.

Usage (unchanged from before):
    from src.tools import TOOLS
"""
from .finance import finance_price_tool, crypto_price_tool
from .web import web_search_tool, system_stats_tool, get_weather_tool
from .filesystem import (
    list_files_tool, read_file_tool, create_file_tool,
    modify_file_tool, rename_file_tool, delete_file_tool,
    create_directory_tool, delete_directory_tool
)
from .automation import (
    launch_app_tool, keyboard_type_tool,
    visual_click_tool, describe_screen_tool
)

TOOLS = {
    "finance_price": finance_price_tool,
    "crypto_price": crypto_price_tool,
    "web_search": web_search_tool,
    "system_stats": system_stats_tool,
    "list_files": list_files_tool,
    "read_file": read_file_tool,
    "create_file": create_file_tool,
    "modify_file": modify_file_tool,
    "rename_file": rename_file_tool,
    "delete_file": delete_file_tool,
    "launch_app": launch_app_tool,
    "keyboard_type": keyboard_type_tool,
    "visual_click": visual_click_tool,
    "describe_screen": describe_screen_tool,
    "create_directory": create_directory_tool,
    "delete_directory": delete_directory_tool,
    "get_weather": get_weather_tool
}
