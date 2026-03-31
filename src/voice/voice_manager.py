"""
VoiceManager — Refactor del modulo voice.

Separa STT e TTS in funzioni pulite e introduce il contesto
breve per gestire le conversazioni vocali multi-turno.
"""
import subprocess
import os
from dataclasses import dataclass, field
from typing import Optional, List
import requests


@dataclass
class VoiceContext:
    """
    Buffer di contesto breve per interazioni vocali.
    Mantiene le ultime N interazioni per gestire follow-up.
    """
    max_turns: int = 3
    history: List[dict] = field(default_factory=list)

    def add_turn(self, user_text: str, agent_response: str):
        self.history.append({"user": user_text, "agent": agent_response})
        if len(self.history) > self.max_turns:
            self.history = self.history[-self.max_turns:]

    def get_context_string(self) -> str:
        if not self.history:
            return ""
        lines = ["[Contesto vocale recente]"]
        for turn in self.history:
            lines.append(f"  User: {turn['user']}")
            lines.append(f"  Argos: {turn['agent'][:100]}")
        return "\n".join(lines)

    def clear(self):
        self.history = []


def init_stt():
    """Inizializza il motore Speech-to-Text. Ritorna (recognizer, is_active)."""
    try:
        from src.utils import no_alsa_err
        with no_alsa_err():
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            # Ritornato al default (0.8) per essere scattante
            recognizer.pause_threshold = 0.8 
            # Assolutamente fondamentale per evitare che il mic resti acceso per 15s credendo che il rumore di fondo sia voce
            recognizer.dynamic_energy_threshold = True
            try:
                with sr.Microphone() as source:
                    pass
                return recognizer, True
            except Exception:
                print("⚠️  Microfono non rilevato.")
                return recognizer, False
    except ImportError:
        print("❌ Mancano librerie voce (SpeechRecognition).")
        return None, False


def _transcribe_audio(temp_filename: str, language: str) -> Optional[str]:
    from src.config import STT_BACKEND, STT_CUSTOM_URL, STT_CUSTOM_API_KEY
    import os
    
    backend = STT_BACKEND
    
    # We load standard keys if backend is groq/openai
    # Fallback to LLM_API_KEY if specific keys are not in env
    api_key = ""
    url = ""
    model = ""
    data = {}
    
    if backend == "groq":
        # Groq Whisper
        api_key = os.getenv("GROQ_API_KEY", os.getenv("LLM_API_KEY", ""))
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        model = "distil-whisper-large-v3-en" if language.startswith("en") else "whisper-large-v3-turbo"
        data = {
            "model": model,
            "language": language[:2],
            "response_format": "json"
        }
    elif backend == "openai":
        # OpenAI Whisper
        api_key = os.getenv("OPENAI_API_KEY", os.getenv("LLM_API_KEY", ""))
        url = "https://api.openai.com/v1/audio/transcriptions"
        model = "whisper-1"
        data = {
            "model": model,
            "language": language[:2],
            "response_format": "json"
        }
    elif backend == "custom":
        # Custom Endpoint
        api_key = STT_CUSTOM_API_KEY
        url = STT_CUSTOM_URL
        if not url:
            raise ValueError("STT_BACKEND=custom requires STT_CUSTOM_URL to be set in .env")
        # Custom may not need a model or language spec if defaults handle it
        data = {}
        # Try injecting if standard behavior allows
        if language:
            data["language"] = language[:2]
    else:
        raise ValueError(f"Unknown STT_BACKEND: '{backend}'")

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    with open(temp_filename, "rb") as f:
        files = {"file": (temp_filename, f, "audio/wav")}
        response = requests.post(url, headers=headers, files=files, data=data, timeout=15)
        
    if response.status_code == 429:
        print("⚠️  Trascrizione: Rate Limit raggiunto (Audio). Riprova tra poco.")
        return None
        
    if response.status_code != 200:
        print(f"❌ STT API Error: {response.text}")
        return None
        
    try:
        return response.json().get("text", "").strip()
    except Exception:
        print(f"❌ Invalid STT JSON Response: {response.text}")
        return None


def listen_stt(recognizer, language: str = "it", timeout: int = 5, phrase_limit: int = 10) -> Optional[str]:
    """
    Ascolta dal microfono e ritorna il testo trascritto usando il backend STT configurato.
    Returns None on error or silence.
    """
    if not recognizer:
        return None
    try:
        from src.utils import no_alsa_err
        import speech_recognition as sr
        
        # Riduciamo il tempo che il recognizer aspetta dopo che l'utente smette di parlare
        recognizer.pause_threshold = 0.35
        recognizer.non_speaking_duration = 0.25
        
        with no_alsa_err():
            with sr.Microphone() as source:
                print("\n🎤 In ascolto...")
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
                
                print("   (Trascrizione STT in corso...)")
                
                # Salva temporaneamente l'audio
                wav_data = audio.get_wav_data()
                temp_filename = "/tmp/argos_stt.wav"
                with open(temp_filename, "wb") as f:
                    f.write(wav_data)
                
                text = _transcribe_audio(temp_filename, language)
                
                if text:
                    print(f'👤 Tu: "{text}"')
                    return text
                return None
                
    except Exception as e:
        # Silenzio su errori di timeout o audio vuoto
        if "Timeout" not in str(e):
            pass
        return None


def speak_tts(text: str, lang: str = "it", manage_listener: bool = True, wait: bool = False):
    """Sintetizza il testo in voce usando gTTS + mpg123.
    
    Args:
        manage_listener: Se True, mette in pausa/riprende il listener STT autonomamente.
                         Se False, assume che il chiamante gestisca il ciclo di vita del listener.
        wait: Ignorato (presente per compatibilità con la chiamata esterna).
    """
    if not text:
        return
    # Non leggere JSON o output tecnici
    if text.strip().startswith("{") or '"tool":' in text:
        return
    try:
        from gtts import gTTS
        clean_text = text.replace("*", "").replace("#", "").replace("`", "")
        tts = gTTS(text=clean_text, lang=lang, slow=False)
        filename = "/tmp/argos_voice.mp3"
        tts.save(filename)
        
        # Mette in pausa l'ascolto background per evitare che si senta da solo
        if manage_listener:
            try:
                from src.voice.hybrid_input import pause_hybrid_listener, resume_hybrid_listener
                pause_hybrid_listener()
            except ImportError:
                pass

        subprocess.run(
            ["mpg123", "-q", filename],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        # Riattiva l'ascolto
        if manage_listener:
            try:
                from src.voice.hybrid_input import resume_hybrid_listener
                resume_hybrid_listener()
            except Exception:
                pass
            
    except Exception:
        pass
