"""
ARGOS-2 Core Package — The Unified Cognitive Engine.

Exposes CoreAgent as the single entry point for all reasoning,
regardless of interface (CLI, API, Telegram).
"""

from src.core.engine import CoreAgent

__all__ = ["CoreAgent"]
