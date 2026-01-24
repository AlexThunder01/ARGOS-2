import base64
import io
import json
import os
import re
import subprocess
import requests
from PIL import Image, ImageDraw
from .utils import detect_backend 
from .config import (GROQ_API_KEY, GROQ_CHAT_URL, OLLAMA_URL, 
                     MODEL_GROQ, VISION_MODEL_OLLAMA, VISION_MODEL_GROQ)

def encode_image_to_base64(image):
    buffered = io.BytesIO()
    # TRUCCO FONDAMENTALE: Se l'immagine ha trasparenza (RGBA), 
    # la convertiamo in RGB (sfondo nero o bianco) prima di salvare in JPEG
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    image.save(buffered, format="JPEG", quality=95)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# Fai la stessa cosa per la funzione High Quality se l'hai aggiunta:
def encode_image_to_base64_high_quality(image):
    buffered = io.BytesIO()
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    image.save(buffered, format="JPEG", quality=100) 
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def get_sanitized_env():
    clean_env = {}
    clean_env["PATH"] = "/usr/bin:/bin:/usr/local/bin"
    clean_env["HOME"] = os.path.expanduser("~")
    for key in ["DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XAUTHORITY"]:
        if key in os.environ:
            clean_env[key] = os.environ[key]
    return clean_env


def take_screenshot_robust():
    filename = "/tmp/jarvis_vision_snap.png"
    if os.path.exists(filename): os.remove(filename)

    env = get_sanitized_env()
    methods = [
        ["/usr/bin/gnome-screenshot", "-f", filename],
        ["/usr/bin/scrot", "-o", filename],
        ["/usr/bin/import", "-window", "root", filename]
    ]

    for cmd in methods:
        try:
            subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if os.path.exists(filename):
                return Image.open(filename)
        except Exception:
            continue
    return None

def add_grid_to_image(image, step=100):
    draw = ImageDraw.Draw(image)
    width, height = image.size
    # Verde fluo per massimo contrasto
    grid_color = (0, 255, 0) 
    
    # Linee Verticali
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=grid_color, width=2) # Spessore 2
        draw.text((x + 5, 5), str(x), fill=grid_color)

    # Linee Orizzontali
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=grid_color, width=2)
        draw.text((5, y + 5), str(y), fill=grid_color)
        
    return image

# --- FUNZIONE 1: ANALISI COORDINATE (CON GRIGLIA) ---
def analyze_screen_for_coordinates(description):
    """
    Versione Definitiva: 
    - Fix RGBA -> RGB (niente più crash JPEG)
    - Griglia Verde ad alta visibilità
    - Parser JSON robusto
    - Scaling matematico preciso
    """
    print(f"📸 Analisi visiva di precisione (Grid) per: '{description}'...")
    screen = take_screenshot_robust()
    if not screen: 
        print("❌ Impossibile acquisire lo screenshot.")
        return None

    # --- FIX CRASH RGBA ---
    # Convertiamo l'immagine in RGB per supportare il formato JPEG ed evitare errori
    if screen.mode != "RGB":
        screen = screen.convert("RGB")

    real_w, real_h = screen.size
    
    try:
        # --- RESIZE PER IL MODELLO ---
        # Usiamo 1280px come larghezza di riferimento per l'analisi
        target_w = 1280
        scale_factor = target_w / real_w
        target_h = int(real_h * scale_factor)
        
        # Ridimensioniamo l'immagine originale
        screen_resized = screen.resize((target_w, target_h), Image.Resampling.LANCZOS)
        
        # --- APPLICAZIONE GRIGLIA VERDE ---
        # Disegniamo la griglia sulla versione ridimensionata che vedrà l'LLM
        screen_with_grid = add_grid_to_image(screen_resized.copy(), step=100)
        
        # Salviamo un'immagine di debug per permetterti di controllare cosa vede Jarvis
        screen_with_grid.save("debug_visione.jpg")
        
        # Codifica in Base64
        img_b64 = encode_image_to_base64(screen_with_grid)
        
        backend = detect_backend()
        model_to_use = VISION_MODEL_GROQ if backend == "groq" else VISION_MODEL_OLLAMA
        
        # --- PROMPT DI PRECISIONE ---
        prompt = (
            f"Image resolution: {target_w}x{target_h}. "
            f"I have overlaid a BRIGHT GREEN GRID. The numbers on the edges are pixel coordinates. "
            f"TASK: Find the exact center (x, y) for: '{description}'. "
            "Look at the grid lines to provide an accurate estimate. "
            "Return ONLY a JSON object: {\"x\": 123, \"y\": 456}. "
            "DO NOT write any other text."
        )

        # Chiamata al modello Vision (VLM)
        content = _call_vlm(backend, model_to_use, prompt, img_b64)
        
        if not content:
            print("❌ Il modello Vision non ha restituito dati.")
            return None

        # --- PARSER JSON ROBUSTO ---
        content = content.strip()
        # Estrae solo la parte tra le parentesi graffe per ignorare chiacchiere extra
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            json_str = match.group(0)
            try:
                coords = json.loads(json_str)
                if "x" in coords and "y" in coords:
                    seen_x = float(coords["x"])
                    seen_y = float(coords["y"])
                    
                    # --- SCALING INVERSO ---
                    # Riportiamo le coordinate dall'immagine 1280px ai pixel reali del monitor
                    final_x = int(seen_x / scale_factor)
                    final_y = int(seen_y / scale_factor)
                    
                    print(f"🎯 Coordinate calcolate: LLM({seen_x},{seen_y}) -> MONITOR({final_x},{final_y})")
                    return {"x": final_x, "y": final_y}
            except json.JSONDecodeError:
                print(f"❌ Errore nel formato JSON ricevuto: {content}")
        else:
            print(f"⚠️ Nessun JSON trovato nella risposta: {content}")

    except Exception as e:
        print(f"❌ Errore interno durante l'analisi Vision: {e}")
    
    return None

# --- FUNZIONE 2: DESCRIZIONE SCHERMO (PULITA) ---
def describe_screen_content(question):
    print("📸 Analisi visiva schermo (Descrizione)...")
    screen = take_screenshot_robust()
    if not screen: return "Errore screenshot."

    try:
        # Resize per velocità, ma niente griglia
        screen.thumbnail((1500, 1500))
        img_b64 = encode_image_to_base64_high_quality(screen)
        
        backend = detect_backend()
        model_to_use = VISION_MODEL_GROQ if backend == "groq" else VISION_MODEL_OLLAMA
        
        prompt = (
            "You are Jarvis. Analyze this computer screenshot. "
            "Describe the visible windows, applications, text, and context. "
            f"User Question: {question}"
        )

        content = _call_vlm(backend, model_to_use, prompt, img_b64)
        
        # Filtro per falsi positivi di sicurezza
        if content.strip().lower() in ["safe", "unsafe", "i cannot"]:
            return "⚠️ Il modello Vision ha rifiutato l'immagine (falso positivo di sicurezza)."
            
        return content

    except Exception as e:
        return f"Errore interno Vision: {e}"

# --- HELPER CHIAMATA API ---
def _call_vlm(backend, model, prompt, img_b64):
    if backend == "groq":
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model, 
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    ]
                }
            ],
            "temperature": 0.1, 
            "max_tokens": 500
        }
        try:
            r = requests.post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=40)
            if r.status_code != 200: return f"Error {r.status_code}: {r.text}"
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e: return str(e)
    else:
        # OLLAMA
        payload = {"model": model, "messages": [{"role": "user", "content": prompt, "images": [img_b64]}], "stream": False}
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=60)
            return r.json()["message"]["content"]
        except Exception as e: return str(e)