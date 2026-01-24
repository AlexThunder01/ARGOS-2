import os
from dotenv import load_dotenv

# Carica il file .env dalla root del progetto
load_dotenv()

# Backend (groq o ollama)
LLM_BACKEND = os.getenv("LLM_BACKEND", "groq").lower()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

# Modelli LLM (Testo)
MODEL_GROQ = os.getenv("MODEL_ID", "meta-llama/llama-4-maverick-17b-128e-instruct")
MODEL_OLLAMA = os.getenv("MODEL_ID", "llama3")

# Modelli Vision (Immagini)
VISION_MODEL_GROQ = "meta-llama/llama-4-scout-17b-16e-instruct" # Modello multimodale Groq
VISION_MODEL_OLLAMA = "llava"

# Chiavi & Endpoint
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# Settings Sistema
ENABLE_VOICE = os.getenv("ENABLE_VOICE", "False").lower() == "true"
HISTORY_LIMIT = 10