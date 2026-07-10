"""
Test dell'IntentParser — verifica il parsing deterministico dei comandi vocali.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.voice.intent import format_confirmation_prompt, parse_intent


def test_intent_web_search():
    intent = parse_intent("cerca il meteo a Roma")
    assert intent.action == "web_search"
    assert "meteo" in intent.params.get("query", "").lower()


def test_intent_web_search_with_suffix():
    intent = parse_intent("cerca intelligenza artificiale su internet")
    assert intent.action == "web_search"
    assert "intelligenza artificiale" in intent.params["query"]


def test_intent_launch_app_firefox():
    intent = parse_intent("apri firefox")
    assert intent.action == "launch_app"
    assert intent.params["app_name"] == "firefox"


def test_intent_launch_app_generic():
    intent = parse_intent("apri terminale")
    assert intent.action == "launch_app"
    assert "terminale" in intent.params["app_name"]


def test_intent_create_file():
    intent = parse_intent("crea un file chiamato test.txt")
    assert intent.action == "create_file"
    assert intent.params["filename"] == "test.txt"


def test_intent_delete_file():
    intent = parse_intent("elimina il file vecchio.log")
    assert intent.action == "delete_file"
    assert intent.needs_confirmation is True


def test_intent_list_files():
    intent = parse_intent("mostrami i file")
    assert intent.action == "list_files"


def test_intent_system_stats():
    intent = parse_intent("stato del sistema")
    assert intent.action == "system_stats"


def test_intent_crypto():
    intent = parse_intent("prezzo di bitcoin")
    assert intent.action == "crypto_price"
    assert intent.params["coin"] == "bitcoin"


def test_intent_describe_screen():
    intent = parse_intent("cosa vedi")
    assert intent.action == "describe_screen"


def test_intent_click():
    intent = parse_intent("clicca sul pulsante invio")
    assert intent.action == "visual_click"
    assert intent.needs_confirmation is True


def test_intent_type():
    intent = parse_intent("scrivi ciao mondo")
    assert intent.action == "keyboard_type"
    assert intent.params["text"] == "ciao mondo"


def test_intent_unknown_fallback():
    intent = parse_intent("qual è il senso della vita?")
    assert intent.action == "ask_llm"
    assert intent.ambiguous is True
    assert intent.confidence < 0.7


def test_intent_empty():
    intent = parse_intent("")
    assert intent.action == "none"
    assert intent.confidence == 0.0


def test_confirmation_prompt():
    intent = parse_intent("elimina il file test.txt")
    prompt = format_confirmation_prompt(intent)
    assert "eliminare" in prompt.lower()
