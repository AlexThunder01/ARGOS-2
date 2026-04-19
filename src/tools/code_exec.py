"""
ARGOS-2 Tool — Code Execution Sandbox (Fase 8).

Esegue codice Python e comandi Bash all'interno di container Docker temporanei
protetti da docker-socket-proxy.
Nessun accesso alla rete o al filesystem host, ad eccezione della workspace dedicata.
"""

import os
import threading
import uuid

from src.config import (
    DOCKER_EXEC_MEM_LIMIT,
    DOCKER_EXEC_TIMEOUT,
    DOCKER_HOST,
    HOST_WORKSPACE_DIR,
    WORKSPACE_DIR,
)

from .helpers import _get_arg

# Maximum execution time in seconds (configurable via DOCKER_EXEC_TIMEOUT env var)
EXEC_TIMEOUT = DOCKER_EXEC_TIMEOUT

# Maximum output length in characters
MAX_OUTPUT = 5000

_docker_client = None
_docker_client_lock = threading.Lock()


def _get_docker_client():
    global _docker_client
    if _docker_client is None:
        with _docker_client_lock:
            if _docker_client is None:
                import docker

                _docker_client = docker.DockerClient(base_url=DOCKER_HOST)
    return _docker_client


def _run_in_docker(image: str, command: list, timeout: int = EXEC_TIMEOUT) -> str:
    import docker
    from requests.exceptions import ReadTimeout

    try:
        client = _get_docker_client()
    except Exception as e:
        return f"Error: Non riesco a connettermi al Docker Socket Proxy ({DOCKER_HOST}): {e}"

    volumes = {}
    if HOST_WORKSPACE_DIR:
        volumes[HOST_WORKSPACE_DIR] = {"bind": "/workspace", "mode": "rw"}

    try:
        try:
            container = client.containers.run(
                image,
                command,
                volumes=volumes,
                working_dir="/workspace",
                detach=True,
                mem_limit=DOCKER_EXEC_MEM_LIMIT,
                cpu_quota=25000,  # 25% of single CPU core
                network_mode="none",  # NO network access
                environment={"PYTHONDONTWRITEBYTECODE": "1"},
            )
        except docker.errors.ImageNotFound:
            return f"Error: Docker Image '{image}' not found on the host system."

        try:
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", 1)
        except (ReadTimeout, Exception):
            # Execution timed out
            container.kill()
            container.remove(force=True)
            return f"Error: Execution timed out ({timeout}s limit). Simplify or optimize your code."

        logs = container.logs().decode("utf-8")
        container.remove(force=True)

        output = logs
        if not output.strip():
            output = (
                f"(Code executed successfully with exit code {exit_code} but produced no output. "
                f"Always use print() to display results, e.g.: print(result))"
            )

        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + f"\n... [truncated, {len(output)} total chars]"

        return output

    except Exception as e:
        return f"Error: Container execution failed: {e}"


_AUTO_PRINT_SUFFIX = """
# --- auto-print injected by ARGOS ---
try:
    _ns = {k: v for k, v in vars().items()
           if not k.startswith('_') and not callable(v) and not isinstance(v, type)}
    if _ns:
        for _k, _v in list(_ns.items())[-10:]:
            print(f"{_k} = {_v!r}")
            # Show value in thousands if large (helps with 'how many thousand X' questions)
            if isinstance(_v, (int, float)) and 1000 <= abs(_v) < 1e9:
                print(f"  → in thousands: {round(_v / 1000, 4)!r}")
except Exception:
    pass
"""


def python_repl_tool(inp):
    """
    Executes Python code in a sandboxed Docker container (python:3.12-slim).
    Always use print() in your code to display results. If the code produces no
    output the tool will automatically print all local variables as a fallback.
    """
    code = _get_arg(inp, ["code", "script", "python", "source"])
    if not code:
        return "Error: No code provided. Use {'code': 'your python code here'}."

    script_name = f"argos_repl_{uuid.uuid4().hex[:8]}.py"
    script_path = os.path.join(WORKSPACE_DIR, script_name)

    # First pass: run user code as-is
    with open(script_path, "w") as f:
        f.write(code)

    try:
        output = _run_in_docker(
            image="python:3.12-slim", command=["python", f"/workspace/{script_name}"]
        )

        # If no output, re-run with auto-print suffix to surface variable values
        if "no output" in output.lower() or not output.strip():
            with open(script_path, "w") as f:
                f.write(code + _AUTO_PRINT_SUFFIX)
            output2 = _run_in_docker(
                image="python:3.12-slim",
                command=["python", f"/workspace/{script_name}"],
            )
            if output2.strip() and "no output" not in output2.lower():
                output = (
                    output2 + "\n(auto-printed variables — add explicit print() to control output)"
                )

        return f"🐍 Python Result:\n{output}"
    finally:
        if os.path.islink(script_path) or os.path.exists(script_path):
            os.remove(script_path)


def bash_exec_tool(inp):
    """
    Executes a bash command in a sandboxed Docker container (python:3.12-slim).
    """
    command = _get_arg(inp, ["command", "cmd", "bash", "shell"])
    if not command:
        return "Error: No command provided. Use {'command': 'your bash command'}."

    output = _run_in_docker(image="python:3.12-slim", command=["bash", "-c", command])
    return f"🖥️ Bash Result:\n{output}"
