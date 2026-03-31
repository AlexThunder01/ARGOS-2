"""
ARGOS Core Agent — LLM-driven cognitive loop with model-agnostic multi-backend support.

This module encapsulates the agent's system prompt, conversational memory management,
and provider-specific API integration logic with automatic key rotation for rate-limit resilience.
"""

import json
import time
import requests
import platform
import os
from .config import LLM_BACKEND, LLM_MODEL, HISTORY_LIMIT
from src.planner.planner import build_system_prompt_suffix


class JarvisAgent:
    """Primary autonomous agent class. Manages the system prompt, conversation
    history, and LLM backend dispatch for OpenAI-compatible and Anthropic providers."""

    def __init__(self):
        self.history = []
        self.backend = LLM_BACKEND
        self.model = LLM_MODEL
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
            if self.backend == "anthropic":
                return self._call_anthropic(self.history, temperature=0.0)
            else:
                return self._call_openai_compatible(self.history, temperature=0.0)
        except Exception as e:
            return f"LLM Error: {e}"

    def _call_openai_compatible(self, messages: list[dict], temperature: float = 0.0, retries: int = 0, model_override: str = None) -> str:
        """Executes an OpenAI-compatible API call with optional dual-key rotation on rate limits."""
        from .config import LLM_BASE_URL, LLM_API_KEY, LLM_API_KEY_2
        
        current_key = LLM_API_KEY_2 if (retries % 2 != 0 and LLM_API_KEY_2) else LLM_API_KEY
        headers = {
            "Content-Type": "application/json"
        }
        if current_key:
            headers["Authorization"] = f"Bearer {current_key}"
            
        payload = {
            "model": model_override or self.model, 
            "messages": messages, 
            "temperature": temperature
        }
        
        try:
            url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            
            if response.status_code == 429:
                if retries < 3:
                    if retries % 2 == 0 and LLM_API_KEY_2:
                        print("⏳ Rate Limit (Key 1). Rotating instantly to Key 2...")
                        return self._call_openai_compatible(messages, temperature, retries + 1, model_override)
                    else:
                        wait_time = 5 * (retries + 1)
                        print(f"⏳ Rate Limit reached. Waiting {wait_time}s...")
                        time.sleep(wait_time)
                        return self._call_openai_compatible(messages, temperature, retries + 1, model_override)
                else:
                    return "Error: Rate Limit exceeded."

            if response.status_code != 200:
                print(f"❌ LLM ERROR: {response.text}")
                return "API Error."
                
            return response.json()["choices"][0]["message"]["content"]
            
        except Exception as e:
            return f"Connection Error: {e}"

    def _call_anthropic(self, messages: list[dict], temperature: float = 0.0, model_override: str = None) -> str:
        """Executes an Anthropic API call."""
        from .config import LLM_API_KEY
        
        # Anthropic doesn't support system messages in the same way (it goes top-level)
        system_msg = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg += m["content"] + "\n"
            else:
                user_msgs.append(m)
                
        headers = {
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        payload = {
            "model": model_override or self.model,
            "system": system_msg.strip(),
            "messages": user_msgs,
            "max_tokens": 1024,
            "temperature": temperature
        }
        
        try:
            response = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=60)
            if response.status_code != 200:
                print(f"❌ ANTHROPIC ERROR: {response.text}")
                return "API Error."
            return response.json()["content"][0]["text"]
        except Exception as e:
            return f"Connection Error: {e}"

    # --- External History Methods (Telegram Chat Module) ---

    def think_with_messages(self, messages: list[dict]) -> str:
        """Executes a single LLM inference with an externally-provided message history.
        Used by the Telegram chat module where each user has their own context."""
        try:
            if self.backend == "anthropic":
                return self._call_anthropic(messages, temperature=0.3)
            else:
                return self._call_openai_compatible(messages, temperature=0.3)
        except Exception as e:
            return f"LLM Error: {e}"

    def call_lightweight(self, prompt: str) -> str:
        """Calls a lightweight model for structured extraction tasks (memory extraction)."""
        from .config import LLM_LIGHTWEIGHT_MODEL
        try:
            if self.backend == "anthropic":
                return self._call_anthropic([{"role": "user", "content": prompt}], temperature=0.0, model_override=LLM_LIGHTWEIGHT_MODEL)
            else:
                return self._call_openai_compatible([{"role": "user", "content": prompt}], temperature=0.0, model_override=LLM_LIGHTWEIGHT_MODEL)
        except Exception:
            return ""