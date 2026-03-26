import base64
import io
import json
import os
import re
import subprocess
import requests
import pytesseract
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

def add_grid_to_image(image, step=80):
    """Disegna una griglia con etichette ad ogni intersezione per massima precisione VLM."""
    draw = ImageDraw.Draw(image)
    width, height = image.size
    grid_color = (0, 255, 0)  # Verde fluo
    label_bg = (0, 0, 0)      # Sfondo nero per leggibilità
    
    # Prova a caricare un font più grande per leggibilità
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except Exception:
        font = ImageDraw.Draw(image).getfont()
    
    # Linee Verticali con etichette in alto
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=grid_color, width=1)
    
    # Linee Orizzontali con etichette a sinistra
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=grid_color, width=1)
    
    # Etichette ad OGNI intersezione (il trucco per la precisione)
    for x in range(0, width, step):
        for y in range(0, height, step):
            label = f"{x},{y}"
            # Sfondo nero per il testo
            bbox = font.getbbox(label)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.rectangle([x + 2, y + 2, x + tw + 6, y + th + 6], fill=label_bg)
            draw.text((x + 4, y + 2), label, fill=grid_color, font=font)
    
    return image

# --- NEW: OCR TEXT FINDER ---
def find_text_on_screen(text_to_find, lang='ita+eng'):
    """
    Cerca un testo specifico sullo schermo usando OCR (Tesseract).
    Ritorna il centro (x, y) della prima occorrenza trovata.
    Molto più preciso del VLM per cliccare scritte!
    """
    print(f"🔍 Analisi OCR per il testo: '{text_to_find}'...")
    screen = take_screenshot_robust()
    if not screen: return None

    # Esegui OCR restituendo dizionario dati (parole, bounding box, confidenza)
    try:
        data = pytesseract.image_to_data(screen, lang=lang, output_type=pytesseract.Output.DICT)
    except Exception as e:
        print(f"❌ OCR Error: {e}")
        return None

    target = text_to_find.lower().strip()
    words = target.split()
    
    # Se cerchiamo una singola parola
    if len(words) == 1:
        for i, word in enumerate(data['text']):
            if target in word.lower() and int(data['conf'][i]) > 40:
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                cx, cy = x + w//2, y + h//2
                print(f"🎯 OCR Trovato '{word}' -> Coordinate: ({cx}, {cy})")
                return {"x": cx, "y": cy}
                
    # Se cerchiamo una frase (più parole consecutive)
    # Match semplice best-effort: cerca se una delle parole chiave esiste con alta confidenza
    # Nelle GUI spesso basta trovare la parola più unica della frase
    else:
        longest_word = max(words, key=len)
        if len(longest_word) > 3:
            for i, word in enumerate(data['text']):
                if longest_word in word.lower() and int(data['conf'][i]) > 30:
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    cx, cy = x + w//2, y + h//2
                    print(f"🎯 OCR Trovato '{word}' (da frase) -> Coordinate: ({cx}, {cy})")
                    return {"x": cx, "y": cy}

    print("❌ OCR did not find the target text.")
    return None

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
        
        # --- PROMPT DI PRECISIONE MIGLIORATO ---
        prompt = (
            f"This is a screenshot of a Linux desktop with resolution {target_w}x{target_h} pixels. "
            f"A GREEN GRID is overlaid on the image. Each intersection has coordinates labeled as 'x,y'. "
            f"\n\nCOORDINATE SYSTEM:"
            f"\n- x=0 is the LEFT edge, x={target_w} is the RIGHT edge"
            f"\n- y=0 is the TOP edge (top of screen), y={target_h} is the BOTTOM edge"
            f"\n- Elements at the TOP of the screen have SMALL y values (y < 100)"
            f"\n- Elements at the BOTTOM of the screen have LARGE y values (y > {target_h - 100})"
            f"\n\nTASK: Find the pixel coordinates of the CENTER of this element: '{description}'"
            f"\n\nSTEPS:"
            f"\n1. First, identify WHERE on the screen the element is (top/middle/bottom, left/center/right)"
            f"\n2. Find the nearest grid label to the element"
            f"\n3. Estimate the precise x,y coordinates"
            f"\n\nReturn ONLY a JSON object: {{\"x\": <number>, \"y\": <number>}}"
            f"\nDo NOT write any other text."
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
                print(f"❌ Invalid JSON format received: {content}")
        else:
            print(f"⚠️ No JSON found in response: {content}")

    except Exception as e:
        print(f"❌ Internal Vision analysis error: {e}")
    
    return None

# --- FUNZIONE 2: DESCRIZIONE SCHERMO (PULITA) ---
def describe_screen_content(question):
    print("📸 Analisi visiva schermo (Descrizione)...")
    screen = take_screenshot_robust()
    if not screen: return "Screenshot error."

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
        return f"Internal Vision Error: {e}"

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