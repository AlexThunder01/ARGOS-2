"""GUI automation tools (visual click, keyboard, app launcher)."""
import subprocess
import shlex
import time
from .helpers import _get_arg

# --- OPTIONAL DEPENDENCIES CHECK ---
PYAUTOGUI_AVAILABLE = False
try:
    import pyautogui
    pyautogui.FAILSAFE = True 
    PYAUTOGUI_AVAILABLE = True
except Exception:
    pass


def launch_app_tool(inp):
    cmd = _get_arg(inp, ["app_name", "command", "cmd"])
    try:
        subprocess.Popen(shlex.split(cmd), stdout=subprocess.DEVNULL, start_new_session=True)
        return f"🚀 Launched: {cmd}"
    except Exception as e: return f"Error: {e}"

def _focus_window_xorg(name_fragment):
    """Attempts to bring a window to the foreground using xdotool on Xorg."""
    if not name_fragment: return False
    try:
        subprocess.run(["xdotool", "search", "--onlyvisible", "--name", name_fragment, "windowactivate"], 
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        try:
            subprocess.run(["xdotool", "search", "--onlyvisible", "--class", name_fragment, "windowactivate"], 
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

def keyboard_type_tool(inp):
    if not PYAUTOGUI_AVAILABLE: return "GUI Error: pyautogui unavailable."
    from src import vision
    
    text = inp.get("text", "")
    target = _get_arg(inp, ["at_element", "where", "target"])
    press_enter = inp.get("press_enter", False)
    
    # 1. WINDOW MANAGEMENT (XORG)
    common_apps = ["firefox", "chrome", "code", "terminal", "discord", "spotify", "gedit", "files", "nautilus", "settings"]
    if target:
        t_low = target.lower()
        for app in common_apps:
            if app in t_low:
                print(f"🚀 Activating window '{app}'...")
                try:
                    subprocess.run(["xdotool", "search", "--onlyvisible", "--name", app, "windowactivate"], 
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(0.8)
                except: pass
                break

    # 2. VISION AND CLICK
    if target:
        print(f"👀 Searching for target: '{target}'")
        coords = vision.find_text_on_screen(target)
        
        if not coords or "x" not in coords:
            print(f"⚠️ OCR failed for '{target}', falling back to VLM Grid analysis...")
            coords = vision.analyze_screen_for_coordinates(target)
        
        if coords and "x" in coords:
            x, y = coords['x'], coords['y']
            print(f"🎯 Moving cursor to ({x}, {y})")
            pyautogui.moveTo(x, y, duration=0.8, tween=pyautogui.easeInOutQuad)
            pyautogui.click()
            time.sleep(0.1)
            pyautogui.click()
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


def visual_click_tool(inp):
    if not PYAUTOGUI_AVAILABLE: return "Error: GUI library unavailable."
    from src import vision
    
    description = _get_arg(inp, ["description", "target", "element"])
    click_type = _get_arg(inp, ["click_type", "type"], "left").lower()
    
    if not description: return "Error: Target description missing."

    # 1. AUTOMATIC WINDOW FOCUS
    common_apps = ["settings", "impostazioni", "firefox", "chrome", "terminal", "code"]
    desc_lower = description.lower()
    for app in common_apps:
        if app in desc_lower:
            print(f"🚀 Context detected '{app}': Activating window...")
            _focus_window_xorg(app)
            time.sleep(1.0)
            break

    # 2. VISION AND TARGET ACQUISITION
    print(f"👀 Visual search for click target: '{description}'")
    coords = vision.find_text_on_screen(description)
    
    if not coords or "x" not in coords:
        print(f"⚠️ OCR could not locate '{description}', falling back to VLM Grid analysis...")
        coords = vision.analyze_screen_for_coordinates(description)

    if coords and "x" in coords:
        x, y = coords['x'], coords['y']
        print(f"🎯 Target coordinates: ({x}, {y})")
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
    from src import vision
    q = _get_arg(inp, ["question"], "What do you see?")
    return vision.describe_screen_content(q)
