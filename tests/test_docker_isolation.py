"""
Docker Sandbox Isolation Tests — pytest suite.

These tests verify the sandboxing contract of python_repl_tool and bash_exec_tool
without requiring a live Docker daemon. The Docker client is mocked so these run
in CI alongside unit tests.

Integration tests against a real Docker daemon can be enabled by passing
--docker-live to pytest (requires Docker socket access).
"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DOCKER_HOST", "tcp://127.0.0.1:2375")
os.environ.setdefault("HOST_WORKSPACE_DIR", os.path.abspath("./workspace"))
os.environ.setdefault("WORKSPACE_DIR", os.path.abspath("./workspace"))


# ---------------------------------------------------------------------------
# Helpers — build a mock Docker client that returns configurable output
# ---------------------------------------------------------------------------


def _mock_container(stdout: bytes = b"", stderr: bytes = b"", exit_code: int = 0):
    """Returns a mock Docker container whose wait/logs mimic the real API."""
    container = MagicMock()
    container.wait.return_value = {"StatusCode": exit_code}
    container.logs.return_value = stdout + stderr
    return container


def _mock_docker_client(container):
    """Wraps a container mock inside a Docker DockerClient mock."""
    client = MagicMock()
    client.containers.run.return_value = container
    return client


# ---------------------------------------------------------------------------
# python_repl_tool — unit tests
# ---------------------------------------------------------------------------


class TestPythonReplTool:
    @patch("src.tools.code_exec._get_docker_client")
    def test_basic_math(self, mock_get_client, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        import src.config as cfg

        monkeypatch.setattr(cfg, "WORKSPACE_DIR", str(tmp_path))

        from src.tools import code_exec

        monkeypatch.setattr(code_exec, "WORKSPACE_DIR", str(tmp_path))

        from src.tools.code_exec import python_repl_tool

        container = _mock_container(stdout=b"1024\n")
        mock_get_client.return_value = _mock_docker_client(container)

        result = python_repl_tool({"code": "print(2**10)"})
        assert "1024" in result

    @patch("src.tools.code_exec._get_docker_client")
    def test_network_isolation_enforced(self, mock_get_client, tmp_path, monkeypatch):
        """Verifies that network_mode=none is passed to containers.run."""
        from src.tools import code_exec

        monkeypatch.setattr(code_exec, "WORKSPACE_DIR", str(tmp_path))

        from src.tools.code_exec import python_repl_tool

        container = _mock_container(stdout=b"ok\n")
        client = _mock_docker_client(container)
        mock_get_client.return_value = client

        python_repl_tool({"code": "print('ok')"})

        _, kwargs = client.containers.run.call_args
        assert kwargs.get("network_mode") == "none", (
            "Docker container must be started with network_mode='none'"
        )

    @patch("src.tools.code_exec._get_docker_client")
    def test_memory_limit_enforced(self, mock_get_client, tmp_path, monkeypatch):
        """Verifies that mem_limit is passed to containers.run."""
        from src.tools import code_exec

        monkeypatch.setattr(code_exec, "WORKSPACE_DIR", str(tmp_path))

        from src.tools.code_exec import python_repl_tool

        container = _mock_container(stdout=b"ok\n")
        client = _mock_docker_client(container)
        mock_get_client.return_value = client

        python_repl_tool({"code": "print('ok')"})

        _, kwargs = client.containers.run.call_args
        assert "mem_limit" in kwargs, "Docker container must have a memory limit set"

    @patch("src.tools.code_exec._get_docker_client")
    def test_nonzero_exit_code_returns_output(self, mock_get_client, tmp_path, monkeypatch):
        """A nonzero exit code still returns the captured output (logs)."""
        from src.tools import code_exec

        monkeypatch.setattr(code_exec, "WORKSPACE_DIR", str(tmp_path))

        from src.tools.code_exec import python_repl_tool

        container = _mock_container(stderr=b"SyntaxError: invalid syntax\n", exit_code=1)
        mock_get_client.return_value = _mock_docker_client(container)

        result = python_repl_tool({"code": "def("})
        assert "SyntaxError" in result

    def test_missing_code_argument(self):
        from src.tools.code_exec import python_repl_tool

        result = python_repl_tool({})
        assert result.lower().startswith("error")

    @patch("src.tools.code_exec._get_docker_client")
    def test_docker_unavailable_returns_error(self, mock_get_client, tmp_path, monkeypatch):
        from src.tools import code_exec

        monkeypatch.setattr(code_exec, "WORKSPACE_DIR", str(tmp_path))

        from src.tools.code_exec import python_repl_tool

        mock_get_client.side_effect = Exception("Cannot connect to Docker daemon")

        result = python_repl_tool({"code": "print('hi')"})
        assert "error" in result.lower()


# ---------------------------------------------------------------------------
# bash_exec_tool — unit tests
# ---------------------------------------------------------------------------


class TestBashExecTool:
    @patch("src.tools.code_exec._get_docker_client")
    def test_basic_command(self, mock_get_client):
        from src.tools.code_exec import bash_exec_tool

        container = _mock_container(stdout=b"hello\n")
        mock_get_client.return_value = _mock_docker_client(container)

        result = bash_exec_tool({"command": "echo hello"})
        assert "hello" in result

    @patch("src.tools.code_exec._get_docker_client")
    def test_network_isolation_enforced(self, mock_get_client):
        """Verifies that network_mode=none is passed to containers.run."""
        from src.tools.code_exec import bash_exec_tool

        container = _mock_container(stdout=b"Network is isolated!\n")
        client = _mock_docker_client(container)
        mock_get_client.return_value = client

        bash_exec_tool({"command": "echo isolated"})

        _, kwargs = client.containers.run.call_args
        assert kwargs.get("network_mode") == "none", "bash_exec must run with network_mode='none'"

    def test_missing_command_argument(self):
        from src.tools.code_exec import bash_exec_tool

        result = bash_exec_tool({})
        assert result.lower().startswith("error")
