"""
ARGOS-2 Telegram Module — Memory System (Backward Compatibility Wrapper).

All memory logic has been promoted to src.core.memory.
This module re-exports everything for backward compatibility with
existing tests, routes, and imports.

Memory extraction and GC are now delegated to the mem0 adapter.
"""

# Re-export all public symbols from the Core memory module
# Re-export config values that tests depend on
from src.config import EMBEDDING_DIM
from src.core.memory import (
    check_embedding_dimensions,
    deserialize_embedding,
    get_embedding,
    retrieve_relevant_memories,
    save_extracted_memories,
    serialize_embedding,
)

# Re-export security functions that were previously defined here
from src.core.security import (
    _COMPILED_BLOCKLIST,
    PARANOID_JUDGE_PROMPT,
    compute_risk_score,
    validate_with_llm_judge,
)

__all__ = [
    "get_embedding",
    "check_embedding_dimensions",
    "serialize_embedding",
    "deserialize_embedding",
    "retrieve_relevant_memories",
    "save_extracted_memories",
    "PARANOID_JUDGE_PROMPT",
    "EMBEDDING_DIM",
    "_COMPILED_BLOCKLIST",
    "compute_risk_score",
    "validate_with_llm_judge",
]
