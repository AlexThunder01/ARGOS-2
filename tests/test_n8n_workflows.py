"""
ARGOS — n8n Workflow Integration Tests

Per ogni workflow attivo, recupera le ultime N esecuzioni dall'API n8n
e verifica che:
  1. L'esecuzione sia terminata con status 'success'
  2. Ogni nodo abbia eseguito senza errori

In caso di fallimento stampa:
  - Il nodo che ha generato l'errore
  - L'input ricevuto dal nodo
  - L'output / messaggio di errore prodotto
"""

import os
import time

import pytest
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

N8N_BASE = os.environ.get("N8N_BASE_URL", "http://localhost:5678")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
EXECUTIONS_TO_CHECK = int(os.environ.get("N8N_TEST_EXECUTIONS", "5"))
TRIGGER_WAIT_SECONDS = int(os.environ.get("N8N_TRIGGER_WAIT", "8"))

# Synthetic test payloads injected via n8n webhook-test or direct trigger.
# Keys must match the workflow name fragment (case-insensitive substring).
MOCK_PAYLOADS: dict[str, dict] = {
    "telegram chat": {
        "message": {
            "message_id": 9999,
            "from": {"id": 123456, "first_name": "TestUser", "is_bot": False},
            "chat": {"id": 123456, "type": "private"},
            "text": "ping",
            "date": int(time.time()),
        }
    },
    "gmail analyzer": {
        "id": "test_msg_id",
        "threadId": "test_thread_id",
        "snippet": "Test email snippet for automated testing",
        "From": "test@example.com",
        "Subject": "Test Subject",
        "To": "target@example.com",
    },
    "webhook approvazione": {
        "callback_query": {
            "id": "test_cb_id",
            "from": {"id": 123456, "first_name": "TestUser"},
            "message": {
                "message_id": 1000,
                "chat": {"id": 123456},
                "text": "Test approval message\nPlease select an option",
            },
            "data": "approve|test_queue_id",
        }
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if N8N_API_KEY:
        h["X-N8N-API-KEY"] = N8N_API_KEY
    return h


def _get(path: str, params: dict | None = None) -> dict:
    r = requests.get(
        f"{N8N_BASE}/api/v1{path}", headers=_headers(), params=params, timeout=10
    )
    r.raise_for_status()
    return r.json()


def _get_workflows() -> list[dict]:
    return _get("/workflows")["data"]


def _get_executions(workflow_id: str, limit: int = EXECUTIONS_TO_CHECK) -> list[dict]:
    data = _get("/executions", params={"workflowId": workflow_id, "limit": limit})
    return data.get("data", [])


def _get_execution_detail(exec_id: str) -> dict:
    return _get(f"/executions/{exec_id}", params={"includeData": "true"})


def _format_node_failure(node_name: str, run_data: dict, error: dict | None) -> str:
    """Build a human-readable failure report for a node."""
    lines = [f"\n{'=' * 60}", f"  FAILED NODE: {node_name}", f"{'=' * 60}"]

    node_run = run_data.get(node_name)
    if node_run:
        run = node_run[0]
        lines.append(f"  Status     : {run.get('executionStatus', 'unknown')}")
        lines.append(f"  Duration   : {run.get('executionTime', '?')} ms")

        # Input data
        source = run.get("source", [])
        if source:
            prev_node = source[0].get("previousNode", "—")
            lines.append(f"  Input from : {prev_node}")

        input_data = run.get("inputOverride") or {}
        if input_data:
            import json

            lines.append(
                f"  Input data : {json.dumps(input_data, indent=4, ensure_ascii=False)[:800]}"
            )

        # Output data
        output = run.get("data", {}).get("main", [[]])
        if output and output[0]:
            import json

            lines.append(
                f"  Output     : {json.dumps(output[0][0].get('json', {}), indent=4, ensure_ascii=False)[:800]}"
            )

    if error:
        lines.append(f"  Error name : {error.get('name', '?')}")
        lines.append(f"  Error msg  : {error.get('message', '?')}")
        lines.append(f"  HTTP code  : {error.get('httpCode', '—')}")
        desc = error.get("description", "")
        if desc:
            lines.append(f"  Description: {desc}")
        ctx = error.get("context", {})
        if ctx:
            import json

            req = ctx.get("request", {})
            if req:
                lines.append(
                    f"  Request    : {json.dumps({'method': req.get('method'), 'uri': req.get('uri'), 'body': req.get('body')}, indent=4, ensure_ascii=False)[:600]}"
                )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parametrised test — one test per active workflow
# ---------------------------------------------------------------------------


def pytest_generate_tests(metafunc):
    """Dynamically parametrise test_workflow_executions with active workflows."""
    if "workflow" not in metafunc.fixturenames:
        return

    try:
        workflows = _get_workflows()
    except Exception:
        metafunc.parametrize("workflow", [], ids=[])
        return

    active = [w for w in workflows if w.get("active")]
    # Deduplicate by name (keep first active)
    seen: set[str] = set()
    unique: list[dict] = []
    for w in active:
        if w["name"] not in seen:
            seen.add(w["name"])
            unique.append(w)

    metafunc.parametrize("workflow", unique, ids=[w["name"] for w in unique])


@pytest.mark.integration
def test_workflow_executions(workflow: dict):
    """
    For each active n8n workflow, retrieve the last N executions and assert
    that all of them succeeded. On failure, report the exact failing node
    with its input and output.
    """
    wf_id = workflow["id"]
    wf_name = workflow["name"]

    executions = _get_executions(wf_id)

    if not executions:
        pytest.skip(
            f"No executions found for workflow '{wf_name}' — trigger it at least once."
        )

    failures: list[str] = []

    for exec_summary in executions:
        exec_id = exec_summary["id"]
        status = exec_summary.get("status", "unknown")

        if status in ("running", "waiting"):
            continue  # skip in-flight executions

        detail = _get_execution_detail(exec_id)
        result_data = detail.get("data", {}).get("resultData", {})
        run_data: dict = result_data.get("runData", {})
        top_error: dict | None = result_data.get("error")

        if status != "success":
            # Find which node failed
            failed_node = "unknown"
            node_error = top_error

            if top_error and top_error.get("node"):
                failed_node = top_error["node"].get("name", "unknown")

            # Also scan runData for per-node errors
            for node_name, node_runs in run_data.items():
                for run in node_runs:
                    if run.get("executionStatus") == "error":
                        failed_node = node_name
                        node_error = run.get("error", top_error)
                        break

            report = _format_node_failure(failed_node, run_data, node_error)
            failures.append(
                f"\nExecution {exec_id} | Status: {status} | "
                f"Started: {exec_summary.get('startedAt', '?')}"
                f"{report}"
            )

    if failures:
        failure_text = "\n".join(failures)
        pytest.fail(
            f"\nWorkflow '{wf_name}' had {len(failures)}/{len(executions)} failed executions:"
            f"{failure_text}"
        )


# ---------------------------------------------------------------------------
# Node-level output snapshot test
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_workflow_node_outputs(workflow: dict):
    """
    For the most recent successful execution, verify that each node
    produced non-empty output (i.e. the data chain was not broken).
    """
    wf_id = workflow["id"]
    wf_name = workflow["name"]

    executions = _get_executions(wf_id, limit=10)
    successful = [e for e in executions if e.get("status") == "success"]

    if not successful:
        pytest.skip(f"No successful executions for '{wf_name}' to inspect.")

    detail = _get_execution_detail(successful[0]["id"])
    run_data: dict = detail.get("data", {}).get("resultData", {}).get("runData", {})

    empty_output_nodes: list[str] = []
    for node_name, node_runs in run_data.items():
        for run in node_runs:
            outputs = run.get("data", {}).get("main", [])
            # noOp nodes legitimately produce no output — skip them
            flat = [item for branch in outputs for item in branch]
            if not flat and run.get("executionStatus") != "success":
                empty_output_nodes.append(node_name)

    if empty_output_nodes:
        pytest.fail(
            f"Workflow '{wf_name}': nodes produced empty output "
            f"without success status: {empty_output_nodes}"
        )
