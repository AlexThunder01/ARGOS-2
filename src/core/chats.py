"""
Argos Chats — CLI `--memory` multi-chat registry.

Each chat is an isolated persistent-memory bucket: its numeric id is used as
the user_id passed to CoreAgent/mem0, so separate named conversations never
mix each other's facts (a single $USER-derived id shared across every
--memory invocation used to conflate them).
"""

from src.db.connection import DB_BACKEND
from src.db.repository import _db, _now_expr


def create_chat() -> int:
    """Creates a new chat and returns its id."""
    with _db() as db:
        if DB_BACKEND == "postgres":
            cur = db.execute("INSERT INTO argos_chats DEFAULT VALUES RETURNING id")
            chat_id = cur.fetchone()["id"]
        else:
            cur = db.execute("INSERT INTO argos_chats DEFAULT VALUES")
            chat_id = cur.lastrowid
        db.commit()
        return chat_id


def chat_exists(chat_id: int) -> bool:
    """Returns True if a chat with this id exists."""
    with _db() as db:
        cur = db.execute("SELECT 1 FROM argos_chats WHERE id = ?", (chat_id,))
        return cur.fetchone() is not None


def touch_chat(chat_id: int) -> None:
    """Updates last_used_at for a chat. Call when resuming it."""
    with _db() as db:
        db.execute(f"UPDATE argos_chats SET last_used_at = {_now_expr()} WHERE id = ?", (chat_id,))
        db.commit()


def list_chats() -> list[dict]:
    """Returns all chats, most recently used first."""
    with _db() as db:
        cur = db.execute(
            "SELECT id, created_at, last_used_at FROM argos_chats ORDER BY last_used_at DESC"
        )
        return [dict(row) for row in cur.fetchall()]
