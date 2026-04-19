"""
ARGOS-2 Core — RAG Memory System.

Interface-agnostic memory layer: embedding generation, cosine similarity
search, and anti-poisoning.

Promoted from src/telegram/memory.py to be usable by both CLI and API.
Memory extraction and garbage collection are now delegated to the mem0 adapter.
"""

import logging

import numpy as np
import requests

from src.config import (
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
)
from src.core.security import compute_risk_score, validate_with_llm_judge

logger = logging.getLogger("argos")


# ==========================================================================
# Embedding Generation & Serialization
# ==========================================================================


def get_embedding(text: str) -> np.ndarray:
    """Calls configured embeddings API and returns a numpy float32 vector.

    Raises RuntimeError if the service is unreachable, so callers can catch
    and degrade gracefully instead of propagating a raw connection error.
    """
    headers = {"Content-Type": "application/json"}
    if EMBEDDING_API_KEY:
        headers["Authorization"] = f"Bearer {EMBEDDING_API_KEY}"

    url = f"{EMBEDDING_BASE_URL.rstrip('/')}/embeddings"
    try:
        response = requests.post(
            url,
            headers=headers,
            json={"model": EMBEDDING_MODEL, "input": text},
            timeout=10,
        )
        response.raise_for_status()
        vec = response.json()["data"][0]["embedding"]
        return np.array(vec, dtype=np.float32)
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Embedding service unreachable at {EMBEDDING_BASE_URL}: {e}") from e
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Embedding service timed out at {EMBEDDING_BASE_URL}") from None


def check_embedding_dimensions():
    """Boot-time dimension check to prevent DB incompatibility when switching models."""
    from src.db.repository import db_get_one_memory_blob

    blob = db_get_one_memory_blob()
    if blob is not None:
        if not isinstance(blob, bytes) or len(blob) < 4:
            raise RuntimeError(
                f"Invalid embedding blob in database: expected bytes, got {type(blob).__name__}. "
                f"Database may be corrupted."
            )
        stored_dim = len(blob) // 4  # float32 is 4 bytes
        if stored_dim != EMBEDDING_DIM:
            raise RuntimeError(
                f"Embedding dimension mismatch: DB contains {stored_dim}-dim vectors "
                f"but current backend configured for {EMBEDDING_DIM}-dim. "
                f"Run scripts/migrate_embeddings.py to re-embed your memories."
            )


def serialize_embedding(vec: np.ndarray) -> bytes:
    """Serializes a numpy vector as a BLOB for SQLite storage."""
    return vec.tobytes()


def deserialize_embedding(blob: bytes) -> np.ndarray:
    """Deserializes a SQLite BLOB back into a numpy vector."""
    return np.frombuffer(blob, dtype=np.float32)


# ==========================================================================
# RAG: Cosine Similarity Search
# ==========================================================================


def retrieve_relevant_memories(
    user_id: int, query_text: str, top_k: int = 3, min_similarity: float = 0.25
) -> list[dict]:
    """
    Retrieves the top_k most relevant memories for query_text.

    - PostgreSQL: Uses pgvector HNSW index with <=> cosine operator (O(log n)).
    - SQLite: Falls back to Python numpy cosine similarity scan (O(n)).
    """
    from src.db.connection import DB_BACKEND

    try:
        query_vec = get_embedding(query_text)
    except Exception as e:
        logger.error(f"[Memory] Embedding generation failed: {e}")
        return []

    # --- PostgreSQL: Native pgvector search ---
    if DB_BACKEND == "postgres":
        from src.db.repository import db_vector_search

        return db_vector_search(user_id, query_vec.tolist(), top_k, min_similarity)

    # --- SQLite: Python numpy fallback ---
    from src.db.repository import db_get_all_memory_blobs, db_update_memory_access

    rows = db_get_all_memory_blobs(user_id)
    if not rows:
        return []

    results = []
    for row_id, content, blob, category, confidence in rows:
        stored_vec = deserialize_embedding(blob)
        # Cosine similarity
        dot = float(np.dot(query_vec, stored_vec))
        norm = float(np.linalg.norm(query_vec) * np.linalg.norm(stored_vec) + 1e-8)
        similarity = dot / norm

        if similarity >= min_similarity:
            results.append(
                {
                    "id": row_id,
                    "content": content,
                    "category": category,
                    "similarity": round(similarity, 4),
                    "confidence": confidence,
                }
            )

    results.sort(key=lambda x: x["similarity"], reverse=True)
    top_results = results[:top_k]

    if len(top_results) < top_k:
        logger.debug(
            f"[Memory] Requested {top_k} results but found only {len(top_results)} "
            f"above similarity threshold {min_similarity}"
        )

    if top_results:
        db_update_memory_access([r["id"] for r in top_results])

    return top_results


# ==========================================================================
# Save with Anti-Poisoning Pipeline
# ==========================================================================


def save_extracted_memories(
    user_id: int,
    facts: list[dict],
    llm_call_fn=None,
    poisoning_enabled: bool = True,
    risk_threshold: float = 0.5,
    suspicious_retention: int = 500,
):
    """
    Validates and saves extracted facts to the memory vector store.
    Runs the 4-layer anti-poisoning pipeline when enabled.
    Uses the centralized security module from src.core.security.
    """
    from src.db.repository import (
        db_insert_memory,
        db_log_suspicious_memory,
        db_prune_suspicious,
    )

    for fact in facts:
        content = fact.get("content", "")
        category = fact.get("category", "general")

        # --- Layer 1: Intercept POISONING_ATTEMPT_DETECTED marker ---
        if content == "POISONING_ATTEMPT_DETECTED":
            logger.warning(f"[AntiPoison] Extraction LLM flagged poisoning for user {user_id}")
            db_log_suspicious_memory(user_id, content, category, 1.0, "extraction_marker")
            continue

        if poisoning_enabled:
            # --- Layer 2: Risk scoring (delegated to core.security) ---
            risk = compute_risk_score(content)

            # NEW: Auto-reject extremely high risk content (no LLM judge needed)
            if risk >= 0.8:
                logger.warning(f"[AntiPoison] BLOCKED (high risk={risk:.2f}): {content[:80]}...")
                db_log_suspicious_memory(user_id, content, category, risk, "risk_score_high")
                continue

            if risk >= risk_threshold:
                logger.warning(f"[AntiPoison] BLOCKED (score={risk:.2f}): {content[:80]}...")
                db_log_suspicious_memory(user_id, content, category, risk, "risk_score")
                continue

            # --- Layer 3: Paranoid LLM Judge (delegated to core.security) ---
            if risk >= 0.2 and llm_call_fn:
                if not validate_with_llm_judge(content, llm_call_fn):
                    logger.warning(
                        f"[AntiPoison] BLOCKED by LLM judge (score={risk:.2f}): {content[:80]}..."
                    )
                    db_log_suspicious_memory(user_id, content, category, risk, "llm_judge")
                    continue
            elif risk >= 0.2 and not llm_call_fn:
                # NEW: Log warning if LLM judge unavailable for medium-risk content
                logger.warning(
                    f"[AntiPoison] LLM judge unavailable for medium-risk content (score={risk:.2f})"
                )
                db_log_suspicious_memory(user_id, content, category, risk, "llm_judge_unavailable")
                continue  # Fail-safe: reject uncertain content

        # --- All checks passed: save the memory ---
        try:
            if category not in ("preference", "fact", "interest", "skill"):
                category = "general"
            vec = get_embedding(content)
            # pgvector accepts list[float], SQLite needs bytes blob
            from src.db.connection import DB_BACKEND

            if DB_BACKEND == "postgres":
                db_insert_memory(user_id, content, vec.tolist(), category)
            else:
                blob = serialize_embedding(vec)
                db_insert_memory(user_id, content, blob, category)
            logger.debug(f"[Memory] Saved [{category}]: {content[:60]}...")
        except Exception as e:
            logger.warning(f"[Memory] Failed to save memory: {e}")

    # Prune suspicious log if over retention cap
    db_prune_suspicious(suspicious_retention)
