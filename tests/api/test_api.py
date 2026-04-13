"""
Test degli Endpoint FastAPI — usa TestClient per verificare le risposte HTTP
senza avviare il server reale.

La connessione al DB è gestita da conftest.py (autouse fixture).
Qui non duplichiamo il setup: ci affidiamo interamente a patch_db.

Endpoint testati:
  GET  /health          → 200 {status: ok}
  GET  /status          → 200 {status: online, backend, model, agent_ready}
  POST /run             → 200 TaskResponse (con LLM mockato)
  POST /run             → 422 se manca il campo obbligatorio 'task'
  POST /run             → 429 se rate limit superato
  POST /run_async       → 400 se webhook_url è SSRF (loopback)
  POST /run_async       → 400 se webhook_url ha schema non http/https
  POST /run_async       → 202 con job_id valido
  POST /run_async       → idempotency: stesso job_id se stessa chiave
  POST /pending_email/:id/consume → 404 per ID inesistente
  POST /telegram/chat   → 422 se mancano campi obbligatori
"""

import os
import sys

# Risali alla root del progetto (tests/api/ → tests/ → root)
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.server import app

# TestClient viene creato a livello di modulo per compatibilità con i test esistenti.
# L'isolamento DB è garantito dalla fixture autouse patch_db di conftest.py,
# che patcha get_connection() prima di ogni test.
client = TestClient(app, raise_server_exceptions=False)


# ==========================================================================
# Helpers
# ==========================================================================


def _mock_task_result(response="Fatto!", success=True, steps=0):
    """Crea un TaskResult mock con i campi minimi."""
    from src.core.engine import TaskResult

    return TaskResult(
        success=success,
        task="test task",
        response=response,
        steps_executed=steps,
        history=[],
        memories_used=0,
    )


# ==========================================================================
# Health & Status
# ==========================================================================


class TestHealthEndpoints:
    def test_health_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_status_returns_200(self):
        """GET /status → backend, model, agent_ready (definito in api/routes/agent.py)."""
        r = client.get("/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "online"
        assert "backend" in data
        assert "model" in data
        assert data["agent_ready"] is True


# ==========================================================================
# POST /run — Agent Task Execution
# ==========================================================================


class TestRunEndpoint:
    def test_run_missing_task_returns_422(self):
        """Manca il campo obbligatorio 'task' → 422 Unprocessable Entity."""
        r = client.post("/run", json={})
        assert r.status_code == 422

    def test_run_invalid_max_steps_returns_422(self):
        """max_steps fuori range (1-20) → 422."""
        r = client.post("/run", json={"task": "test", "max_steps": 0})
        assert r.status_code == 422

        r = client.post("/run", json={"task": "test", "max_steps": 99})
        assert r.status_code == 422

    def _make_task_response(self):
        """Crea una TaskResponse Pydantic valida che FastAPI può serializzare."""
        from api.routes.agent import TaskResponse

        return TaskResponse(
            success=True,
            task="test task",
            steps_executed=0,
            result="Completato!",
            history=[],
            backend="openai-compatible",
            model="test-model",
        )

    def test_run_returns_task_response(self):
        """Con LLM mockato, /run ritorna una TaskResponse valida."""
        with patch(
            "api.routes.agent._run_task_async_core",
            new_callable=AsyncMock,
            return_value=self._make_task_response(),
        ):
            r = client.post("/run", json={"task": "test task"})

        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["result"] == "Completato!"
        assert "steps_executed" in data
        assert "backend" in data
        assert "model" in data
        assert "history" in data

    def test_run_with_require_confirmation_false(self):
        """require_confirmation=False è il default e non cambia il comportamento."""
        with patch(
            "api.routes.agent._run_task_async_core",
            new_callable=AsyncMock,
            return_value=self._make_task_response(),
        ):
            r = client.post(
                "/run", json={"task": "test", "require_confirmation": False}
            )

        assert r.status_code == 200

    def test_run_rate_limit_returns_429(self):
        """Se il rate limit è superato, /run ritorna 429."""
        from src.core.rate_limit import RateLimitExceeded

        # check_rate_limit è importato localmente dentro la route, quindi
        # si patcha nel modulo sorgente.
        with patch(
            "src.core.rate_limit.check_rate_limit",
            side_effect=RateLimitExceeded("Rate limit exceeded"),
        ):
            r = client.post("/run", json={"task": "test"})

        assert r.status_code == 429


# ==========================================================================
# POST /run_async — Async Agent Execution
# ==========================================================================


class TestRunAsyncEndpoint:
    def test_run_async_missing_task_returns_422(self):
        r = client.post("/run_async", json={"webhook_url": "https://example.com/hook"})
        assert r.status_code == 422

    def test_run_async_missing_webhook_returns_422(self):
        r = client.post("/run_async", json={"task": "test task"})
        assert r.status_code == 422

    def test_run_async_loopback_webhook_blocked(self):
        """Webhook URL con hostname localhost → 400 (SSRF guard)."""
        r = client.post(
            "/run_async",
            json={"task": "test", "webhook_url": "http://localhost/hook"},
        )
        assert r.status_code == 400
        assert (
            "webhook_url" in r.json()["detail"].lower()
            or "Invalid" in r.json()["detail"]
        )

    def test_run_async_private_ip_webhook_blocked(self):
        """Webhook URL con IP privato → 400 (SSRF guard)."""
        r = client.post(
            "/run_async",
            json={"task": "test", "webhook_url": "http://192.168.1.100/hook"},
        )
        assert r.status_code == 400

    def test_run_async_non_http_scheme_blocked(self):
        """Webhook URL con schema ftp → 400."""
        r = client.post(
            "/run_async",
            json={"task": "test", "webhook_url": "ftp://example.com/hook"},
        )
        assert r.status_code == 400

    def test_run_async_valid_returns_202(self):
        """Webhook valido → 202 Accepted con job_id."""
        with patch("api.routes.agent._run_task_async_core", new_callable=AsyncMock):
            r = client.post(
                "/run_async",
                json={"task": "test task", "webhook_url": "https://example.com/hook"},
            )

        assert r.status_code == 202
        data = r.json()
        assert "job_id" in data
        assert data["status"] == "accepted"
        assert data["deduplicated"] is False

    def test_run_async_idempotency_key_deduplication(self):
        """Stesso Idempotency-Key → stesso job_id, deduplicated=True."""
        with patch("api.routes.agent._run_task_async_core", new_callable=AsyncMock):
            r1 = client.post(
                "/run_async",
                json={"task": "test", "webhook_url": "https://example.com/hook"},
                headers={"Idempotency-Key": "test-idem-key-12345"},
            )
            r2 = client.post(
                "/run_async",
                json={"task": "test", "webhook_url": "https://example.com/hook"},
                headers={"Idempotency-Key": "test-idem-key-12345"},
            )

        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["job_id"] == r2.json()["job_id"]
        assert r2.json()["deduplicated"] is True


# ==========================================================================
# POST /pending_email/:id/consume — HITL Email
# ==========================================================================


class TestEmailEndpoints:
    def test_consume_nonexistent_returns_404(self, api_db):
        """
        ID inesistente → 404.
        api_db è la fixture locale (conftest.py di questa directory) che
        fornisce il DB in-memory già configurato con la tabella pending_emails.
        """
        with patch("api.routes.email.get_connection", return_value=api_db):
            r = client.post("/pending_email/nonexistent-id/consume")
        assert r.status_code == 404


# ==========================================================================
# POST /telegram/chat — Validazione input
# ==========================================================================


class TestTelegramEndpoint:
    def test_missing_fields_returns_422(self):
        """Senza i campi obbligatori (user_id, chat_id, text) → 422."""
        r = client.post("/telegram/chat", json={})
        assert r.status_code == 422

    def test_missing_text_returns_422(self):
        """Manca 'text' → 422."""
        r = client.post("/telegram/chat", json={"user_id": 1, "chat_id": 1})
        assert r.status_code == 422

    def test_missing_user_id_returns_422(self):
        """Manca 'user_id' → 422."""
        r = client.post("/telegram/chat", json={"chat_id": 1, "text": "ciao"})
        assert r.status_code == 422
