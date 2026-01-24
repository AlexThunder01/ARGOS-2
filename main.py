#!/usr/bin/env python3
import sys
import os
import json
import time

# Aggiunge src al path per trovare i moduli
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.agent import JarvisAgent
from src.tools import TOOLS
from src.voice import speak, listen
from src.config import ENABLE_VOICE
from src.utils import extract_json, print_banner

def main():

    print_banner() 

    try:
        jarvis = JarvisAgent()
    except Exception as e:
        print(f"❌ Errore avvio Argos: {e}")
        return

    print(f"\n🤖 Argos ONLINE [Backend: {jarvis.backend}] [Model: {jarvis.model}]")
    if ENABLE_VOICE: speak("Sistemi online.")

    while True:
        try:
            # 1. Input Utente
            user_input = listen() if ENABLE_VOICE else input("\n👤 Tu: ")
            if not user_input: continue
            if user_input.lower() in ["exit", "esci", "stop"]: break

            jarvis.add_message("user", user_input)

            # 2. Loop di Ragionamento
            loop_count = 0 
            while True:
                print("⏳ ...", end="\r")
                response = jarvis.think()
                print(" " * 10, end="\r")

                tool_data = extract_json(response)

                # Se non è un tool o il parsing ha fallito, è una risposta testuale
                if not tool_data:
                    print(f"🤖 Jarvis: {response}")
                    jarvis.add_message("assistant", response)
                    if ENABLE_VOICE: speak(str(response)[:200])
                    break 

                tool_name = tool_data.get("tool")
                tool_input = tool_data.get("input")

                # Controlla se il tool esiste
                if tool_name not in TOOLS:
                    print(f"❌ Errore: Tool '{tool_name}' sconosciuto.")
                    break

                # Protezione loop infiniti
                loop_count += 1
                if loop_count > 4:
                    print("\n🛑 STOP: Troppe azioni automatiche.")
                    jarvis.add_message("system", "STOP: Troppe azioni. Chiedi input.")
                    break

                print(f"⚙️  TOOL RILEVATO: {tool_name}")

                # --- 🔒 SECURITY GATE (BLINDATO) 🔒 ---
                # Lista delle azioni che richiedono conferma manuale
                dangerous_tools = [
                    "create_file", 
                    "modify_file", 
                    "rename_file",  # <--- AGGIUNTO
                    "create_directory",
                    "delete_directory",
                    "delete_file", 
                    "read_file",
                    "visual_click", 
                    "keyboard_type", 
                    "launch_app"
                ]

                execute = True
                
                # Se il tool è nella lista pericolosa, chiedi conferma
                if tool_name in dangerous_tools:
                    print(f"\n{'='*40}")
                    print(f"⚠️  RICHIESTA AUTORIZZAZIONE SICUREZZA")
                    print(f"   Azione: {tool_name.upper()}")
                    print(f"   Dati:   {tool_input}")
                    print(f"{'='*40}")
                    
                    choice = input("👉 Autorizzi l'esecuzione? (s/N): ").lower().strip()
                    if choice != 's':
                        print("🚫 AZIONE NEGATA DALL'UTENTE.")
                        execute = False
                        # Diciamo all'LLM che è stato bloccato
                        jarvis.add_message("assistant", json.dumps(tool_data))
                        jarvis.add_message("user", "AZIONE NEGATA DALL'UTENTE. FERMATI.")
                        break # Esce dal loop interno, torna a "Tu:"

                # Esecuzione effettiva
                if execute:
                    try:
                        result = TOOLS[tool_name](tool_input)
                    except Exception as e:
                        result = f"Errore Python Tool: {e}"
                    
                    print(f"   ✅ OUT: {result}") 

                    # Feedback al cervello dell'agente
                    jarvis.add_message("assistant", json.dumps(tool_data))
                    jarvis.add_message("user", f"RISULTATO TOOL: {result}")
                    
                    time.sleep(0.5)

        except KeyboardInterrupt: 
            print("\n👋 Uscita forzata.")
            break
        except Exception as e: 
            print(f"❌ Errore Main: {e}")

if __name__ == "__main__":
    main()