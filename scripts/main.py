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
        print("🚫 ACTION DENIED BY USER.")
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
                print(f"  {status} [{step.tool}] {step.result[:120]}")
        print(f"🤖 Argos: {result.response}")
        return

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

            # Execute through CoreAgent
            print("⏳ ...", end="\r")
            result = agent.run_task(user_input)
            print(" " * 10, end="\r")

            # Display result
            if result.history:
                for step in result.history:
                    status = "✅" if step.success else "❌"
                    print(f"  {status} [{step.tool}] {step.result[:120]}")

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
