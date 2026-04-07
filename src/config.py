"""
Infrastructure & secrets configuration — loaded from .env / environment variables.

BOUNDARY: this module owns anything that cannot change at runtime without a restart:
API keys, DB connection strings, model names, resource limits, feature flags.
Behavioral settings that operators adjust without restarting the server (tone of voice,
conversation window, auto-approve, etc.) live in workflows_config.py (YAML, hot-reload).
"""

import os

from dotenv import load_dotenv

# Carica il file .env dalla root del progetto
load_dotenv()

# --- Base LLM (Text & Reasoning) ---
LLM_BACKEND = os.getenv("LLM_BACKEND", "openai-compatible").lower()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_KEY_2 = os.getenv("LLM_API_KEY_2", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
LLM_LIGHTWEIGHT_MODEL = os.getenv("LLM_LIGHTWEIGHT_MODEL", "llama-3.1-8b-instant")

# --- Vision LLM ---
VISION_BASE_URL = os.getenv("VISION_BASE_URL", LLM_BASE_URL)
VISION_API_KEY = os.getenv("VISION_API_KEY", LLM_API_KEY)
VISION_MODEL = os.getenv("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# --- Embeddings (RAG) ---
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.groq.com/openai/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text-v1.5")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

# --- STT (Speech-to-Text) ---
STT_BACKEND = os.getenv("STT_BACKEND", "groq").lower()
STT_CUSTOM_URL = os.getenv("STT_CUSTOM_URL", "")
STT_CUSTOM_API_KEY = os.getenv("STT_CUSTOM_API_KEY", "")

# Settings Sistema
ENABLE_VOICE = os.getenv("ENABLE_VOICE", "False").lower() == "true"
HISTORY_LIMIT = 10

# Rate Limiting
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "50"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "5"))

# Isolation Workspace (Fase 8)
DOCKER_HOST = os.getenv("DOCKER_HOST", "tcp://localhost:2375")
HOST_WORKSPACE_DIR = os.getenv("HOST_WORKSPACE_DIR", "")
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "./workspace")
DOCKER_EXEC_MEM_LIMIT = os.getenv("DOCKER_EXEC_MEM_LIMIT", "128m")
os.makedirs(WORKSPACE_DIR, exist_ok=True)
