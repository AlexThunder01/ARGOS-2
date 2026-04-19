"""
Backward-compatibility shim.

All config values are now defined in src/settings.py (ArgosSettings).
This module re-exports them so existing imports don't break.
"""

import os

from src.settings import get_settings as _gs

_s = _gs()

# --- Base LLM (Text & Reasoning) ---
LLM_BACKEND = _s.llm_backend
LLM_BASE_URL = _s.llm_base_url
LLM_API_KEY = _s.llm_api_key
LLM_API_KEY_2 = _s.llm_api_key_2
LLM_MODEL = _s.llm_model
LLM_LIGHTWEIGHT_MODEL = _s.llm_lightweight_model

# --- Vision LLM ---
VISION_BASE_URL = _s.vision_base_url or _s.llm_base_url
VISION_API_KEY = _s.vision_api_key or _s.llm_api_key
VISION_MODEL = _s.vision_model

# --- Embeddings (RAG) ---
EMBEDDING_BASE_URL = _s.embedding_base_url
EMBEDDING_API_KEY = _s.embedding_api_key
EMBEDDING_MODEL = _s.embedding_model
EMBEDDING_DIM = _s.embedding_dim

# --- STT (Speech-to-Text) ---
STT_BACKEND = _s.stt_backend
STT_CUSTOM_URL = _s.stt_custom_url
STT_CUSTOM_API_KEY = _s.stt_custom_api_key

# --- Features ---
ENABLE_VOICE = _s.enable_voice
HISTORY_LIMIT = _s.history_limit

# --- Rate Limiting ---
RATE_LIMIT_PER_HOUR = _s.rate_limit_per_hour
RATE_LIMIT_PER_MINUTE = _s.rate_limit_per_minute

# --- n8n Integration ---
N8N_BASE_URL = _s.n8n_base_url

# --- Timeouts (seconds) ---
WEBHOOK_TIMEOUT_SECONDS = _s.webhook_timeout_seconds
LLM_HEALTH_CHECK_TIMEOUT = _s.llm_health_check_timeout
N8N_CHECK_TIMEOUT = _s.n8n_check_timeout

# --- Circuit Breaker (Resilience) ---
CIRCUIT_BREAKER_FAILURE_THRESHOLD = _s.circuit_breaker_failure_threshold
CIRCUIT_BREAKER_TIMEOUT_SECONDS = _s.circuit_breaker_timeout_seconds

# --- Observability & Tool Control ---
TOOL_RAG_TOP_K = _s.tool_rag_top_k
COST_PER_TOKEN = _s.cost_per_token
TOOL_TIMEOUT_SECONDS = _s.tool_timeout_seconds

# --- Isolation Workspace (Fase 8) ---
DOCKER_HOST = _s.docker_host
WORKSPACE_DIR = os.path.abspath(_s.workspace_dir)
HOST_WORKSPACE_DIR = os.path.abspath(_s.host_workspace_dir or _s.workspace_dir)
DOCKER_EXEC_MEM_LIMIT = _s.docker_exec_mem_limit
DOCKER_EXEC_TIMEOUT = _s.docker_exec_timeout
SCRAPER_TIMEOUT = _s.scraper_timeout

# --- Upload settings ---
UPLOAD_MAX_BYTES = _s.upload_max_bytes
UPLOAD_MAX_FILES = _s.upload_max_files
UPLOAD_TTL_HOURS = _s.upload_ttl_hours

# --- Security & Observability (Phase 4) ---
ARGOS_PARANOID_MODE = _s.argos_paranoid_mode
ARGOS_PERMISSION_AUDIT = _s.argos_permission_audit

# Create workspace directory if it doesn't exist
os.makedirs(WORKSPACE_DIR, exist_ok=True)
