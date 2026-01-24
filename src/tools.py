import os
import shutil
import subprocess
import shlex
import requests
import psutil
from . import vision  
import time

# --- OPTIONAL DEPENDENCIES CHECK ---
PYAUTOGUI_AVAILABLE = False
try:
    import pyautogui
    pyautogui.FAILSAFE = True 
    PYAUTOGUI_AVAILABLE = True
except Exception:
    pass

# --- HELPER FUNCTIONS ---

def _get_desktop_path():
    home = os.path.expanduser("~")
    # Prova config XDG
    xdg_config = os.path.join(home, ".config", "user-dirs.dirs")
    if os.path.exists(xdg_config):
        try:
            with open(xdg_config, "r") as f:
                for line in f:
                    if line.startswith("XDG_DESKTOP_DIR"):
                        parts = line.split("=")
                        if len(parts) > 1:
                            path = parts[1].strip().strip('"')
                            path = path.replace("$HOME", home)
                            if os.path.isdir(path): return path
        except: pass
    
    # Fallback comuni
    for c in ["Scrivania", "Desktop", "Escritorio"]:
        path = os.path.join(home, c)
        if os.path.isdir(path): return path
    return home

def _normalize_path(path_str):
    if not path_str: return _get_desktop_path()
    path_str = str(path_str).strip()
    
    # FIX: Se l'LLM impazzisce e manda un path Windows (C:/Users/...) su Linux
    if ":" in path_str and not path_str.startswith("/"):
        # Prende solo il nome del file finale (es. ciao_mondo.py)
        # e lo mette sul desktop corretto
        base_name = os.path.basename(path_str.replace("\\", "/"))
        return os.path.join(_get_desktop_path(), base_name)

    # Espande ~
    if "~" in path_str:
        path_str = os.path.expanduser(path_str)

    # Se è assoluto, ritorna così com'è
    if os.path.isabs(path_str):
        return path_str
        
    # Altrimenti unisce al Desktop
    return os.path.join(_get_desktop_path(), path_str)


def _get_arg(inp, keys, default=None):
    """Estrae un argomento cercando tra varie chiavi possibili."""
    if isinstance(inp, str): return inp
    if isinstance(inp, dict):
        for k in keys:
            if k in inp and inp[k]: return inp[k]
    return default

# --- WEB & INFO TOOLS ---

def crypto_price_tool(coin_id):
    coin_id = _get_arg(coin_id, ["coin", "id", "name"])
    if not coin_id: return "Errore: Specifica una moneta."
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id.lower()}&vs_currencies=eur"
        r = requests.get(url, timeout=5)
        val = r.json().get(coin_id.lower(), {}).get('eur')
        return f"€{val:,.2f}" if val else "Moneta non trovata."
    except Exception as e: return f"Errore API: {e}"

def web_search_tool(query):
    q = _get_arg(query, ["query", "q", "search"])
    try:
        from ddgs import DDGS
        results = DDGS().text(query=q, max_results=5, region="it-it")
        if not results: return "Nessun risultato trovato."
        
        output = []
        for r in results:
            # Usiamo un formato più pulito senza etichette pesanti
            output.append(f"--- {r['title']} ---\n{r['body']}\n")
        return "\n".join(output)
    except Exception as e:
        return f"Errore Ricerca: {e}"

def system_stats_tool(_):
    return f"CPU: {psutil.cpu_percent()}%, RAM: {psutil.virtual_memory().percent}%"

# --- FILE SYSTEM TOOLS ---

def list_files_tool(inp):
    raw_path = _get_arg(inp, ["path", "directory", "folder"])
    if raw_path in [".", "DESKTOP", None]: target = _get_desktop_path()
    else: target = _normalize_path(raw_path)

    if not os.path.exists(target): return f"Errore: '{target}' non esiste."
    try:
        items = [f for f in os.listdir(target) if not f.startswith('.')]
        items.sort()
        return f"📂 '{os.path.basename(target)}': {', '.join(items[:50])}"
    except Exception as e: return f"Errore: {e}"

def read_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "file"])
    path = _normalize_path(fname)
    if not os.path.exists(path): return "File non trovato."
    if os.path.isdir(path): return "È una cartella, usa list_files."
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f"📄 CONTENUTO:\n{f.read(3000)}"
    except Exception as e: return f"Errore: {e}"

def create_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "name"], "senza_nome.txt")
    if "." not in fname: fname += ".txt"
    path = _normalize_path(fname)
    
    content = inp.get("content", "") if isinstance(inp, dict) else ""

    if os.path.exists(path): return f"⚠️ Il file '{os.path.basename(path)}' esiste già."
    try:
        with open(path, "w", encoding="utf-8") as f: f.write(content)
        return f"✅ Creato: {path}"
    except Exception as e: return f"Errore: {e}"

def create_directory_tool(inp):
    name = _get_arg(inp, ["name", "path", "directory", "dirname"])
    if not name: return "Errore: Specifica il nome della cartella."
    
    path = _normalize_path(name)
    
    if os.path.exists(path):
        return f"⚠️ La cartella o il file '{os.path.basename(path)}' esiste già."
    
    try:
        os.makedirs(path, exist_ok=True)
        return f"✅ Cartella creata: {path}"
    except Exception as e:
        return f"Errore creazione cartella: {e}"
    
def delete_directory_tool(inp):
    name = _get_arg(inp, ["name", "path", "directory", "dirname"])
    if not name: return "Errore: Specifica il nome della cartella da eliminare."
    
    path = _normalize_path(name)
    
    if not os.path.exists(path):
        return f"Errore: La cartella '{path}' non esiste."
    if not os.path.isdir(path):
        return f"Errore: '{path}' non è una cartella (forse è un file)."
    
    try:
        import shutil
        shutil.rmtree(path) # Cancella cartella e tutto il contenuto
        return f"🗑️ Cartella eliminata con successo: {path}"
    except Exception as e:
        return f"Errore eliminazione cartella: {e}"


def modify_file_tool(inp):
    # Questo tool cambia il CONTENUTO
    fname = _get_arg(inp, ["filename", "path", "file"])
    if not fname: return "Errore: Specifica il nome del file da modificare."
    
    path = _normalize_path(fname)
    if not os.path.exists(path): return "Errore: File non trovato."

    content = inp.get("content", "") if isinstance(inp, dict) else ""
    mode = "a" if isinstance(inp, dict) and inp.get("mode") == "append" else "w"

    try:
        with open(path, mode, encoding="utf-8") as f:
            if mode == "a": f.write("\n" + content)
            else: f.write(content)
        return f"✅ Modificato ({mode}): {path}"
    except Exception as e: return f"Errore: {e}"

def rename_file_tool(inp):
    # NUOVO TOOL PER RINOMINARE
    old = _get_arg(inp, ["old_name", "old_path", "filename", "current_name"])
    new = _get_arg(inp, ["new_name", "new_path", "name"])
    
    if not old or not new: return "Errore: Servono 'old_name' e 'new_name'."
    
    p_old = _normalize_path(old)
    p_new = _normalize_path(new)
    
    if not os.path.exists(p_old): return f"Errore: '{old}' non trovato."
    if os.path.exists(p_new): return f"Errore: '{new}' esiste già."
    
    try:
        os.rename(p_old, p_new)
        return f"✅ Rinomina completata: {old} -> {new}"
    except Exception as e: return f"Errore rename: {e}"

def delete_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "file"])
    path = _normalize_path(fname)
    if not os.path.exists(path): return "File non trovato."
    try:
        if os.path.isdir(path): os.rmdir(path)
        else: os.remove(path)
        return f"🗑️ Eliminato: {path}"
    except Exception as e: return f"Errore: {e}"

# --- AUTOMATION TOOLS ---

def launch_app_tool(inp):
    cmd = _get_arg(inp, ["app_name", "command", "cmd"])
    try:
        subprocess.Popen(shlex.split(cmd), stdout=subprocess.DEVNULL, start_new_session=True)
        return f"🚀 Lanciato: {cmd}"
    except Exception as e: return f"Errore: {e}"

def _focus_window(app_name):
    """
    Tenta di portare la finestra in primo piano usando wmctrl su Linux.
    """
    if not app_name: return
    try:
        # wmctrl -a cerca una finestra che contiene 'app_name' nel titolo
        subprocess.run(["wmctrl", "-a", app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5) # Tempo per l'animazione della finestra
    except Exception:
        pass

def keyboard_type_tool(inp):
    if not PYAUTOGUI_AVAILABLE: return "Errore GUI."
    
    text = inp.get("text", "")
    target = _get_arg(inp, ["at_element", "where", "target"])
    press_enter = inp.get("press_enter", False)
    
    # 1. GESTIONE FINESTRA (XORG)
    # Proviamo ad attivare la finestra se menzionata
    common_apps = ["firefox", "chrome", "code", "terminal", "discord", "spotify", "gedit", "files", "nautilus", "settings"]
    if target:
        t_low = target.lower()
        for app in common_apps:
            if app in t_low:
                print(f"🚀 Attivo finestra '{app}'...")
                try:
                    subprocess.run(["xdotool", "search", "--onlyvisible", "--name", app, "windowactivate"], 
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(0.8) # Tempo per redraw
                except: pass
                break

    # 2. VISIONE E CLICK
    if target:
        print(f"👀 Mirino di precisione su: '{target}'")
        coords = vision.analyze_screen_for_coordinates(target)
        
        if coords and "x" in coords:
            x, y = coords['x'], coords['y']
            print(f"🎯 Sposto mouse a ({x}, {y})")
            
            # Movimento umano (non istantaneo)
            pyautogui.moveTo(x, y, duration=0.8, tween=pyautogui.easeInOutQuad)
            
            # Correzione offset (opzionale): A volte gli LLM mirano leggermente in alto
            # Se vedi che clicca sempre sul bordo superiore, decommenta la riga sotto:
            # y += 10 
            
            pyautogui.click()
            time.sleep(0.1)
            pyautogui.click() # Doppio click per selezionare testo/input
            time.sleep(0.5)
        else:
            print("⚠️ Target non trovato. Scrivo nella posizione attuale.")

    # 3. SCRITTURA
    try:
        if text and text.strip():
            print(f"✍️  Scrivo: {text}")
            pyautogui.write(text, interval=0.05)
        
        if press_enter: 
            time.sleep(0.3)
            print("↵ Invio")
            pyautogui.press('enter')
            
        return f"✅ Fatto."
    except Exception as e: return f"Errore: {e}"

def _get_arg(inp, keys, default=None):
    """Estrae un argomento cercando tra varie chiavi possibili."""
    if isinstance(inp, str): return inp
    if isinstance(inp, dict):
        for k in keys:
            if k in inp and inp[k]: return inp[k]
    return default

def _focus_window_xorg(name_fragment):
    """
    Tenta di portare la finestra in primo piano usando xdotool su Xorg.
    """
    if not name_fragment: return False
    try:
        # Cerca finestre visibili che contengono il nome (es. 'settings' o 'firefox')
        subprocess.run(["xdotool", "search", "--onlyvisible", "--name", name_fragment, "windowactivate"], 
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        try:
            # Fallback ricerca per classe (es. 'Gnome-control-center')
            subprocess.run(["xdotool", "search", "--onlyvisible", "--class", name_fragment, "windowactivate"], 
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

def visual_click_tool(inp):
    if not PYAUTOGUI_AVAILABLE: return "Errore: Libreria GUI non disponibile."
    
    description = _get_arg(inp, ["description", "target", "element"])
    click_type = _get_arg(inp, ["click_type", "type"], "left").lower()
    
    if not description: return "Errore: Descrizione target mancante."

    # 1. TENTA IL FOCUS AUTOMATICO
    # Se l'utente dice "Clicca Bluetooth in Impostazioni", cerchiamo di attivare 'settings' o 'impostazioni'
    common_apps = ["settings", "impostazioni", "firefox", "chrome", "terminal", "code"]
    desc_lower = description.lower()
    for app in common_apps:
        if app in desc_lower:
            print(f"🚀 Rilevato contesto '{app}': Attivo finestra...")
            _focus_window_xorg(app)
            time.sleep(1.0) # Attesa per l'animazione di Linux
            break

    # 2. VISIONE E MIRA (GRID SYSTEM)
    print(f"👀 Analisi visiva per click: '{description}'")
    coords = vision.analyze_screen_for_coordinates(description)

    if coords and "x" in coords:
        x, y = coords['x'], coords['y']
        print(f"🎯 Coordinate target: ({x}, {y})")

        # 3. AZIONE FISICA
        pyautogui.moveTo(x, y, duration=0.8, tween=pyautogui.easeInOutQuad)
        
        if "right" in click_type or "destr" in click_type:
            pyautogui.click(button='right')
            res = "Click Destro"
        elif "double" in click_type or "doppio" in click_type:
            pyautogui.doubleClick()
            res = "Doppio Click"
        else:
            pyautogui.click()
            res = "Click Sinistro"

        return f"✅ {res} eseguito su '{description}'."
    
    return f"⚠️ Impossibile trovare visivamente: '{description}'"

def describe_screen_tool(inp):
    q = _get_arg(inp, ["question"], "Cosa vedi?")
    return vision.describe_screen_content(q)

TOOLS = {
    "crypto_price": crypto_price_tool,
    "web_search": web_search_tool,
    "system_stats": system_stats_tool,
    "list_files": list_files_tool,
    "read_file": read_file_tool,
    "create_file": create_file_tool,
    "modify_file": modify_file_tool,
    "rename_file": rename_file_tool, # NUOVO
    "delete_file": delete_file_tool,
    "launch_app": launch_app_tool,
    "keyboard_type": keyboard_type_tool,
    "visual_click": visual_click_tool,
    "describe_screen": describe_screen_tool,
    "create_directory": create_directory_tool,
    "delete_directory": delete_directory_tool
}