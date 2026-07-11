# n8n Custom Workflows

## Overview

n8n serves as a **credential manager and webhook router** for ARGOS result delivery. n8n does NOT orchestrate agent reasoning, make LLM calls, or invoke tools directly. ARGOS maintains full task execution autonomy.

---

## n8n Role (D-04)

n8n in ARGOS serves ONLY as:

1. **OAuth2 Credential Manager**: Credentials are created via n8n API and validated before workflow activation
2. **Webhook Receiver and Router**: ARGOS delivers task results via HTTP POST to n8n webhook URLs, and n8n routes them to downstream workflows
3. **NOT a Task Orchestrator**: n8n cannot execute agent reasoning, make LLM calls, or invoke tools

Key distinction: ARGOS is the **thinking engine**. n8n is the **delivery mechanism** — it receives completed results and routes them to your business logic.

---

## Integration Flow

### 1. Task Execution (Inside ARGOS)

```
User Task
    ↓
CoreAgent Reasoning (LLM loop)
    ↓
Tools Execute (code, web, API calls, etc.)
    ↓
Task Complete
```

### 2. Result Delivery (via n8n)

```
Task Result (JSON)
    ↓
ARGOS n8n Reachability Check (only if N8N_BASE_URL is set)
    ↓
HTTP POST to n8n Webhook URL
    ↓
n8n Webhook Listener Receives Result
    ↓
n8n Routes to Configured Workflows
    ↓
Downstream Action (Send email, update database, etc.)
```

### 3. Known Limitations

- **No agent loop feedback**: n8n cannot request ARGOS to continue a task or provide additional steps
- **No mid-flight modification**: n8n cannot modify task execution while it's running
- **Async webhook delivery**: Result delivery is fire-and-forget; if webhook delivery fails, result is not retried

---

## Provisioning n8n Workflows (`scripts/inject_n8n.py`)

Credential creation (`create_telegram_credential`, `create_gmail_credential`) is a separate,
one-time **setup** step — it patches a workflow JSON template with a freshly created n8n
credential ID and imports it via n8n's API. It runs standalone (`python3 scripts/inject_n8n.py`),
authenticated with `N8N_API_KEY`/`N8N_HOST`/`N8N_PORT`, and is unrelated to the `/run_async`
request path: nothing produced there flows into a running task's webhook payload, and
`/run_async` performs no credential validation of its own — only the reachability check below.

```
logger.error("[n8n] n8n unreachable: HTTP 503")
logger.info("[n8n] Reachability verified")
```

---

## Configuration

### Environment Variable: N8N_BASE_URL

Set the n8n instance URL in your `.env`:

```bash
N8N_BASE_URL=http://localhost:5678
```

If `N8N_BASE_URL` is empty or not set:
- n8n integration is disabled
- Health check shows `n8n: unconfigured`
- No credential or OAuth checks are performed

---

## Endpoint: POST /run_async

To deliver ARGOS task results to an n8n webhook:

```bash
curl -X POST http://localhost:8000/api/run_async \
  -H "X-ARGOS-API-KEY: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Analyze this data and summarize",
    "webhook_url": "https://your-n8n-instance.com/webhook/task-complete",
    "require_confirmation": false,
    "max_steps": 5
  }'
```

Response (HTTP 202 Accepted):

```json
{
  "status": "accepted",
  "job_id": "abc12345",
  "message": "The task has been securely queued. Final execution payload will be delivered to the provided webhook.",
  "deduplicated": false
}
```

When the task completes, ARGOS POSTs the result JSON to your webhook URL.

---

## Health Check

Check ARGOS system status including n8n configuration:

```bash
curl http://localhost:8000/api/health
```

Response:

```json
{
  "status": "ok",
  "checks": {
    "api": "ok",
    "db": "ok",
    "llm": "ok",
    "migrations": "applied",
    "n8n": "configured"
  }
}
```

If `n8n` is `unconfigured`, set `N8N_BASE_URL` and restart the server.

---

## Security Notes

1. **SSRF Protection**: Webhook URLs are validated to prevent Server-Side Request Forgery (SSRF) attacks. Loopback (localhost, 127.0.0.1) and private IP addresses (10.x, 172.16.x, 192.168.x) are blocked.

2. **API Key Required**: All `/run` and `/run_async` calls require the `X-ARGOS-API-KEY` header.

3. **Credential Isolation**: Credentials created in n8n are isolated per n8n instance. ARGOS does not store or manage credentials directly.

4. **No PII in Health Checks**: The `/health` endpoint returns only status strings ("ok", "error", "configured", etc.), not sensitive data or error stack traces.

---

## Example: Email Analysis Workflow

This is a typical n8n workflow using ARGOS:

1. **Trigger**: Gmail Webhook listens for new emails
2. **Extract**: n8n saves email body to a file
3. **ARGOS Task**: POST to `/run_async` with task: "Analyze this email: /tmp/email.txt"
4. **ARGOS Executes**: CoreAgent reasoning → tool execution → result
5. **n8n Receives**: Webhook receives result JSON
6. **n8n Routes**: Based on result, send Slack notification or create ticket

```json
// Example result payload posted to n8n webhook
{
  "success": true,
  "task": "Analyze this email for sentiment",
  "steps_executed": 3,
  "result": "Email tone is professional but urgent. Recommend immediate response.",
  "job_id": "abc12345",
  "backend": "openai-compatible",
  "model": "llama-3.3-70b-versatile"
}
```

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `inject_n8n.py` fails to create a credential | Credential creation rejected by n8n | Verify `N8N_API_KEY` is valid and not expired; check n8n logs |
| "n8n unreachable: HTTP xxx" | n8n instance down or `N8N_BASE_URL` wrong | Verify n8n is running and `N8N_BASE_URL` points to it |
| Webhook delivery timeout | Webhook URL is unreachable or slow | Verify webhook URL is publicly accessible; check n8n webhook listener is running |
| "N8N_BASE_URL is empty" | n8n is not configured | Set `N8N_BASE_URL` in `.env` and restart server |

---

## Further Reading

- [n8n Official Documentation](https://docs.n8n.io/)
- [ARGOS API Reference](./ARCHITECTURE.md)
- [Health Check Endpoint Details](./CONFIGURATION_GUIDE.md)
