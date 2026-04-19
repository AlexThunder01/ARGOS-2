"""
ArgosSettings — single source of truth for all Argos configuration.

Reads from environment variables and .env file.
src/config.py re-exports from here for backward compatibility.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ArgosSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM (Text & Reasoning) ---
    llm_backend: str = Field(default="openai-compatible")
    llm_base_url: str = Field(default="https://api.groq.com/openai/v1")
    llm_api_key: str = Field(default="")
    llm_api_key_2: str = Field(default="")
    llm_model: str = Field(default="llama-3.3-70b-versatile")
    llm_lightweight_model: str = Field(default="llama-3.1-8b-instant")

    # --- Vision LLM ---
    vision_base_url: str | None = Field(default=None)
    vision_api_key: str | None = Field(default=None)
    vision_model: str = Field(default="meta-llama/llama-4-scout-17b-16e-instruct")

    # --- Embeddings (RAG) ---
    embedding_base_url: str = Field(default="https://api.groq.com/openai/v1")
    embedding_api_key: str = Field(default="")
    embedding_model: str = Field(default="nomic-embed-text-v1.5")
    embedding_dim: int = Field(default=768)

    # --- STT (Speech-to-Text) ---
    stt_backend: str = Field(default="groq")
    stt_custom_url: str = Field(default="")
    stt_custom_api_key: str = Field(default="")

    # --- Features ---
    enable_voice: bool = Field(default=False)
    history_limit: int = Field(default=10)

    # --- Rate Limiting ---
    rate_limit_per_hour: int = Field(default=50)
    rate_limit_per_minute: int = Field(default=5)

    # --- Timeouts (seconds) ---
    webhook_timeout_seconds: int = Field(default=10)
    llm_health_check_timeout: int = Field(default=3)
    n8n_check_timeout: int = Field(default=3)

    # --- Circuit Breaker (Resilience) ---
    circuit_breaker_failure_threshold: int = Field(default=5)
    circuit_breaker_timeout_seconds: int = Field(default=60)

    # --- Observability & Tool Control ---
    tool_rag_top_k: int = Field(default=12)
    cost_per_token: float = Field(default=0.0)
    tool_timeout_seconds: int = Field(default=30)

    # --- Isolation Workspace (Fase 8) ---
    docker_host: str = Field(default="tcp://localhost:2375")
    workspace_dir: str = Field(default="./workspace")
    host_workspace_dir: str | None = Field(default=None)
    docker_exec_mem_limit: str = Field(default="128m")
    docker_exec_timeout: int = Field(default=30)
    scraper_timeout: int = Field(default=15)

    # --- Upload settings ---
    upload_max_bytes: int = Field(default=20 * 1024 * 1024)  # 20 MB default
    upload_max_files: int = Field(default=5)
    upload_ttl_hours: int = Field(default=24)

    # --- n8n Integration ---
    n8n_base_url: str = Field(default="")

    # --- Security & Observability (Phase 4) ---
    argos_paranoid_mode: bool = Field(default=False)
    argos_permission_audit: str = Field(default="logs/argos_permissions.jsonl")
    otel_exporter_otlp_endpoint: str = Field(default="")


@lru_cache(maxsize=1)
def get_settings() -> ArgosSettings:
    """Returns the singleton settings instance (cached after first call)."""
    return ArgosSettings()
