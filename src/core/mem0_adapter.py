"""
mem0 adapter for Argos memory system.

Wraps mem0's Memory class to expose a simple add/search/get_all interface,
backed by the configured vector store (pgvector or qdrant).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("argos")


def _build_mem0():
    """Initialize and return a mem0 Memory instance with Argos config."""
    from mem0 import Memory

    from src.config import (
        EMBEDDING_API_KEY,
        EMBEDDING_BASE_URL,
        EMBEDDING_MODEL,
        LLM_API_KEY,
        LLM_BASE_URL,
        LLM_MODEL,
    )

    config = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": LLM_MODEL,
                "api_key": LLM_API_KEY or "dummy",
                "openai_base_url": LLM_BASE_URL,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": EMBEDDING_MODEL,
                "api_key": EMBEDDING_API_KEY or LLM_API_KEY or "dummy",
                "openai_base_url": EMBEDDING_BASE_URL,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "argos_memories",
                "embedding_model_dims": 768,
            },
        },
    }

    import os

    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith("postgresql"):
        config["vector_store"] = {
            "provider": "pgvector",
            "config": {
                "connection_string": database_url,
                "collection_name": "argos_memories",
                "embedding_model_dims": int(os.getenv("EMBEDDING_DIM", "768")),
            },
        }

    return Memory.from_config(config)


class ArgosMemory:
    """
    Thin wrapper over mem0 Memory.

    All operations are synchronous (mem0 handles async internally).
    Callers in CoreAgent use asyncio.to_thread() to avoid blocking.
    """

    def __init__(self, user_id: int):
        self._user_id = str(user_id)
        self._mem0 = _build_mem0()

    def add(self, text: str) -> None:
        """Store a new memory fact. mem0 handles entity extraction and deduplication."""
        if not text or not text.strip():
            return
        try:
            self._mem0.add(text, user_id=self._user_id)
        except Exception as e:
            logger.warning(f"[Memory] mem0 add failed: {e}")

    def search(self, query: str, top_k: int = 5) -> list[str]:
        """Return top_k memory strings most relevant to query."""
        if not query or not query.strip():
            return []
        try:
            result = self._mem0.search(query, user_id=self._user_id, limit=top_k)
            return [r["memory"] for r in result.get("results", [])]
        except Exception as e:
            logger.warning(f"[Memory] mem0 search failed: {e}")
            return []

    def get_all(self) -> list[str]:
        """Return all stored memory strings for this user."""
        try:
            result = self._mem0.get_all(user_id=self._user_id)
            return [r["memory"] for r in result.get("results", [])]
        except Exception as e:
            logger.warning(f"[Memory] mem0 get_all failed: {e}")
            return []
