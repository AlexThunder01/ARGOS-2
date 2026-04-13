"""
Integration test per l'endpoint POST /api/chat/stream (Server-Sent Events).

Usa TestClient (in-process, nessun server reale) con il DB in-memory
già configurato dal conftest.py locale.

Coverage:
  - Stream termina sempre con "data: [DONE]" — anche su errore LLM
  - Ogni chunk intermedio è JSON valido {"chunk": "..."}
  - Il primo chunk è sempre "[Pensando...]"
  - Concatenando tutti i chunk si ottiene la risposta completa
  - Rate limit superato → 429 prima ancora dello stream
  - POST senza campo 'task' obbligatorio → 422
  - Risposta dell'agente vuota → stream chiuso pulitamente con [DONE]
  - Eccezione non gestita in _run_agent → chunk [ERRORE] + [DONE]
  - history iniettata viene passata all'agente
  - max_steps rispettato (non esplode con valori al limite: 1 e 20)
"""

import json
import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.server import app
from src.core.engine import TaskResult

# TestClient colleziona l'intero stream SSE in memoria — nessun server reale.
client = TestClient(app, raise_server_exceptions=False)


# ==========================================================================
# Helpers
# ==========================================================================


def _task_result(
    response: str = "Risposta di test.", success: bool = True
) -> TaskResult:
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


def _post_stream(task: str = "test task", history=None, max_steps: int = 5):
    body = {"task": task, "max_steps": max_steps}
    if history is not None:
        body["history"] = history
    return client.post("/api/chat/stream", json=body)


# ==========================================================================
# Terminazione stream con [DONE]
# ==========================================================================


class TestSseStreamTermination:
    def test_stream_ends_with_done_on_success(self):
        """Su risposta normale, l'ultimo marker deve essere [DONE]."""
        with patch(
            "src.core.engine.CoreAgent.run_task", return_value=_task_result("Ciao!")
        ):
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

    def test_first_chunk_is_pensando(self):
        """Il primo chunk deve essere sempre '[Pensando...]'."""
        with patch(
            "src.core.engine.CoreAgent.run_task",
            return_value=_task_result("risposta"),
        ):
            r = _post_stream()

        _, chunks = _collect_sse(r)
        assert len(chunks) > 0
        assert "[Pensando...]" in chunks[0]["chunk"]

    def test_chunks_assemble_full_response(self):
        """Concatenando tutti i chunk (eccetto il primo '[Pensando...]') si ottiene la risposta."""
        risposta = "Questa è la risposta completa dell'agente."
        with patch(
            "src.core.engine.CoreAgent.run_task", return_value=_task_result(risposta)
        ):
            r = _post_stream()

        _, chunks = _collect_sse(r)
        # Escludi il chunk "[Pensando...]" e concatena il resto
        word_chunks = [c["chunk"] for c in chunks if "[Pensando...]" not in c["chunk"]]
        full = "".join(word_chunks).strip()
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
            r = client.post("/api/chat/stream", json={"task": ""})
        assert r.status_code == 200

    def test_rate_limit_returns_429(self):
        """Rate limit superato → 429 prima dell'avvio dello stream."""
        from src.core.rate_limit import RateLimitExceeded

        with patch(
            "src.core.rate_limit.check_rate_limit",
            side_effect=RateLimitExceeded("Rate limit exceeded"),
        ):
            r = client.post("/api/chat/stream", json={"task": "test"})

        assert r.status_code == 429


# ==========================================================================
# Contesto storia iniettata (multi-turn)
# ==========================================================================


class TestSseInjectedHistory:
    def test_history_passed_to_agent(self):
        """La history fornita dal client deve essere passata all'agente."""
        captured_history = []

        def capture_run_task(self_agent, task):
            captured_history.extend(self_agent._injected_history)
            return _task_result("ok")

        history = [
            {"role": "user", "content": "primo messaggio"},
            {"role": "assistant", "content": "prima risposta"},
        ]

        with patch("src.core.engine.CoreAgent.run_task", capture_run_task):
            _post_stream(task="nuovo task", history=history)

        assert len(captured_history) == 2
        assert captured_history[0]["content"] == "primo messaggio"
        assert captured_history[1]["content"] == "prima risposta"

    def test_history_truncated_to_last_10(self):
        """La history viene troncata agli ultimi 10 messaggi prima di essere iniettata."""
        captured_history = []

        def capture_run_task(self_agent, task):
            captured_history.extend(self_agent._injected_history)
            return _task_result("ok")

        # Invia 15 messaggi
        history = [{"role": "user", "content": f"msg {i}"} for i in range(15)]

        with patch("src.core.engine.CoreAgent.run_task", capture_run_task):
            _post_stream(task="task", history=history)

        assert len(captured_history) <= 10
        # Devono esserci gli ultimi 10
        assert captured_history[-1]["content"] == "msg 14"

    def test_no_history_sends_empty_list(self):
        """Se history non viene inviata, _injected_history deve essere []."""
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
        with patch(
            "src.core.engine.CoreAgent.run_task", return_value=_task_result("ok")
        ):
            r = _post_stream(max_steps=steps)
        assert r.status_code == 200
