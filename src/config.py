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

# --- n8n Integration ---
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "")  # e.g., "http://localhost:5678"

# --- Timeouts (seconds) ---
WEBHOOK_TIMEOUT_SECONDS = int(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "10"))
LLM_HEALTH_CHECK_TIMEOUT = int(os.getenv("LLM_HEALTH_CHECK_TIMEOUT", "3"))
N8N_CHECK_TIMEOUT = int(os.getenv("N8N_CHECK_TIMEOUT", "3"))

# --- Circuit Breaker (Resilience) ---
CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(
    os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")
)
CIRCUIT_BREAKER_TIMEOUT_SECONDS = int(
    os.getenv("CIRCUIT_BREAKER_TIMEOUT_SECONDS", "60")
)

# --- Observability & Tool Control ---
TOOL_RAG_TOP_K = int(os.getenv("ARGOS_TOOL_RAG_TOP_K", "12"))
COST_PER_TOKEN = float(os.getenv("ARGOS_COST_PER_TOKEN", "0.0"))
TOOL_TIMEOUT_SECONDS = int(os.getenv("ARGOS_TOOL_TIMEOUT_SECONDS", "30"))

# Isolation Workspace (Fase 8)
DOCKER_HOST = os.getenv("DOCKER_HOST", "tcp://localhost:2375")
WORKSPACE_DIR = os.path.abspath(os.getenv("WORKSPACE_DIR", "./workspace"))
# HOST_WORKSPACE_DIR: path on the Docker host machine that maps to /workspace inside the container.
# Falls back to WORKSPACE_DIR (absolute) so local runs without explicit config work out of the box.
HOST_WORKSPACE_DIR = os.path.abspath(os.getenv("HOST_WORKSPACE_DIR") or WORKSPACE_DIR)
DOCKER_EXEC_MEM_LIMIT = os.getenv("DOCKER_EXEC_MEM_LIMIT", "128m")
DOCKER_EXEC_TIMEOUT = int(os.getenv("DOCKER_EXEC_TIMEOUT", "30"))
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "15"))
os.makedirs(WORKSPACE_DIR, exist_ok=True)

# Upload settings
UPLOAD_MAX_BYTES: int = int(
    os.getenv("UPLOAD_MAX_BYTES", str(20 * 1024 * 1024))
)  # 20 MB default
UPLOAD_MAX_FILES: int = int(os.getenv("UPLOAD_MAX_FILES", "5"))
UPLOAD_TTL_HOURS: int = int(os.getenv("UPLOAD_TTL_HOURS", "24"))
