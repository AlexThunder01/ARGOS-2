"""
ARGOS-2 Telegram Module — Memory System (Backward Compatibility Wrapper).

All memory logic has been promoted to src.core.memory.
This module re-exports everything for backward compatibility with
existing tests, routes, and imports.
"""

# Re-export all public symbols from the Core memory module
# Re-export config values that tests depend on
from src.config import EMBEDDING_DIM
from src.core.memory import (
    EXTRACT_EVERY_N,
    EXTRACT_MIN_LENGTH,
    GC_EVERY_N,
    MEMORY_EXTRACTION_PROMPT,
    check_embedding_dimensions,
    deserialize_embedding,
    extract_memories_from_text,
    get_embedding,
    retrieve_relevant_memories,
    save_extracted_memories,
    serialize_embedding,
    should_extract_memory,
    should_run_gc,
)
from src.core.security import (
    _COMPILED_BLOCKLIST,
    PARANOID_JUDGE_PROMPT,
)

# Re-export security functions that were previously defined here
from src.core.security import compute_risk_score, validate_with_llm_judge

__all__ = [
    "get_embedding",
    "check_embedding_dimensions",
    "serialize_embedding",
    "deserialize_embedding",
    "retrieve_relevant_memories",
    "should_extract_memory",
    "should_run_gc",
    "extract_memories_from_text",
    "save_extracted_memories",
    "EXTRACT_EVERY_N",
    "EXTRACT_MIN_LENGTH",
    "GC_EVERY_N",
    "MEMORY_EXTRACTION_PROMPT",
    "PARANOID_JUDGE_PROMPT",
    "EMBEDDING_DIM",
    "_COMPILED_BLOCKLIST",
    "compute_risk_score",
    "validate_with_llm_judge",
]
