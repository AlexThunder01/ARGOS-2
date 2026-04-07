import os
import sys

# Assicuriamoci che l'import parta dalla root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.connection import get_connection, DB_BACKEND
from src.core.memory import get_embedding, serialize_embedding
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

def run():
    logger.info(f"Avvio migrazione embedding. Backend database: {DB_BACKEND}")
    
    conn = get_connection()
    raw_memories = []
    
    # 1. Carica tutte le memorie esistenti
    try:
        if DB_BACKEND == "postgres":
            cur = conn.cursor()
            cur.execute("SELECT user_id, content, category FROM tg_memory_vectors")
            rows = cur.fetchall()
            cur.close()
        else:
            cur = conn.execute("SELECT user_id, content, category FROM tg_memory_vectors")
            rows = cur.fetchall()
            
        for row in rows:
            raw_memories.append({
                "user_id": row["user_id"],
                "content": row["content"],
                "category": row["category"]
            })
        logger.info(f"Lette {len(raw_memories)} memorie dal database.")
    except Exception as e:
        logger.error(f"Impossibile leggere memorie col vecchio formato: {e}")
        return

    # 2. Modifica la struttura del database (se Postgres)
    if DB_BACKEND == "postgres":
        cur = conn.cursor()
        logger.info("Dropping table data and updating pgvector dimension to 1024...")
        cur.execute("DROP INDEX IF EXISTS idx_tg_mem_hnsw")
        cur.execute("TRUNCATE TABLE tg_memory_vectors RESTART IDENTITY CASCADE")
        cur.execute("ALTER TABLE tg_memory_vectors ALTER COLUMN embedding TYPE vector(1024)")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_tg_mem_hnsw ON tg_memory_vectors
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
        cur.close()
        conn.commit()
    else:
        logger.info("Truncating SQLite table...")
        conn.execute("DELETE FROM tg_memory_vectors")
        conn.commit()

    # 3. Ri-calcola e inserisci con il nuovo modello
    logger.info("Rigenerazione degli embeddings con bge-m3...")
    for mem in raw_memories:
        try:
            vec = get_embedding(mem["content"])
            if DB_BACKEND == "postgres":
                cur = conn.cursor()
                vec_str = "[" + ",".join(f"{v:.8f}" for v in vec.tolist()) + "]"
                cur.execute(
                    "INSERT INTO tg_memory_vectors (user_id, content, embedding, category) VALUES (%s, %s, %s::vector, %s)",
                    (mem["user_id"], mem["content"], vec_str, mem["category"])
                )
                cur.close()
            else:
                blob = serialize_embedding(vec)
                conn.execute(
                    "INSERT INTO tg_memory_vectors (user_id, content, embedding, category) VALUES (?, ?, ?, ?)",
                    (mem["user_id"], mem["content"], blob, mem["category"])
                )
        except Exception as e:
            logger.error(f"Fallito re-embedding per '{mem['content']}': {e}")
    
    conn.commit()
    logger.info("Migrazione completata con successo! Potete riavviare Argos.")

if __name__ == "__main__":
    run()
