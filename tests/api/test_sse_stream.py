"""
Integration test per l'endpoint POST /api/chat/stream (Server-Sent Events).

Usa TestClient (in-process, nessun server reale) con il DB in-memory
già configurato dal conftest.py locale.

Coverage:
  - Stream termina sempre con "data: [DONE]" — anche su errore LLM
  - Ogni chunk intermedio è JSON valido {"chunk": "..."}
  - Concatenando tutti i chunk si ottiene la risposta completa
  - Rate limit superato → 429 prima ancora dello stream
  - POST senza campo 'task' obbligatorio → 422
  - Risposta dell'agente vuota → stream chiuso pulitamente con [DONE]
  - Eccezione non gestita in _run_agent → chunk [ERRORE] + [DONE]
  - messaggi già salvati per un chat_id vengono ricaricati e passati all'agente come history
  - max_steps rispettato (non esplode con valori al limite: 1 e 20)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.server import app
from src.core.engine import TaskResult

# TestClient colleziona l'intero stream SSE in memoria — nessun server reale.
client = TestClient(app, raise_server_exceptions=False)


# ==========================================================================
# Helpers
# ==========================================================================


def _task_result(response: str = "Risposta di test.", success: bool = True) -> TaskResult:
    return TaskResult(
        success=success,
        task="test",
        response=response,
        steps_executed=0,
        history=[],
        memories_used=0,
    )


def _collect_sse(response) -> tuple[list[str], list[dict]]:
    """
    Parsa il body SSE e ritorna:
      - raw_lines: tutte le righe "data: ..." grezze
      - chunks: lista dei payload JSON deserializzati (esclude [DONE])
    """
    raw_lines = []
    chunks = []
    for line in response.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        raw_lines.append(payload)
        if payload == "[DONE]":
            continue
        try:
            chunks.append(json.loads(payload))
        except json.JSONDecodeError:
            pass
    return raw_lines, chunks


def _post_stream(task: str = "test task", chat_id: int | None = None, max_steps: int = 5):
    from src.core.chats import create_chat

    if chat_id is None:
        chat_id = create_chat()
    body = {"task": task, "chat_id": chat_id, "max_steps": max_steps}
    return client.post("/api/chat/stream", json=body)


# ==========================================================================
# Terminazione stream con [DONE]
# ==========================================================================


class TestSseStreamTermination:
    def test_stream_ends_with_done_on_success(self):
        """Su risposta normale, l'ultimo marker deve essere [DONE]."""
        with patch("src.core.engine.CoreAgent.run_task", return_value=_task_result("Ciao!")):
            r = _post_stream()

        assert r.status_code == 200
        raw_lines, _ = _collect_sse(r)
        assert "[DONE]" in raw_lines, "Marker [DONE] assente nello stream"
        assert raw_lines[-1] == "[DONE]", "[DONE] non è l'ultimo marker"

    def test_stream_ends_with_done_on_llm_exception(self):
        """Anche se _run_agent lancia un'eccezione, [DONE] deve essere emesso."""
        with patch(
            "src.core.engine.CoreAgent.run_task",
            side_effect=RuntimeError("LLM completamente down"),
        ):
            r = _post_stream()

        assert r.status_code == 200
        raw_lines, _ = _collect_sse(r)
        assert "[DONE]" in raw_lines, "[DONE] assente anche su eccezione"

    def test_stream_ends_with_done_on_empty_response(self):
        """Risposta dell'agente vuota ("") → stream chiude con [DONE]."""
        with patch("src.core.engine.CoreAgent.run_task", return_value=_task_result("")):
            r = _post_stream()

        raw_lines, _ = _collect_sse(r)
        assert "[DONE]" in raw_lines


# ==========================================================================
# Formato dei chunk
# ==========================================================================


class TestSseChunkFormat:
    def test_all_chunks_are_valid_json(self):
        """Ogni chunk intermedio (non [DONE]) deve essere JSON valido."""
        with patch(
            "src.core.engine.CoreAgent.run_task",
            return_value=_task_result("Una bella risposta."),
        ):
            r = _post_stream()

        raw_lines, chunks = _collect_sse(r)
        # Verifica che tutte le righe non-DONE siano JSON validi con campo "chunk"
        non_done = [line for line in raw_lines if line != "[DONE]"]
        assert len(non_done) > 0

        for line in non_done:
            parsed = json.loads(line)  # lancia JSONDecodeError se invalido
            assert "chunk" in parsed, f"Campo 'chunk' assente in: {line}"
            assert isinstance(parsed["chunk"], str)

    def test_chunks_assemble_full_response(self):
        """Concatenando tutti i chunk si ottiene la risposta completa.

        Nessun chunk di stato "[Pensando...]" deve essere iniettato: il frontend
        mostra già un proprio indicatore "Processing..." mentre lo stream è
        aperto (isTyping), quindi un chunk del genere finirebbe concatenato nel
        contenuto reale del messaggio invece di restare un indicatore separato.
        """
        risposta = "Questa è la risposta completa dell'agente."
        with patch("src.core.engine.CoreAgent.run_task", return_value=_task_result(risposta)):
            r = _post_stream()

        _, chunks = _collect_sse(r)
        assert not any("Pensando" in c["chunk"] for c in chunks), (
            "Chunk di stato leaked nel contenuto del messaggio"
        )
        full = "".join(c["chunk"] for c in chunks).strip()
        assert full == risposta

    def test_error_chunk_injected_on_exception(self):
        """Su eccezione del loop, deve essere iniettato un chunk [ERRORE]."""
        with patch(
            "src.core.engine.CoreAgent.run_task",
            side_effect=Exception("errore simulato"),
        ):
            r = _post_stream()

        _, chunks = _collect_sse(r)
        all_text = " ".join(c["chunk"] for c in chunks)
        assert "[ERRORE]" in all_text or "errore" in all_text.lower()


# ==========================================================================
# Validazione input HTTP
# ==========================================================================


class TestSseHttpValidation:
    def test_missing_task_returns_422(self):
        """Manca il campo obbligatorio 'task' → 422 Unprocessable Entity."""
        r = client.post("/api/chat/stream", json={"max_steps": 5})
        assert r.status_code == 422

    def test_empty_task_accepted(self):
        """task='' è una stringa valida → 200 (la validazione semantica è dell'agente)."""
        with patch("src.core.engine.CoreAgent.run_task", return_value=_task_result("")):
            r = _post_stream(task="")
        assert r.status_code == 200

    def test_rate_limit_returns_429(self):
        """Rate limit superato → 429 prima dell'avvio dello stream."""
        from src.core.rate_limit import RateLimitExceeded

        with patch(
            "src.core.rate_limit.check_rate_limit",
            side_effect=RateLimitExceeded("Rate limit exceeded"),
        ):
            r = _post_stream()

        assert r.status_code == 429


# ==========================================================================
# Contesto storia iniettata (multi-turn)
# ==========================================================================


class TestSseInjectedHistory:
    def test_history_loaded_from_db_and_passed_to_agent(self):
        """I messaggi già salvati per questo chat_id devono essere passati all'agente
        come _injected_history — prima del turno corrente, non duplicati."""
        from src.core.chats import create_chat, save_message

        captured_history = []

        def capture_run_task(self_agent, task):
            captured_history.extend(self_agent._injected_history)
            return _task_result("ok")

        chat_id = create_chat()
        save_message(chat_id, "user", "primo messaggio")
        save_message(chat_id, "agent", "prima risposta")

        with patch("src.core.engine.CoreAgent.run_task", capture_run_task):
            _post_stream(task="nuovo task", chat_id=chat_id)

        assert len(captured_history) == 2
        assert captured_history[0]["content"] == "primo messaggio"
        assert captured_history[1]["content"] == "prima risposta"

    def test_history_truncated_to_last_10(self):
        """La history viene troncata agli ultimi 10 messaggi prima di essere iniettata,
        e il turno corrente non deve comparire nella history iniettata."""
        from src.core.chats import create_chat, save_message

        captured_history = []

        def capture_run_task(self_agent, task):
            captured_history.extend(self_agent._injected_history)
            return _task_result("ok")

        chat_id = create_chat()
        # Salva 15 messaggi precedenti
        for i in range(15):
            save_message(chat_id, "user", f"msg {i}")

        with patch("src.core.engine.CoreAgent.run_task", capture_run_task):
            _post_stream(task="task corrente", chat_id=chat_id)

        assert len(captured_history) == 10
        # Devono esserci gli ultimi 10 PRECEDENTI (non il turno corrente appena inviato)
        assert captured_history[-1]["content"] == "msg 14"

    def test_no_prior_messages_sends_empty_list(self):
        """Se non ci sono messaggi precedenti per questo chat_id, _injected_history deve essere []."""
        captured = []

        def capture_run_task(self_agent, task):
            captured.append(list(self_agent._injected_history))
            return _task_result("ok")

        with patch("src.core.engine.CoreAgent.run_task", capture_run_task):
            _post_stream(task="task senza history")

        assert captured[0] == []


# ==========================================================================
# Limite max_steps
# ==========================================================================


class TestSseMaxSteps:
    @pytest.mark.parametrize("steps", [1, 10, 20])
    def test_valid_max_steps_returns_200(self, steps):
        """max_steps nei valori validi (1–20) non deve causare errori HTTP."""
        with patch("src.core.engine.CoreAgent.run_task", return_value=_task_result("ok")):
            r = _post_stream(max_steps=steps)
        assert r.status_code == 200
