"""
ARGOS-2 DB Repository — Interface-agnostic re-export layer.

Memory-related DB functions live in src/telegram/db.py for historical reasons.
This module provides a stable import surface for src/core so that core modules
do not depend directly on the telegram package.

All symbols here are thin re-exports; the implementation stays in telegram.db.
"""

from src.telegram.db import (
    db_get_all_memory_blobs,
    db_get_one_memory_blob,
    db_insert_memory,
    db_log_suspicious_memory,
    db_prune_suspicious,
    db_update_memory_access,
    db_vector_search,
)

__all__ = [
    "db_get_one_memory_blob",
    "db_vector_search",
    "db_get_all_memory_blobs",
    "db_update_memory_access",
    "db_insert_memory",
    "db_log_suspicious_memory",
    "db_prune_suspicious",
]
