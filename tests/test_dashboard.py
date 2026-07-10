import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set env vars BEFORE importing server
os.environ["ARGOS_API_KEY"] = ""  # No key — rely on permissive mode below
os.environ["ARGOS_PERMISSIVE_MODE"] = "true"  # Required for keyless test client
os.environ["ADMIN_CHAT_ID"] = "12345"
os.environ["DB_BACKEND"] = "sqlite"
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""

from unittest.mock import patch

from fastapi.testclient import TestClient


def _make_test_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS tg_rate_limits (
        user_id INTEGER NOT NULL, window_start TEXT NOT NULL, hit_count INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, window_start)
    )""")
    conn.commit()
    return conn


_test_conn = _make_test_db()
_patcher1 = patch("api.routes.dashboard.get_connection", return_value=_test_conn)
_patcher1.start()

from api.server import app

client = TestClient(app)


class TestDashboardStats:
    def test_rate_limits(self):
        # Insert test data
        import datetime
        import hashlib
        import os

        from src.config import RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_MINUTE

        linux_user = os.environ.get("USER", "argos")
        user_id = int(hashlib.sha256(linux_user.encode()).hexdigest()[:16], 16) % (2**31)

        now = datetime.datetime.now(datetime.UTC)
        minute_win = now.strftime("%Y-%m-%dT%H:%M:00Z")
        hour_win = now.strftime("%Y-%m-%dT%H:00:00Z")

        _test_conn.execute(
            "INSERT INTO tg_rate_limits (user_id, window_start, hit_count) VALUES (?, ?, ?)",
            (user_id, minute_win, 3),
        )
        _test_conn.execute(
            "INSERT INTO tg_rate_limits (user_id, window_start, hit_count) VALUES (?, ?, ?)",
            (user_id, hour_win, 25),
        )
        _test_conn.commit()

        r = client.get("/api/stats/rate_limits")
        assert r.status_code == 200
        data = r.json()
        assert "minute" in data
        assert "hour" in data
        assert data["minute"]["used"] == 3
        assert data["hour"]["used"] == 25
        assert data["minute"]["max"] == RATE_LIMIT_PER_MINUTE
        assert data["hour"]["max"] == RATE_LIMIT_PER_HOUR

    @patch("api.routes.dashboard._collect_docker_stats")
    def test_docker_stats(self, mock_collect):
        mock_collect.return_value = {
            "argos-api": {
                "state": "running",
                "image": "api:latest",
                "health": "healthy",
            }
        }
        r = client.get("/api/stats/docker")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["containers"]["argos-api"]["state"] == "running"

    def test_system_stats(self):
        r = client.get("/api/stats/system")
        assert r.status_code == 200
        data = r.json()
        assert "cpu" in data
        assert "ram" in data
        assert "db_pool" in data
        assert "isolation" in data
        assert "exec_last_run" in data
        assert type(data["cpu"]) in [float, int]
        assert type(data["ram"]) in [float, int]

    def test_security_stats(self):
        import datetime

        now = datetime.datetime.now(datetime.UTC)
        today = now.strftime("%Y-%m-%d")

        _test_conn.execute("""CREATE TABLE IF NOT EXISTS tg_suspicious_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, content TEXT, 
            category TEXT, risk_score REAL, blocked_by TEXT, created_at TEXT
        )""")
        _test_conn.execute(
            "INSERT INTO tg_suspicious_memories (user_id, content, risk_score, created_at) VALUES (?, ?, ?, ?)",
            (1, "bad prompt", 0.9, f"{today} 12:00:00"),
        )
        _test_conn.commit()

        r = client.get("/api/stats/security")
        assert r.status_code == 200
        data = r.json()
        assert data["paranoid_judge"] is True
        assert data["blocked_today"] >= 1
        assert "risk_score_avg" in data

    def test_latency_stats(self):
        r = client.get("/api/stats/latency")
        assert r.status_code == 200
        data = r.json()
        assert "ping" in data
        assert "db_query" in data
        assert "memory_recall" in data
        assert "n8n_trigger" in data
        assert "ms" in data["ping"]
        assert "ms" in data["db_query"]

    def test_config_stats(self):
        r = client.get("/api/stats/config")
        assert r.status_code == 200
        data = r.json()
        assert "model" in data
        assert "version" in data
