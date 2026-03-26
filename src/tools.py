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
    # Try XDG user-dirs config
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
    
    # Common fallback directory names
    for c in ["Scrivania", "Desktop", "Escritorio"]:
        path = os.path.join(home, c)
        if os.path.isdir(path): return path
    return home

def _normalize_path(path_str):
    if not path_str: return _get_desktop_path()
    path_str = str(path_str).strip()
    
    # FIX: Handle Windows-style paths (C:/Users/...) hallucinated by the LLM on Linux
    if ":" in path_str and not path_str.startswith("/"):
        # Extract only the final filename and redirect to the correct desktop path
        base_name = os.path.basename(path_str.replace("\\", "/"))
        return os.path.join(_get_desktop_path(), base_name)

    # Expand home directory shorthand
    if "~" in path_str:
        path_str = os.path.expanduser(path_str)

    # Return absolute paths unchanged
    if os.path.isabs(path_str):
        return path_str
        
    # Relative paths are resolved against the desktop directory
    return os.path.join(_get_desktop_path(), path_str)


def _get_arg(inp, keys, default=None):
    """Extracts an argument by searching across multiple possible key names."""
    if isinstance(inp, str): return inp
    if isinstance(inp, dict):
        for k in keys:
            if k in inp and inp[k]: return inp[k]
    return default

# --- WEB & INFO TOOLS ---

def crypto_price_tool(coin_id):
    coin_id = _get_arg(coin_id, ["coin", "id", "name"])
    if not coin_id: return "Error: Please specify a coin identifier."
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id.lower()}&vs_currencies=eur"
        r = requests.get(url, timeout=5)
        val = r.json().get(coin_id.lower(), {}).get('eur')
        return f"€{val:,.2f}" if val else "Coin not found."
    except Exception as e: return f"API Error: {e}"

def finance_price_tool(asset):
    asset_name = _get_arg(asset, ["asset", "symbol", "name", "ticker"])
    if not asset_name: return "Error: Please specify an asset (e.g., 'gold', 'AAPL')."
    
    # Convenience mapping for the LLM (which may not always know exact YF ticker symbols)
    common_symbols = {
        "oro": "GC=F", "gold": "GC=F",
        "argento": "SI=F", "silver": "SI=F",
        "platino": "PL=F", "platinum": "PL=F",
        "petrolio": "CL=F", "oil": "CL=F",
        "gas": "NG=F",
        "sp500": "^GSPC", "s&p500": "^GSPC",
        "nasdaq": "^IXIC", "dow": "^DJI"
    }
    
    # Sanitize LLM-generated input artifacts like "gold in euro" or "GOLD_EUR"
    clean_asset = asset_name.lower().strip().replace(' in euro', '').replace('_euro','').replace(' euro', '')
    ticker = common_symbols.get(clean_asset, asset_name.upper())
    
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        # Some assets use 'currentPrice', others 'regularMarketPrice'
        info = t.fast_info
        if hasattr(info, 'last_price') and info.last_price is not None:
            price = info.last_price
            # Attempt to extract currency denomination if available
            currency = t.info.get('currency', 'USD') if hasattr(t, 'info') else 'USD'
            
            # Append unit of measure where applicable (precious metals are priced per troy ounce)
            unit_str = ""
            if "oro" in clean_asset or "gold" in clean_asset or "argento" in clean_asset or "silver" in clean_asset:
                unit_str = " per troy ounce (oz)"
                
            # Base output string
            output = f"{asset_name.capitalize()} (Ticker: {ticker}): {price:,.2f} {currency}{unit_str}"
            
            # Supplementary calculations (EUR conversion and per-gram pricing)
            if currency == 'USD':
                try:
                    eur_usd = yf.Ticker("EURUSD=X").fast_info.last_price
                    if eur_usd:
                        price_eur = price / eur_usd
                        output += f" (Equivalente calcolato: {price_eur:,.2f} EUR{unit_str})"
                        
                        # For precious metals, also compute per-gram price
                        if unit_str:
                            price_gram_eur = price_eur / 31.1034768
                            output += f" -> Circa {price_gram_eur:,.2f} EUR al grammo"
                except Exception:
                    pass
            
            return output
        
        return f"Price not found for '{ticker}'. Please verify the asset name or ticker symbol."
    except Exception as e:
        return f"Finance API Error: {e}"

def web_search_tool(query):
    q = _get_arg(query, ["query", "q", "search", "text", "search_query", "keywords"])
    # Fallback: if dict has no recognized key, extract the first string value
    if not q and isinstance(query, dict):
        values = [v for v in query.values() if isinstance(v, str) and v.strip()]
        q = values[0] if values else None
    # Final fallback: raw string input
    if not q and isinstance(query, str):
        q = query
    if not q:
        return "Error: No search query specified."
    try:
        from ddgs import DDGS
        results = DDGS().text(query=q, max_results=5, region="it-it")
        if not results: return "No results found. DO NOT fabricate data under any circumstances. Inform the user that the search returned no results."
        
        output = []
        for r in results:
            output.append(f"--- {r['title']} ---\n{r['body']}\n")
        return "\n".join(output)
    except Exception as e:
        return f"Search Error: {e}. The search servers are unreachable or the API has changed. DO NOT fabricate any information. Inform the user that a technical error occurred."

def system_stats_tool(_):
    return f"CPU: {psutil.cpu_percent()}%, RAM: {psutil.virtual_memory().percent}%"

# --- FILE SYSTEM TOOLS ---

def list_files_tool(inp):
    raw_path = _get_arg(inp, ["path", "directory", "folder"])
    if raw_path in [".", "DESKTOP", None]: target = _get_desktop_path()
    else: target = _normalize_path(raw_path)

    if not os.path.exists(target): return f"Error: '{target}' does not exist."
    try:
        items = [f for f in os.listdir(target) if not f.startswith('.')]
        items.sort()
        return f"📂 '{os.path.basename(target)}': {', '.join(items[:50])}"
    except Exception as e: return f"Error: {e}"

def read_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "file"])
    path = _normalize_path(fname)
    if not os.path.exists(path): return "File not found."
    if os.path.isdir(path): return "Target is a directory, use list_files instead."
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f"📄 CONTENT:\n{f.read(3000)}"
    except Exception as e: return f"Error: {e}"

def create_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "name"], "untitled.txt")
    if "." not in fname: fname += ".txt"
    path = _normalize_path(fname)
    
    content = inp.get("content", "") if isinstance(inp, dict) else ""

    if os.path.exists(path): return f"⚠️ File '{os.path.basename(path)}' already exists."
    try:
        with open(path, "w", encoding="utf-8") as f: f.write(content)
        return f"✅ Created: {path}"
    except Exception as e: return f"Error: {e}"

def create_directory_tool(inp):
    name = _get_arg(inp, ["name", "path", "directory", "dirname"])
    if not name: return "Error: Please specify a directory name."
    
    path = _normalize_path(name)
    
    if os.path.exists(path):
        return f"⚠️ Directory or file '{os.path.basename(path)}' already exists."
    
    try:
        os.makedirs(path, exist_ok=True)
        return f"✅ Directory created: {path}"
    except Exception as e:
        return f"Directory creation error: {e}"
    
def delete_directory_tool(inp):
    name = _get_arg(inp, ["name", "path", "directory", "dirname"])
    if not name: return "Error: Please specify the directory name to delete."
    
    path = _normalize_path(name)
    
    if not os.path.exists(path):
        return f"Error: Directory '{path}' does not exist."
    if not os.path.isdir(path):
        return f"Error: '{path}' is not a directory (possibly a file)."
    
    try:
        import shutil
        shutil.rmtree(path)  # Recursively delete directory and all contents
        return f"🗑️ Directory successfully deleted: {path}"
    except Exception as e:
        return f"Directory deletion error: {e}"


def modify_file_tool(inp):
    # Modifies file CONTENT (overwrite or append)
    fname = _get_arg(inp, ["filename", "path", "file"])
    if not fname: return "Error: Please specify the filename to modify."
    
    path = _normalize_path(fname)
    if not os.path.exists(path): return "Error: File not found."

    content = inp.get("content", "") if isinstance(inp, dict) else ""
    mode = "a" if isinstance(inp, dict) and inp.get("mode") == "append" else "w"

    try:
        with open(path, mode, encoding="utf-8") as f:
            if mode == "a": f.write("\n" + content)
            else: f.write(content)
        return f"✅ Modified ({mode}): {path}"
    except Exception as e: return f"Error: {e}"

def rename_file_tool(inp):
    # File/directory rename operation
    old = _get_arg(inp, ["old_name", "old_path", "filename", "current_name"])
    new = _get_arg(inp, ["new_name", "new_path", "name"])
    
    if not old or not new: return "Error: Both 'old_name' and 'new_name' are required."
    
    p_old = _normalize_path(old)
    p_new = _normalize_path(new)
    
    if not os.path.exists(p_old): return f"Error: '{old}' not found."
    if os.path.exists(p_new): return f"Error: '{new}' already exists."
    
    try:
        os.rename(p_old, p_new)
        return f"✅ Renamed: {old} -> {new}"
    except Exception as e: return f"Rename error: {e}"

def delete_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "file"])
    path = _normalize_path(fname)
    if not os.path.exists(path): return "File not found."
    try:
        if os.path.isdir(path): shutil.rmtree(path)  # FIX: rmtree for non-empty directories
        else: os.remove(path)
        return f"🗑️ Deleted: {path}"
    except Exception as e: return f"Error: {e}"

# --- AUTOMATION TOOLS ---

def launch_app_tool(inp):
    cmd = _get_arg(inp, ["app_name", "command", "cmd"])
    try:
        subprocess.Popen(shlex.split(cmd), stdout=subprocess.DEVNULL, start_new_session=True)
        return f"🚀 Launched: {cmd}"
    except Exception as e: return f"Error: {e}"

def _focus_window(app_name):
    """Attempts to bring a window to the foreground using wmctrl on Linux."""
    if not app_name: return
    try:
        # wmctrl -a searches for a window containing 'app_name' in the title
        subprocess.run(["wmctrl", "-a", app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)  # Allow time for window animation
    except Exception:
        pass

def keyboard_type_tool(inp):
    if not PYAUTOGUI_AVAILABLE: return "GUI Error: pyautogui unavailable."
    
    text = inp.get("text", "")
    target = _get_arg(inp, ["at_element", "where", "target"])
    press_enter = inp.get("press_enter", False)
    
    # 1. WINDOW MANAGEMENT (XORG)
    # Attempt to activate the relevant window if mentioned
    common_apps = ["firefox", "chrome", "code", "terminal", "discord", "spotify", "gedit", "files", "nautilus", "settings"]
    if target:
        t_low = target.lower()
        for app in common_apps:
            if app in t_low:
                print(f"🚀 Activating window '{app}'...")
                try:
                    subprocess.run(["xdotool", "search", "--onlyvisible", "--name", app, "windowactivate"], 
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(0.8) # Allow time for window redraw
                except: pass
                break

    # 2. VISION AND CLICK
    if target:
        print(f"👀 Searching for target: '{target}'")
        
        # 2a. Try OCR first (most accurate for text elements)
        coords = vision.find_text_on_screen(target)
        
        # 2b. Fallback to VLM Grid (for icons, unlabeled buttons, complex descriptions)
        if not coords or "x" not in coords:
            print(f"⚠️ OCR failed for '{target}', falling back to VLM Grid analysis...")
            coords = vision.analyze_screen_for_coordinates(target)
        
        if coords and "x" in coords:
            x, y = coords['x'], coords['y']
            print(f"🎯 Moving cursor to ({x}, {y})")
            
            # Human-like movement (non-instantaneous)
            pyautogui.moveTo(x, y, duration=0.8, tween=pyautogui.easeInOutQuad)
            
            # Offset correction (optional): LLMs sometimes aim slightly too high
            # If clicks consistently land on the upper border, uncomment the line below:
            # y += 10
            
            pyautogui.click()
            time.sleep(0.1)
            pyautogui.click()  # Double click to select text/input field
            time.sleep(0.5)
        else:
            print("⚠️ Target not found. Typing at current cursor position.")

    # 3. TEXT INPUT
    try:
        if text and text.strip():
            print(f"✍️  Typing: {text}")
            pyautogui.write(text, interval=0.05)
        
        if press_enter: 
            time.sleep(0.3)
            print("↵ Enter")
            pyautogui.press('enter')
            
        return f"✅ Done."
    except Exception as e: return f"Error: {e}"

# NOTE: _get_arg is defined at line 66. Duplicate copy removed.

def _focus_window_xorg(name_fragment):
    """Attempts to bring a window to the foreground using xdotool on Xorg."""
    if not name_fragment: return False
    try:
        # Search for visible windows containing the given name fragment
        subprocess.run(["xdotool", "search", "--onlyvisible", "--name", name_fragment, "windowactivate"], 
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        try:
            # Fallback: search by window class name
            subprocess.run(["xdotool", "search", "--onlyvisible", "--class", name_fragment, "windowactivate"], 
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

def visual_click_tool(inp):
    if not PYAUTOGUI_AVAILABLE: return "Error: GUI library unavailable."
    
    description = _get_arg(inp, ["description", "target", "element"])
    click_type = _get_arg(inp, ["click_type", "type"], "left").lower()
    
    if not description: return "Error: Target description missing."

    # 1. AUTOMATIC WINDOW FOCUS
    # If the user says "Click Bluetooth in Settings", attempt to activate the relevant window
    common_apps = ["settings", "impostazioni", "firefox", "chrome", "terminal", "code"]
    desc_lower = description.lower()
    for app in common_apps:
        if app in desc_lower:
            print(f"🚀 Context detected '{app}': Activating window...")
            _focus_window_xorg(app)
            time.sleep(1.0)  # Allow time for Linux window animation
            break
    # 2. VISION AND TARGET ACQUISITION
    print(f"👀 Visual search for click target: '{description}'")
    
    # 2a. Try OCR first (best for text elements)
    coords = vision.find_text_on_screen(description)
    
    # 2b. Fallback to VLM Grid System
    if not coords or "x" not in coords:
        print(f"⚠️ OCR could not locate '{description}', falling back to VLM Grid analysis...")
        coords = vision.analyze_screen_for_coordinates(description)

    if coords and "x" in coords:
        x, y = coords['x'], coords['y']
        print(f"🎯 Target coordinates: ({x}, {y})")

        # 3. PHYSICAL ACTION
        pyautogui.moveTo(x, y, duration=0.8, tween=pyautogui.easeInOutQuad)
        
        if "right" in click_type or "destr" in click_type:
            pyautogui.click(button='right')
            res = "Right Click"
        elif "double" in click_type or "doppio" in click_type:
            pyautogui.doubleClick()
            res = "Double Click"
        else:
            pyautogui.click()
            res = "Left Click"

        return f"✅ {res} executed on '{description}'."
    
    return f"⚠️ Unable to visually locate: '{description}'"

def describe_screen_tool(inp):
    q = _get_arg(inp, ["question"], "What do you see?")
    return vision.describe_screen_content(q)

TOOLS = {
    "finance_price": finance_price_tool,
    "crypto_price": crypto_price_tool,
    "web_search": web_search_tool,
    "system_stats": system_stats_tool,
    "list_files": list_files_tool,
    "read_file": read_file_tool,
    "create_file": create_file_tool,
    "modify_file": modify_file_tool,
    "rename_file": rename_file_tool,
    "delete_file": delete_file_tool,
    "launch_app": launch_app_tool,
    "keyboard_type": keyboard_type_tool,
    "visual_click": visual_click_tool,
    "describe_screen": describe_screen_tool,
    "create_directory": create_directory_tool,
    "delete_directory": delete_directory_tool
}