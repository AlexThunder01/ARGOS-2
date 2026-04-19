import os
import queue
import select
import subprocess
import sys
import threading

import speech_recognition as sr

voice_command_queue = queue.Queue()
_stop_listening_fn = None
_listening = False
_bg_mic = None
_recognizer = None

# Pre-genera l'audio "Sì?" al caricamento del modulo (una sola volta)
_WAKEWORD_AUDIO = "/tmp/argos_wakeword_si.mp3"
try:
    if not os.path.exists(_WAKEWORD_AUDIO):
        from gtts import gTTS

        _tts = gTTS(text="Sì?", lang="it", slow=False)
        _tts.save(_WAKEWORD_AUDIO)
except Exception:
    pass


def _process_background_impl(recognizer, audio):
    if not _listening:
        return
    try:
        # Usa Google (gratuito e robusto per ascolti continui h24) per non
        # bruciare il rate limit dell'API Groq Whisper
        text = recognizer.recognize_google(audio, language="it-IT").strip()
        text_lower = text.lower()

        # Ignora l'auto-ascolto del TTS
        if text_lower in ["sistemi online", "sistemi", "online"]:
            return

        # LOG INVISIBILE PER CAPIRE COSA SENTE IL MIC:
        if text_lower:
            # Stampiamo leggermente per farti capire cosa sente Google in background
            print(
                f"\r🔍 [Debug STT Background] Ho sentito: '{text}'{' ' * 20}\n👤 Tu (scrivi o di' 'Argos...'): ",
                end="",
                flush=True,
            )

        # Wake word detection
        wake_words = ["argos", "arkos", "argo", "algos", "harcos"]

        detected_word = None
        for w in wake_words:
            if text_lower.startswith(w):
                detected_word = w
                break

        if detected_word:
            # Wake word rilevata! Ignoriamo il resto della frase imprecisa di Google
            # e passiamo immediatamente al riconoscimento ad alta fedeltà STT.
            print(
                f"\r🎤 [Wake-Word rilevata] Passaggio all'STT principale...{' ' * 20}\n",
                flush=True,
            )

            # import locali per evitare loop circolari
            from src.voice.voice_manager import listen_stt

            # Disattiviamo l'ascolto passivo temporaneamente per liberare la scheda audio
            pause_hybrid_listener()

            import time as _time

            _time.sleep(0.15)  # Piccolo delay per rilascio hardware

            # Feedback vocale ISTANTANEO da file pre-cached (zero rete!)
            if os.path.exists(_WAKEWORD_AUDIO):
                subprocess.Popen(
                    ["mpg123", "-q", _WAKEWORD_AUDIO],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                print("\a🟢 Dimmi!", flush=True)

            # Avviamo la registrazione ad altissima precisione con Whisper
            whisper_rec = sr.Recognizer()
            cmd = listen_stt(whisper_rec, language="it", timeout=8, phrase_limit=20)

            if cmd:
                print(f"✅ [Comando STT]: '{cmd}'\n")
                voice_command_queue.put(cmd)
            else:
                print("❌ [STT] Nessun comando rilevato.\n")

            # Riaccendiamo "le orecchie" passive di Google
            resume_hybrid_listener()

            return  # Finiamo qui per questo pezzo di audio
    except sr.UnknownValueError:
        pass
    except sr.RequestError:
        pass
    except Exception:
        pass


def _process_background_audio(recognizer, audio):
    """Callback di base: SPARA SU UN THREAD SEPARATO PER NON BLOCCARE IL MICROFONO.
    La chiamata API impiega 1-3 secondi, in quel tempo il microfono DEVE poter
    continuare ad ascoltare."""
    if not _listening:
        return
    threading.Thread(target=_process_background_impl, args=(recognizer, audio), daemon=True).start()


def start_hybrid_listener():
    """Inizializza il microfono in background per ascolto continuo."""
    global _stop_listening_fn, _listening, _bg_mic, _recognizer
    if _listening:
        return

    try:
        from src.utils import no_alsa_err

        # MONKEY-PATCH: Sopprime brutalmente gli errori Jack/ALSA che vengono
        # spammati quando il thread asincrono apre il microfono
        original_enter = sr.Microphone.__enter__

        def silenced_enter(self):
            with no_alsa_err():  # Devnull su stderr
                return original_enter(self)

        sr.Microphone.__enter__ = silenced_enter

        _recognizer = sr.Recognizer()
        _recognizer.pause_threshold = 0.8
        _recognizer.dynamic_energy_threshold = True

        with no_alsa_err():  # Silenzia l'inizializzazione principale
            _bg_mic = sr.Microphone()
            with _bg_mic as source:
                _recognizer.adjust_for_ambient_noise(source, duration=1.0)

        _listening = True
        # Forziamo phrase_time_limit per impedire che il thread resti in listening infinito
        _stop_listening_fn = _recognizer.listen_in_background(
            _bg_mic, _process_background_audio, phrase_time_limit=10
        )
        return True
    except Exception as e:
        print(f"⚠️ Background listener startup error: {e}")
        return False


def stop_hybrid_listener(wait=True):
    global _stop_listening_fn, _listening
    if _stop_listening_fn:
        # Passiamo wait_for_stop al vero stop_fn
        _stop_listening_fn(wait_for_stop=wait)
        _stop_listening_fn = None
    _listening = False


def pause_hybrid_listener():
    """Mette in pausa l'ascolto senza bloccare il thread principale."""
    stop_hybrid_listener(wait=False)


def resume_hybrid_listener():
    """Riprende l'ascolto creando un NUOVO microfono per evitare lock context conflicts."""
    global _stop_listening_fn, _listening, _recognizer, _bg_mic
    if not _listening and _recognizer:
        try:
            from src.utils import no_alsa_err

            with no_alsa_err():
                # Creiamo un'istanza pulita ogni volta per aggirare l'AssertionError
                # causato dai thread zombie che non hanno ancora mollato il microfono precedente.
                _bg_mic = sr.Microphone()
                with _bg_mic as source:
                    _recognizer.adjust_for_ambient_noise(source, duration=0.8)
        except Exception:
            pass

        _listening = True
        _stop_listening_fn = _recognizer.listen_in_background(
            _bg_mic, _process_background_audio, phrase_time_limit=10
        )


def get_hybrid_input(prompt="\n👤 Tu (scrivi o di' 'Argos...'): ") -> str:
    """Attende sia input non-bloccante da tastiera che comandi in coda dal thread STT."""
    print(prompt, end="", flush=True)

    # Svuota buffer vecchi
    while not voice_command_queue.empty():
        try:
            voice_command_queue.get_nowait()
        except queue.Empty:
            break

    while True:
        # 1. Coda vocale
        try:
            cmd = voice_command_queue.get_nowait()
            return cmd
        except queue.Empty:
            pass

        # 2. Tastiera (solo Linux/Unix usando select)
        if sys.stdin in select.select([sys.stdin], [], [], 0.2)[0]:
            line = sys.stdin.readline()
            if line:
                return line.strip()
