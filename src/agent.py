"""
ARGOS Core Agent — LLM-driven cognitive loop with multi-backend support (Groq / Ollama).

This module encapsulates the agent's system prompt, conversational memory management,
and provider-specific API integration logic with automatic key rotation for rate-limit resilience.
"""

import json
import time
import requests
import platform
import os
from .config import (LLM_BACKEND, OLLAMA_URL, MODEL_GROQ, MODEL_OLLAMA, 
                     GROQ_API_KEY, GROQ_CHAT_URL, HISTORY_LIMIT)
from src.planner.planner import build_system_prompt_suffix


class JarvisAgent:
    """Primary autonomous agent class. Manages the system prompt, conversation
    history, and LLM backend dispatch for both Groq Cloud and local Ollama inference."""

    def __init__(self):
        self.history = []
        self.backend = LLM_BACKEND
        self.model = MODEL_GROQ if self.backend == "groq" else MODEL_OLLAMA
        self.history_limit = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))

        # --- System Context Detection ---
        user = os.environ.get("USER", "user")
        os_system = platform.system()
        home_dir = os.path.expanduser("~")
        
        # Core System Prompt — Constrains the agent's reasoning and output format
        self.system_prompt = """
        You are ARGOS, an intelligent and precise virtual assistant.
        PRIMARY LANGUAGE: English. Always respond in English by default, UNLESS the user speaks to you in another language.

        - Operating System: {os_system}
        - Current User: {user}
        - Home Directory: {home_dir}
        - When creating files on the desktop, use ONLY the correct path for the host OS (e.g., /home/{user}/Desktop on Linux).
        - NEVER use Windows-style paths (C:/...) when running on Linux.
        
        RESPONSE STYLE:
        1. Be EXTREMELY concise and natural. No robotic phrasing.
        2. After performing an action (e.g., a click), respond only with "Done." or similar. Do NOT repeat verbose mechanical descriptions like "A left click was executed on...".
        3. Present information conversationally, as a real person would. If asked for news, summarize briefly without formal bullet lists.
        4. Never append "How can I help you further?" at the end. Stop after your response.
        5. Execute ONLY the requested action.
        6. NEVER split write actions: if you need to type text and press Enter, do it in a SINGLE tool call using "press_enter": true.
        7. If a visual action fails, ask the user to reposition the window or retry.

        FUNDAMENTAL RULES:
        1. Execute ONLY EXACTLY what the user requests. If the user says "Click on X", click on X and STOP. Do NOT read the file, do NOT open it, do NOT perform any action not explicitly requested.
        2. Do NOT invent follow-up actions. Your task ends as soon as the tool finishes.
        3. 🛑 MANDATORY: You may invoke ONLY A SINGLE "tool" PER TURN. Generating multiple actions in the same response is STRICTLY FORBIDDEN.
        4. After generating ONE JSON action, stop and wait for the result before proceeding.
        
        AVAILABLE TOOLS (the names below must be used in "action" -> "tool" and "input"):
        --- VISION ---
        - describe_screen: {{"question": "..."}}
        - visual_click: {{"description": "element description", "click_type": "left/right/double"}}
        
        --- SYSTEM ---
        - launch_app: {{"app_name": "firefox"}}
        - system_stats
        - keyboard_type: {{"text": "text to type", "at_element": "visual description", "press_enter": true}}
        
        --- FILE SYSTEM ---
        - list_files: {{"path": "."}}
        - read_file: {{"filename": "..."}}
        - create_file: {{"filename": "...", "content": "..."}}
        - modify_file: {{"filename": "...", "content": "...", "mode": "write/append"}}
        - rename_file: {{"old_name": "...", "new_name": "..."}}
        - delete_file: {{"filename": "..."}}
        - create_directory: {{"name": "directory_name"}}
        - delete_directory: {{"name": "directory_name"}}
        
        --- WEB & FINANCE ---
        - web_search: {{"query": "search query"}}
        - crypto_price: {{"coin": "bitcoin"}}
        - finance_price: {{"asset": "gold"}}
        """.format(os_system=os_system, user=user, home_dir=home_dir)
        
        self.system_prompt += "\n" + build_system_prompt_suffix()
        self._init_history()

    def _init_history(self):
        """Resets the conversation history to the initial system prompt."""
        self.history = [{"role": "system", "content": self.system_prompt}]

    def add_message(self, role, content):
        """Appends a new message to the memory buffer."""
        self.history.append({"role": role, "content": str(content)})

    def trim_history(self):
        """Maintains the conversation history within the configured limit to prevent context overflow."""
        if len(self.history) > self.history_limit + 1:
            # Keep the system prompt (index 0) and the most recent N messages
            system_prompt = self.history[0]
            recent_context = self.history[-(self.history_limit):]
            self.history = [system_prompt] + recent_context

    def think(self):
        """Executes one step of the agent's reasoning loop."""
        self.trim_history()
        try:
            if self.backend == "groq":
                return self._call_groq()
            else:
                return self._call_ollama()
        except Exception as e:
            return f"LLM Error: {e}"

    def _call_groq(self, retries=0):
        """Executes a Groq Cloud API call with automatic key rotation on rate limits."""
        from .config import GROQ_API_KEY, GROQ_API_KEY2
        
        # Alternate between primary and secondary API keys to mitigate rate limits
        current_key = GROQ_API_KEY2 if (retries % 2 != 0 and GROQ_API_KEY2) else GROQ_API_KEY
        
        headers = {
            "Authorization": f"Bearer {current_key}", 
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model, 
            "messages": self.history, 
            "temperature": 0.0  # Zero temperature = deterministic output, minimal hallucination
        }
        
        try:
            response = requests.post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 429:
                if retries < 3:
                    # If a secondary key is available, rotate instantly without delay
                    if retries % 2 == 0 and GROQ_API_KEY2:
                        print("⏳ Rate Limit (Key 1). Rotating instantly to Key 2...")
                        return self._call_groq(retries + 1)
                    else:
                        wait_time = 5 * (retries + 1)
                        print(f"⏳ Global Rate Limit reached. Waiting {wait_time}s...")
                        time.sleep(wait_time)
                        return self._call_groq(retries + 1)
                else:
                    return "Error: Groq Rate Limit exceeded."

            if response.status_code != 200:
                print(f"❌ GROQ ERROR: {response.text}")
                return "API Error."
                
            return response.json()["choices"][0]["message"]["content"]
            
        except Exception as e:
            return f"Connection Error: {e}"

    def _call_ollama(self):
        """Executes a local Ollama inference call."""
        payload = {"model": self.model, "messages": self.history, "stream": False}
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=60)
            return r.json()["message"]["content"]
        except Exception as e:
            return f"Ollama Error: {e}"