import json
import time
import requests
import platform
import os
from .config import (LLM_BACKEND, OLLAMA_URL, MODEL_GROQ, MODEL_OLLAMA, 
                     GROQ_API_KEY, GROQ_CHAT_URL, HISTORY_LIMIT)

class JarvisAgent:
    def __init__(self):
        self.history = []
        self.backend = LLM_BACKEND
        self.model = MODEL_GROQ if self.backend == "groq" else MODEL_OLLAMA

        # --- RILEVAMENTO CONTESTO SISTEMA ---
        user = os.environ.get("USER", "Utente")
        os_system = platform.system()
        home_dir = os.path.expanduser("~")
        
        # PROMPT "GUINZAGLIO CORTO"
        self.system_prompt = """
        sei ARGOS, un assistente virtuale colto e raffinato. Rispondi in Italiano.

        - Sei su: {os_system}
        - Utente: {user}
        - Home Directory: {home_dir}
        - Quando crei file sul desktop, usa SOLO il percorso relativo o quello corretto per Linux (es. /home/{user}/Scrivania).
        - NON usare MAI percorsi Windows (C:/...) se sei su Linux.
        
        STILE DI RISPOSTA:
        1. Non limitarti a riassumere i risultati del web o a elencare i siti.
        2. Elabora le informazioni e rispondi in modo discorsivo, come una persona reale.
        3. Se ti viene chiesto il meteo, non dire "il sito X dice...", ma di' "A Roma oggi il cielo è..."
        4. Evita elenchi puntati di siti web a meno che l'utente non ti chieda esplicitamente le fonti.
        5. Sii conciso ma esaustivo.
        6. Esegui SOLO l'azione richiesta.
        7. NON spezzare mai le azioni di scrittura: se devi scrivere e premere invio, fallo in UN SOLO tool.
        8. Usa "press_enter": true nel JSON invece di chiamare il tool due volte.
        9. Se un'azione visiva fallisce, NON inventare codici tastiera strani. 
        10. Chiedi all'utente di spostare la finestra o riprovare.
        
        REGOLE FONDAMENTALI:
        1. Esegui SOLO l'azione richiesta dall'utente.
        2. NON inventare azioni successive.
        3. Se usi 'visual_click' o 'launch_app', considera il task completato.
        
        FORMATO RISPOSTA:
        - Se devi agire: SOLO JSON.
        - Se hai finito o devi spiegare: TESTO normale.
        
        TOOLS DISPONIBILI:
        --- VISIONE ---
        - describe_screen: {"tool": "describe_screen", "input": {"question": "..."}}
        - visual_click: {"tool": "visual_click", "input": {"description": "descrizione elemento", "click_type": "left/right/double"}}
        
        --- SISTEMA ---
        - launch_app: {"tool": "launch_app", "input": {"app_name": "firefox"}}
        - system_stats
        - keyboard_type: {{"tool": "keyboard_type", "input": {{"text": "testo da scrivere", "at_element": "descrizione visiva (es. barra di ricerca in alto, campo username, ecc.)", "press_enter": true}}}}
        
        --- FILE SYSTEM ---
        - list_files: {"tool": "list_files", "input": {"path": "."}}
        - read_file:  {"tool": "read_file", "input": {"filename": "..."}}
        - create_file:{"tool": "create_file", "input": {"filename": "...", "content": "..."}}
        - modify_file:{"tool": "modify_file", "input": {"filename": "...", "content": "...", "mode": "write/append"}}
        - rename_file:{"tool": "rename_file", "input": {"old_name": "...", "new_name": "..."}} 
        - delete_file:{"tool": "delete_file", "input": {"filename": "..."}}
        - create_directory: {"tool": "create_directory", "input": {"name": "nome_cartella"}}
        - delete_directory: {"tool": "delete_directory", "input": {"name": "nome_cartella"}}
        
        --- WEB ---
        - web_search
        - crypto_price: {"tool": "crypto_price", "input": {"coin": "bitcoin"}}
        """
        self._init_history()

    def _init_history(self):
        self.history = [{"role": "system", "content": self.system_prompt}]

    def add_message(self, role, content):
        self.history.append({"role": role, "content": content})
        if len(self.history) > HISTORY_LIMIT + 1:
            self.history = [self.history[0]] + self.history[-HISTORY_LIMIT:]

    def think(self):
        try:
            if self.backend == "groq":
                return self._call_groq()
            else:
                return self._call_ollama()
        except Exception as e:
            return f"Error LLM: {e}"

    def _call_groq(self, retries=0):
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}", 
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model, 
            "messages": self.history, 
            "temperature": 0.0 # Zero creatività = Meno allucinazioni
        }
        
        try:
            response = requests.post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 429:
                if retries < 2:
                    wait_time = 5 * (retries + 1)
                    print(f"⏳ Rate Limit. Attendo {wait_time}s...")
                    time.sleep(wait_time)
                    return self._call_groq(retries + 1)
                else:
                    return "Errore: Rate Limit Groq."

            if response.status_code != 200:
                print(f"❌ GROQ ERROR: {response.text}")
                return "Errore API."
                
            return response.json()["choices"][0]["message"]["content"]
            
        except Exception as e:
            return f"Errore Connessione: {e}"

    def _call_ollama(self):
        payload = {"model": self.model, "messages": self.history, "stream": False}
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=60)
            return r.json()["message"]["content"]
        except Exception as e:
            return f"Errore Ollama: {e}"