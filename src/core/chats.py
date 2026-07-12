"""
Argos Chats — CLI/Dashboard shared multi-chat registry.

Each chat is an isolated persistent-memory bucket: its numeric id is used as
the user_id passed to CoreAgent/mem0, so separate named conversations never
mix each other's facts (a single $USER-derived id shared across every
--memory invocation used to conflate them).

CLI and Dashboard both read/write through this module — same argos_chats /
argos_chat_messages tables, same ids, so a chat started in one interface
resumes identically in the other.
"""

import logging

from src.db.connection import DB_BACKEND
from src.db.repository import _db, _now_expr

logger = logging.getLogger("argos")


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


def get_chat(chat_id: int) -> dict | None:
    """Single chat's metadata (id, title, created_at, last_used_at), or None."""
    with _db() as db:
        cur = db.execute(
            "SELECT id, title, created_at, last_used_at FROM argos_chats WHERE id = ?",
            (chat_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def touch_chat(chat_id: int) -> None:
    """Updates last_used_at for a chat. Call when resuming it."""
    with _db() as db:
        db.execute(f"UPDATE argos_chats SET last_used_at = {_now_expr()} WHERE id = ?", (chat_id,))
        db.commit()


def list_chats() -> list[dict]:
    """Returns all chats, most recently used first."""
    with _db() as db:
        cur = db.execute(
            "SELECT id, title, created_at, last_used_at FROM argos_chats ORDER BY last_used_at DESC"
        )
        return [dict(row) for row in cur.fetchall()]


def save_message(chat_id: int, role: str, content: str) -> None:
    """Appends one turn (role: 'user' | 'agent') to a chat's transcript."""
    with _db() as db:
        db.execute(
            "INSERT INTO argos_chat_messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content),
        )
        db.commit()


def get_messages(chat_id: int) -> list[dict]:
    """Full transcript of a chat, oldest first."""
    with _db() as db:
        cur = db.execute(
            "SELECT role, content, created_at FROM argos_chat_messages "
            "WHERE chat_id = ? ORDER BY id ASC",
            (chat_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def _generate_title(first_message: str) -> str:
    """Calls the lightweight model directly (no CoreAgent instance needed —
    same underlying primitive ArgosAgent.call_lightweight wraps)."""
    import asyncio

    from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_LIGHTWEIGHT_MODEL
    from src.llm.client import complete as llm_complete

    prompt = (
        "Genera un titolo brevissimo (massimo 5 parole, senza virgolette) per "
        f"una conversazione che inizia con questo messaggio:\n\n{first_message}"
    )
    response = asyncio.run(
        llm_complete(
            messages=[{"role": "user", "content": prompt}],
            model=LLM_LIGHTWEIGHT_MODEL,
            temperature=0.0,
            api_key=LLM_API_KEY or None,
            api_base=LLM_BASE_URL or None,
        )
    )
    return (response.content or "").strip()


def generate_title_if_needed(chat_id: int, first_message: str) -> None:
    """If the chat has no title yet, generates one from the first message and
    saves it. Never raises: a failed generation leaves the title NULL, to be
    retried on the next call (e.g. the next turn)."""
    chat = get_chat(chat_id)
    if chat is None or chat["title"]:
        return

    try:
        title = _generate_title(first_message)
    except Exception:
        logger.debug("generate_title_if_needed: title generation failed", exc_info=True)
        return

    if not title:
        return

    with _db() as db:
        db.execute("UPDATE argos_chats SET title = ? WHERE id = ?", (title, chat_id))
        db.commit()
