#!/usr/bin/env python3
"""
ARGOS-2 Memory Embeddings Migration Script

This script re-embeds all existing memories in the SQLite database to match
a new embedding provider or model. It reads all memories, generates new vectors
using the specified (or default configured) API, and updates the database.

Usage:
    python3 scripts/migrate_embeddings.py \
        --from-url https://api.groq.com/openai/v1 \
        --to-url http://localhost:11434/v1 \
        --model nomic-embed-text
"""

import sys
import os
import argparse
import requests
import numpy as np

# Ensure we can import from src
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.connection import get_connection

def serialize_embedding(vec: np.ndarray) -> bytes:
    return vec.tobytes()

def generate_embedding(url: str, api_key: str, model: str, text: str) -> bytes:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        
    endpoint = f"{url.rstrip('/')}/embeddings"
    response = requests.post(
        endpoint,
        headers=headers,
        json={"model": model, "input": text},
        timeout=30
    )
    response.raise_for_status()
    vec = response.json()["data"][0]["embedding"]
    return serialize_embedding(np.array(vec, dtype=np.float32))

def migrate(to_url: str, model: str, api_key: str):
    conn = get_connection()
    # Fetch all memory blobs
    print(f"[*] Fetching memories from DB to migrate...")
    rows = conn.execute("SELECT id, content FROM tg_memory_vectors").fetchall()
    total = len(rows)
    print(f"[*] Found {total} memories.")

    if total == 0:
        print("[*] No memories to migrate.")
        return

    print(f"[*] Re-embedding {total} memories using {to_url} (model: {model})...")
    
    success = 0
    errors = 0
    for i, row in enumerate(rows, 1):
        mem_id = row["id"]
        content = row["content"]
        try:
            new_blob = generate_embedding(to_url, api_key, model, content)
            conn.execute("UPDATE tg_memory_vectors SET embedding = ? WHERE id = ?", (new_blob, mem_id))
            success += 1
            if i % 10 == 0:
                print(f"    progress: {i}/{total}")
        except Exception as e:
            errors += 1
            print(f"[!] Error migrating memory {mem_id}: {e}")
            
    conn.commit()
    print(f"\n[*] Migration complete. {success} succeeded, {errors} failed.")

if __name__ == "__main__":
    from src.config import EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_API_KEY
    
    parser = argparse.ArgumentParser(description="Migrate ARGOS-2 Memory Embeddings")
    parser.add_argument("--from-url", help="Old embedding URL (informational only)", default="")
    parser.add_argument("--to-url", help="New embedding URL", default=EMBEDDING_BASE_URL)
    parser.add_argument("--model", help="New embedding model", default=EMBEDDING_MODEL)
    parser.add_argument("--api-key", help="API key for the new provider", default=EMBEDDING_API_KEY)
    
    args = parser.parse_args()
    
    print(f"=== ARGOS-2 Memory Migration ===")
    if args.from_url:
        print(f"From: {args.from_url}")
    print(f"To:   {args.to_url}")
    print(f"Model:{args.model}\n")
    
    migrate(args.to_url, args.model, args.api_key)
