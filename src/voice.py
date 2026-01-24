import subprocess
import os
from .utils import check_system_deps, no_alsa_err
from .config import ENABLE_VOICE

VOICE_ACTIVE = False
recognizer = None

if ENABLE_VOICE:
    try:
        with no_alsa_err():
            import speech_recognition as sr
            from gtts import gTTS 
            recognizer = sr.Recognizer()
            recognizer.pause_threshold = 1.0
            # Test rapido microfono
            try:
                with sr.Microphone() as source: pass
                VOICE_ACTIVE = True
            except:
                print("⚠️  Microfono non rilevato.")
    except ImportError:
        print("❌ Mancano librerie voce (SpeechRecognition, gTTS).")
    except Exception as e:
        print(f"❌ Errore Audio: {e}")

def speak(text):
    if not VOICE_ACTIVE or not text: return
    # Non leggere JSON o comandi tecnici
    if text.strip().startswith("{") or '"tool":' in text: return 
    
    try:
        from gtts import gTTS
        # Pulisce caratteri speciali
        clean_text = text.replace("*", "").replace("#", "").replace("`", "")
        tts = gTTS(text=clean_text, lang='it', slow=False)
        filename = "/tmp/jarvis_voice.mp3"
        tts.save(filename)
        subprocess.run(["mpg123", "-q", filename], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def listen():
    if VOICE_ACTIVE:
        with no_alsa_err():
            import speech_recognition as sr
            with sr.Microphone() as source:
                print("\n🎤 In ascolto...")
                try:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=8)
                    print("   (Elaborazione...)")
                    text = recognizer.recognize_google(audio, language="it-IT")
                    print(f"👤 Tu: \"{text}\"")
                    return text
                except: return None
    return input("\n⌨️ Scrivi tu: ")