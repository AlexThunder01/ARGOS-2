"""
ARGOS-2 Tools Package — Tutto derivato dal REGISTRY.

TOOLS, TOOL_METADATA e DASHBOARD_TOOLS_WHITELIST sono ora generati automaticamente
da ToolSpec: un'unica sorgente di verità invece di tre dict sincronizzati a mano.
"""

from .registry import REGISTRY
from .spec import ToolInput, ToolRegistry, ToolSpec

# ── Backward-compatibility exports ──────────────────────────────────────────
TOOLS = REGISTRY.as_tools_dict()
TOOL_METADATA = REGISTRY.as_metadata_dict()
DASHBOARD_TOOLS_WHITELIST = REGISTRY.dashboard_whitelist()


def get_dashboard_tools() -> dict:
    """Returns only the tools allowed on the web dashboard."""
    return {k: v for k, v in TOOLS.items() if k in DASHBOARD_TOOLS_WHITELIST}
