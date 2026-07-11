"""
Tests for src.core.chats — CLI/Dashboard shared multi-chat registry.
"""

from unittest.mock import patch

from src.db.migrations import run_migrations


class TestChats:
    def test_save_message_and_get_messages_roundtrip(self, patch_db):
        run_migrations(patch_db)
        from src.core.chats import create_chat, get_messages, save_message

        chat_id = create_chat()
        save_message(chat_id, "user", "ciao")
        save_message(chat_id, "agent", "ciao a te")

        messages = get_messages(chat_id)
        assert [m["role"] for m in messages] == ["user", "agent"]
        assert [m["content"] for m in messages] == ["ciao", "ciao a te"]

    def test_get_messages_empty_for_chat_with_no_turns(self, patch_db):
        run_migrations(patch_db)
        from src.core.chats import create_chat, get_messages

        chat_id = create_chat()
        assert get_messages(chat_id) == []

    def test_list_chats_includes_title_none_by_default(self, patch_db):
        run_migrations(patch_db)
        from src.core.chats import create_chat, list_chats

        chat_id = create_chat()
        found = next(c for c in list_chats() if c["id"] == chat_id)
        assert found["title"] is None

    def test_get_chat_returns_none_for_missing_id(self, patch_db):
        run_migrations(patch_db)
        from src.core.chats import get_chat

        assert get_chat(999999) is None

    def test_get_chat_returns_row_for_existing_id(self, patch_db):
        run_migrations(patch_db)
        from src.core.chats import create_chat, get_chat

        chat_id = create_chat()
        chat = get_chat(chat_id)
        assert chat["id"] == chat_id
        assert chat["title"] is None

    def test_generate_title_if_needed_sets_title(self, patch_db):
        run_migrations(patch_db)
        from src.core.chats import create_chat, generate_title_if_needed, get_chat

        chat_id = create_chat()
        with patch("src.core.chats._generate_title", return_value="Meteo a Milano"):
            generate_title_if_needed(chat_id, "che tempo fa a Milano?")

        assert get_chat(chat_id)["title"] == "Meteo a Milano"

    def test_generate_title_if_needed_does_not_overwrite_existing_title(self, patch_db):
        run_migrations(patch_db)
        from src.core.chats import create_chat, generate_title_if_needed, get_chat

        chat_id = create_chat()
        with patch("src.core.chats._generate_title", return_value="Primo titolo"):
            generate_title_if_needed(chat_id, "primo messaggio")
        with patch("src.core.chats._generate_title", return_value="Secondo titolo"):
            generate_title_if_needed(chat_id, "un altro messaggio")

        assert get_chat(chat_id)["title"] == "Primo titolo"

    def test_generate_title_if_needed_swallows_llm_failure(self, patch_db):
        run_migrations(patch_db)
        from src.core.chats import create_chat, generate_title_if_needed, get_chat

        chat_id = create_chat()
        with patch("src.core.chats._generate_title", side_effect=RuntimeError("LLM down")):
            generate_title_if_needed(chat_id, "ciao")  # must not raise

        assert get_chat(chat_id)["title"] is None
