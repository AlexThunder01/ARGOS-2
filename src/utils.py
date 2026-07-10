import contextlib
import json
import os
import platform
import shutil
import sys
import time

from .config import ENABLE_VOICE, LLM_BACKEND


def check_system_deps():
    if ENABLE_VOICE and not shutil.which("mpg123"):
        print("⚠️  WARNING: 'mpg123' not found. Audio playback will be unavailable.")


@contextlib.contextmanager
def no_alsa_err():
    """Silenzia gli errori sys.stderr (incl. JACK/ALSA) reindirizzando a devnull."""
    original_stderr = -1
    devnull = -1
    try:
        original_stderr = os.dup(sys.stderr.fileno())
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stderr.fileno())
        yield
    except Exception:
        # Passiamo l'eccezione all'esterno senza yieldare di nuovo (che causa RuntimeError)
        raise
    finally:
        try:
            if original_stderr != -1:
                os.dup2(original_stderr, sys.stderr.fileno())
                os.close(original_stderr)
            if devnull != -1:
                os.close(devnull)
        except Exception:
            pass


# --- SOPPRESSIONE GLOBALE ALSA C-LEVEL ---

if platform.system() == "Linux":
    try:
        from ctypes import CFUNCTYPE, c_char_p, c_int, cdll

        ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)

        def py_error_handler(filename, line, function, err, fmt):
            pass

        c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
        asound = cdll.LoadLibrary("libasound.so.2")
        asound.snd_lib_error_set_handler(c_error_handler)
    except Exception:
        pass


def extract_json(text):
    text = str(text).strip()
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def normalize_path(path):
    # Usato solo per visualizzazione log, la logica vera è in tools.py
    if not path:
        return ""
    return os.path.basename(str(path).strip().replace("\\", "/"))


def detect_backend():
    """Rileva backend attivo."""
    return LLM_BACKEND


def print_banner():
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    banner = [
        f"{CYAN}{BOLD}                .--------.",
        r"           ____/          \____",
        r"          /     _        _     \ ",
        r"         /   / \ \      / / \   \ ",
        r"        |   |   | |    | |   |   |",
        r"         \   \_/ /      \ \_/   /",
        r"          \____          ____/",
        r"               \________/",
        f"{BLUE}      --- ARGOS PROTOCOL ONLINE ---",
        f"          System Status: ACTIVE{RESET}",
    ]

    for line in banner:
        print(line)
        time.sleep(0.05)  # Effetto caricamento riga per riga
    print("\n")
