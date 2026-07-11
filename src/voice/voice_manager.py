"""
VoiceManager — Refactor del modulo voice.

Separa STT e TTS in funzioni pulite e introduce il contesto
breve per gestire le conversazioni vocali multi-turno.
"""

import os
import subprocess

import requests


def _transcribe_audio(temp_filename: str, language: str) -> str | None:
    from src.config import STT_BACKEND, STT_CUSTOM_API_KEY, STT_CUSTOM_URL

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
        model = (
            "distil-whisper-large-v3-en" if language.startswith("en") else "whisper-large-v3-turbo"
        )
        data = {"model": model, "language": language[:2], "response_format": "json"}
    elif backend == "openai":
        # OpenAI Whisper
        api_key = os.getenv("OPENAI_API_KEY", os.getenv("LLM_API_KEY", ""))
        url = "https://api.openai.com/v1/audio/transcriptions"
        model = "whisper-1"
        data = {"model": model, "language": language[:2], "response_format": "json"}
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


def listen_stt(
    recognizer, language: str = "it", timeout: int = 5, phrase_limit: int = 10
) -> str | None:
    """
    Ascolta dal microfono e ritorna il testo trascritto usando il backend STT configurato.
    Returns None on error or silence.
    """
    if not recognizer:
        return None
    try:
        import speech_recognition as sr

        from src.utils import no_alsa_err

        # Riduciamo il tempo che il recognizer aspetta dopo che l'utente smette di parlare
        recognizer.pause_threshold = 0.35
        recognizer.non_speaking_duration = 0.25

        with no_alsa_err(), sr.Microphone() as source:
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
                from src.voice.hybrid_input import (
                    pause_hybrid_listener,
                    resume_hybrid_listener,
                )

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
