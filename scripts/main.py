#!/usr/bin/env python3
import sys
import os
import json
import time

# Aggiunge la root del progetto al path per trovare i moduli (src)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import JarvisAgent
from src.tools import TOOLS
from src.voice.voice_manager import speak_tts as speak, init_stt
from src.config import ENABLE_VOICE
from src.utils import extract_json, print_banner
from src.planner.planner import parse_planner_response
from src.world_model.state import WorldState
from src.logging.tracer import setup_tracer, log_step, log_decision

def main():

    print_banner()
    logger = setup_tracer()

    try:
        jarvis = JarvisAgent()
    except Exception as e:
        logger.error(f"ARGOS startup error: {e}")
        print(f"❌ ARGOS startup error: {e}")
        return

    state = WorldState()

    # Inizializza STT se la voce è abilitata
    voice_ok = False
    if ENABLE_VOICE:
        from src.voice.hybrid_input import start_hybrid_listener, stop_hybrid_listener, get_hybrid_input
        voice_ok = start_hybrid_listener()
        if not voice_ok:
            logger.warning("Voice enabled but microphone unavailable, falling back to text input.")

    logger.info(f"\n🤖 Argos ONLINE [Backend: {jarvis.backend}] [Model: {jarvis.model}]")
    if ENABLE_VOICE: speak("Systems online.")

    while True:
        try:
            # 1. User Input (Hybrid or Text)
            if ENABLE_VOICE and voice_ok:
                user_input = get_hybrid_input("\n👤 You (type or say 'Argos...'): ")
            else:
                user_input = input("\n👤 You: ")
                
            if not user_input: continue
            if user_input.lower() in ["exit", "quit", "stop"]:
                logger.info("Session terminated by user.")
                if ENABLE_VOICE and voice_ok:
                    stop_hybrid_listener()
                break

            # Update the WorldState with the current task
            state.reset()
            state.current_task = user_input
            jarvis.add_message("user", user_input)

            # 2. Reasoning Loop
            loop_count = 0
            while True:
                print("⏳ ...", end="\r")
                raw_response = jarvis.think()
                print(" " * 10, end="\r")

                decision = parse_planner_response(raw_response)
                
                log_decision(logger, decision.thought, decision.tool or "done", decision.confidence)

                # If the agent has finished execution (final text is outside JSON block)
                if decision.done:
                    final_text = decision.response or raw_response
                    print(f"🤖 Argos: {final_text}")
                    jarvis.add_message("assistant", raw_response)
                    logger.debug(f"Final response: {final_text[:150]}")
                    if ENABLE_VOICE: speak(str(final_text))
                    break

                tool_name = decision.tool
                tool_input = decision.tool_input

                # Check if the tool exists
                if not tool_name or tool_name not in TOOLS:
                    msg = f"Tool '{tool_name}' unknown."
                    logger.error(msg)
                    print(f"❌ Error: {msg}")
                    break

                # Infinite loop protection
                max_loops = int(os.getenv("MAX_TOOL_LOOPS", "10"))
                loop_count += 1
                if loop_count > max_loops:
                    msg = f"STOP: Too many automatic actions (limit: {max_loops})."
                    logger.warning(msg)
                    print(f"\n🛑 {msg}")
                    jarvis.add_message("system", f"{msg} Request user input.")
                    break

                print(f"⚙️  TOOL DETECTED: {tool_name}")

                # --- 🔒 SECURITY GATE 🔒 ---
                dangerous_tools = [
                    "create_file", "modify_file", "rename_file", "create_directory",
                    "delete_directory", "delete_file", "read_file", "visual_click", 
                    "keyboard_type", "launch_app"
                ]

                execute = True

                if tool_name in dangerous_tools:
                    print(f"\n{'='*40}")
                    print(f"⚠️  SECURITY AUTHORIZATION REQUIRED")
                    print(f"   Action: {tool_name.upper()}")
                    print(f"   Data:   {tool_input}")
                    print(f"{'='*40}")
                    logger.warning(f"Security Gate: confirmation requested for '{tool_name}' | input={tool_input}")

                    choice = input("👉 Authorize execution? (y/N): ").lower().strip()
                    if choice != 'y':
                        print("🚫 ACTION DENIED BY USER.")
                        logger.info(f"Action '{tool_name}' denied by user.")
                        execute = False
                        state.record_action(tool_name, tool_input, "Denied by user.", False)
                        
                        # Inject into the reasoning loop that the user blocked the command
                        jarvis.add_message("assistant", json.dumps({"action": {"tool": tool_name, "input": tool_input}}))
                        jarvis.add_message("user", "ACTION DENIED BY USER. STOP.")
                        break

                # Actual execution
                if execute:
                    try:
                        result = TOOLS[tool_name](tool_input)
                        success = not str(result).startswith(("Error", "Errore"))
                    except Exception as e:
                        result = f"Python Tool Error: {e}"
                        success = False

                    state.record_action(tool_name, tool_input, str(result), success)
                    log_step(logger, state, tool_name, str(result), success)

                    logger.debug(f"Tool output: {result}")

                    # Feedback to the agent's brain
                    jarvis.add_message("assistant", json.dumps({"action": {"tool": tool_name, "input": tool_input}}))
                    jarvis.add_message("user", f"TOOL RESULT: {result}")

        except KeyboardInterrupt:
            logger.info("Forced exit (Ctrl+C).")
            print("\n👋 Forced exit.")
            break
        except Exception as e:
            logger.error(f"Main Loop Error: {e}")
            print(f"❌ Main Loop Error: {e}")

if __name__ == "__main__":
    main()