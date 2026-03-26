import os
from dotenv import load_dotenv

# Carica il file .env dalla root del progetto
load_dotenv()

# Backend (groq o ollama)
LLM_BACKEND = os.getenv("LLM_BACKEND", "groq").lower()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

# Modelli LLM (Testo) — Production
MODEL_GROQ = os.getenv("GROQ_MODEL_ID", "llama-3.3-70b-versatile")
MODEL_OLLAMA = os.getenv("OLLAMA_MODEL_ID", "llama3")

# Modelli Vision (Immagini) — Preview (unico multimodale su Groq)
VISION_MODEL_GROQ = "meta-llama/llama-4-scout-17b-16e-instruct"
VISION_MODEL_OLLAMA = "llava"

# Chiavi & Endpoint
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEY2 = os.getenv("GROQ_API_KEY2", "")
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# Settings Sistema
ENABLE_VOICE = os.getenv("ENABLE_VOICE", "False").lower() == "true"
HISTORY_LIMIT = 10