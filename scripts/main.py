#!/usr/bin/env python3
"""
ARGOS-2 CLI — Interactive Terminal Interface.

Provides a rich command-line experience for direct interaction with the
CoreAgent. Supports three memory modes and voice input.

Usage:
    python3 scripts/main.py                  # Stateless (default)
    python3 scripts/main.py --session        # Ephemeral RAM memory
    python3 scripts/main.py --memory         # Persistent DB memory
    python3 scripts/main.py --user-id 42     # Custom user ID
"""

import argparse
import os
import re
import sys

# Project root on sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import ENABLE_VOICE
from src.core import CoreAgent
from src.logging.tracer import setup_tracer
from src.utils import print_banner

# ==========================================================================
# CLI Security Gate — Interactive (y/N) Prompt
# ==========================================================================


def cli_confirmation_callback(tool_name: str, tool_input: dict) -> bool:
    """Prompts the user for authorization before executing a dangerous tool."""
    print(f"\n{'=' * 40}")
    print("⚠️  SECURITY AUTHORIZATION REQUIRED")
    print(f"   Action: {tool_name.upper()}")
    print(f"   Data:   {tool_input}")
    print(f"{'=' * 40}")
    choice = input("👉 Authorize execution? (y/N): ").lower().strip()
    if choice != "y":
        return False
    return True


# ==========================================================================
# Argument Parser
# ==========================================================================


def parse_args():
    parser = argparse.ArgumentParser(
        description="ARGOS-2 CLI — Interactive Terminal Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Memory Modes:
  (default)     Stateless — each command is isolated
  --session     Ephemeral — RAM-only memory for the current session
  --memory      Persistent — full RAG memory saved to database
        """,
    )
    memory_group = parser.add_mutually_exclusive_group()
    memory_group.add_argument(
        "--session",
        action="store_true",
        help="Enable ephemeral session memory (RAM-only, cleared on exit)",
    )
    memory_group.add_argument(
        "--memory",
        action="store_true",
        help="Enable persistent RAG memory (same database as Telegram)",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Override the auto-generated user ID (default: sha256 hash of $USER)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=int(os.getenv("MAX_TOOL_LOOPS", "10")),
        help="Maximum tool execution steps per task (default: 10)",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        default=None,
        help="Optional one-shot prompt (skips interactive loop)",
    )
    return parser.parse_args()


# ==========================================================================
# Main Loop
# ==========================================================================


def _format_step_preview(result: str, max_len: int = 120) -> str:
    """Formats a tool result for single-line terminal display.

    Collapses newlines into spaces and appends '…' if the text was truncated,
    so the preview is always one readable line with no dangling sentence fragments.
    """
    flat = " ".join(result.split())
    if len(flat) <= max_len:
        return flat
    # Truncate at the last word boundary within max_len
    truncated = flat[:max_len].rsplit(" ", 1)[0]
    return truncated + "…"


def main():
    args = parse_args()

    # Determine memory mode
    if args.memory:
        memory_mode = "persistent"
    elif args.session:
        memory_mode = "session"
    else:
        memory_mode = "off"

    print_banner()
    logger = setup_tracer()

    # Initialize CoreAgent
    try:
        agent = CoreAgent(
            memory_mode=memory_mode,
            user_id=args.user_id,
            max_steps=args.max_steps,
            confirmation_callback=cli_confirmation_callback,
        )
    except Exception as e:
        logger.error(f"ARGOS startup error: {e}")
        print(f"❌ ARGOS startup error: {e}")
        return

    # Voice setup (optional)
    voice_ok = False
    if ENABLE_VOICE:
        from src.voice.hybrid_input import (
            get_hybrid_input,
            start_hybrid_listener,
            stop_hybrid_listener,
        )

        voice_ok = start_hybrid_listener()
        if not voice_ok:
            logger.warning(
                "Voice enabled but microphone unavailable, falling back to text input."
            )

    # Status line
    mode_label = {
        "off": "Stateless",
        "session": "Session Memory",
        "persistent": "Persistent Memory",
    }
    logger.info(
        f"\n🤖 Argos ONLINE [Backend: {agent.backend}] [Model: {agent.model}] "
        f"[Memory: {mode_label[memory_mode]}]"
    )
    if memory_mode == "persistent":
        try:
            from src.telegram.db import db_register_user

            db_register_user(agent.user_id, username="cli_user")
        except Exception:
            pass
    if ENABLE_VOICE:
        from src.voice.voice_manager import speak_tts as speak

        speak("Systems online.")

    # One-shot mode: execute prompt and exit
    if args.prompt:
        one_shot = " ".join(args.prompt)
        print("⏳ ...", end="\r")
        result = agent.run_task(one_shot)
        print(" " * 10, end="\r")
        if result.history:
            for step in result.history:
                status = "✅" if step.success else "❌"
                print(f"  {status} [{step.tool}] {_format_step_preview(step.result)}")
        print(f"🤖 Argos: {result.response}")
        return

    # Conversation history — maintained across turns for multi-turn coherence.
    # Injected into each task via _injected_history so the LLM has context
    # from prior exchanges (last 10 messages = 5 turns).
    conversation_history: list[dict] = []

    # Interactive loop
    while True:
        try:
            # User Input
            if ENABLE_VOICE and voice_ok:
                user_input = get_hybrid_input("\n👤 You (type or say 'Argos...'): ")
            else:
                user_input = input("\n👤 You: ")

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "stop"):
                logger.info("Session terminated by user.")
                if ENABLE_VOICE and voice_ok:
                    stop_hybrid_listener()
                break

            # Detect name introduction/correction and update DB profile BEFORE
            # run_task so _build_llm_context immediately reads the correct name.
            #
            # Two pattern groups:
            #  1. Unambiguous introductions: "mi chiamo X", "il mio nome è X", ...
            #  2. Correction context: "no sono X", "adesso sono X", "ora sono X" —
            #     only when X starts with uppercase (blocks "sono stanco", "sono sicuro").
            #
            # NOTE: bare \bsono\b is intentionally excluded from group 1 (too
            # broad — matches "sono nella Scrivania", etc.).
            if memory_mode == "persistent":
                _negation = re.search(
                    r"(?i:non mi chiamo|non sono|don't call me|not my name)",
                    user_input,
                )
                # Group 1 — unambiguous phrases (case-insensitive name)
                _name_m = re.search(
                    r"(?i:\bmi\s+chiamo\b|\bil\s+mio\s+nome\s+è\b|\bchiamami\b"
                    r"|\bmy\s+name\s+is\b|\bI'm\b|\bi\s+am\b)"
                    r"\s+([A-Za-zÀ-Úà-ú]{2,})",
                    user_input,
                )
                # Group 2 — correction context + "sono" + CapitalizedName only
                if not _name_m:
                    _name_m = re.search(
                        r"(?i:\bno[,.\s]+sono\b|\badesso\s+sono\b|\bora\s+sono\b"
                        r"|\bin\s+realtà\s+sono\b|\banzi\s+sono\b)"
                        r"\s+([A-ZÀ-Ú][a-zA-Zà-ú]+)",
                        user_input,
                    )
                if _name_m and not _negation:
                    try:
                        from src.telegram.db import db_update_profile
                        db_update_profile(agent.user_id, display_name=_name_m.group(1).capitalize())
                    except Exception:
                        pass
                elif _negation:
                    try:
                        from src.telegram.db import db_update_profile
                        db_update_profile(agent.user_id, display_name="")
                    except Exception:
                        pass

            # Inject prior conversation so the LLM retains context between tasks
            agent._injected_history = conversation_history[-10:]

            # Execute through CoreAgent
            print("⏳ ...", end="\r")
            result = agent.run_task(user_input)
            print(" " * 10, end="\r")

            # Accumulate history for next turn (kept to last 10 messages)
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": result.response})
            if len(conversation_history) > 10:
                conversation_history = conversation_history[-10:]

            # Display result
            if result.history:
                for step in result.history:
                    if not step.success and step.result in ("Denied by user.", "ACTION DENIED BY USER. STOP."):
                        continue
                    status = "✅" if step.success else "❌"
                    print(f"  {status} [{step.tool}]")

            print(f"🤖 Argos: {result.response}")

            if ENABLE_VOICE:
                speak(str(result.response))

        except KeyboardInterrupt:
            logger.info("Forced exit (Ctrl+C).")
            print("\n👋 Forced exit.")
            break
        except Exception as e:
            logger.error(f"Main Loop Error: {e}")
            print(f"❌ Main Loop Error: {e}")


if __name__ == "__main__":
    main()
