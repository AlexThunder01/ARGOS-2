import json
import re
import os
import sys
import shutil
import contextlib
import requests
import time
from .config import ENABLE_VOICE, LLM_BACKEND, OLLAMA_URL, GROQ_API_KEY


def check_system_deps():
    if ENABLE_VOICE and not shutil.which("mpg123"):
        print("⚠️  ATTENZIONE: 'mpg123' non trovato. L'audio non funzionerà.")

@contextlib.contextmanager
def no_alsa_err():
    """Silenzia gli errori ALSA su Linux."""
    try:
        original_stderr = os.dup(sys.stderr.fileno())
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stderr.fileno())
        yield
    except Exception:
        yield
    finally:
        try:
            os.dup2(original_stderr, sys.stderr.fileno())
            os.close(devnull)
            os.close(original_stderr)
        except: pass

def extract_json(text):
    text = str(text).strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match: return None
    try: return json.loads(match.group(0))
    except: return None

def normalize_path(path):
    # Usato solo per visualizzazione log, la logica vera è in tools.py
    if not path: return ""
    return os.path.basename(str(path).strip().replace("\\", "/"))

def detect_backend():
    """Rileva backend attivo."""
    if LLM_BACKEND in ("ollama", "groq"): return LLM_BACKEND
    if GROQ_API_KEY: return "groq"
    try:
        if requests.get(OLLAMA_URL, timeout=0.5).ok: return "ollama"
    except: pass
    return "ollama"

def print_banner():
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    banner = [
        f"{CYAN}{BOLD}                .--------.",
        "           ____/          \____",
        "          /     _        _     \\",
        "         /   / \ \      / / \   \\",
        "        |   |   | |    | |   |   |",
        "         \   \_/ /      \ \_/   /",
        "          \____          ____/",
        "               \________/",
        f"{BLUE}      --- JARVIS PROTOCOL ONLINE ---",
        f"          System Status: ACTIVE{RESET}"
    ]

    for line in banner:
        print(line)
        time.sleep(0.05) # Effetto caricamento riga per riga
    print("\n")