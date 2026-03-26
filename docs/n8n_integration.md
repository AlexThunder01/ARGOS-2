# 🔗 ARGOS + n8n Integration Guide

## Architecture

```
n8n Workflow → HTTP Request → ARGOS API → Agent executes task → JSON response → n8n continues
```

> **Principle:** ARGOS handles all reasoning and execution. n8n only handles triggers, routing, notifications, and multi-service orchestration.

---

## Setup

### 1. Start ARGOS API
```bash
cd argos/
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

### 2. Verify it's running
```bash
curl http://localhost:8000/status
```
```json
{"status": "online", "backend": "groq", "model": "meta-llama/...", "agent_ready": true}
```

---

## API Endpoints

### `POST /run` — Execute a Task

**Request:**
```json
{
  "task": "Search for the current weather in London and save the result to a file",
  "require_confirmation": true,
  "max_steps": 5
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `task` | string | required | Natural language task description |
| `require_confirmation` | bool | `false` | Block dangerous actions (file ops, clicks) |
| `max_steps` | int | `5` | Max agent loop iterations (1–20) |

**Response:**
```json
{
  "success": true,
  "task": "Search for the current weather in London...",
  "steps_executed": 2,
  "result": "✅ Created: /home/user/Desktop/weather_london.txt",
  "history": [
    {"step": 1, "tool": "web_search", "result": "In London today...", "success": true, "timestamp": "14:32:01"},
    {"step": 2, "tool": "create_file", "result": "✅ Created: ...", "success": true, "timestamp": "14:32:03"}
  ],
  "backend": "groq",
  "model": "meta-llama/llama-4-maverick-17b-128e-instruct"
}
```

### `POST /run_async` — Execute Task in Background (Webhook) ✅ **Recommended for n8n**
**Use this for long-running tasks** so n8n doesn't hit HTTP timeouts while waiting for ARGOS.

**Request:**
```json
{
  "webhook_url": "https://your-n8n-domain/webhook/argos-callback",
  "task": "Explore 5 websites about generative AI and extract the key concepts",
  "require_confirmation": false,
  "max_steps": 10
}
```

**Immediate Response (HTTP 202 Accepted):**
```json
{
  "status": "accepted",
  "job_id": "c92f1b4a",
  "message": "The task has been accepted. The result will be posted to the provided webhook URL."
}
```

*ARGOS will perform the task in the background. Once finished (or failed), it will `POST` the standard `TaskResponse` JSON structure directly to the `webhook_url`, including the `job_id` property so n8n can map it back to the original workflow using a "Wait for Webhook" node.*

### `GET /status` — Health Check
```json
{"status": "online", "backend": "groq", "model": "...", "agent_ready": true}
```

### `GET /logs/last` — Last Session Log
```json
{"log_file": "logs/argos_20260325_143200.log", "lines": ["..."]}
```

---

## n8n Workflow Examples

### Example 1: Scheduled Web Research
```
Schedule Trigger (daily 9:00)
  → HTTP Request POST http://localhost:8000/run
    body: {"task": "Cerca le ultime notizie su AI e salvale in un file", "max_steps": 5}
  → IF node (success == true)
    → Telegram: "✅ Report generato"
    → ELSE: Telegram: "❌ Task fallito"
```

### Example 2: Webhook-triggered Desktop Automation
```
Webhook (POST /webhook/desktop-task)
  → HTTP Request POST http://localhost:8000/run
    body: {"task": "{{$json.task}}", "require_confirmation": false}
  → Respond to Webhook with result
```

### Example 3: File Monitoring + Processing
```
Schedule Trigger (every 30 min)
  → HTTP Request POST http://localhost:8000/run
    body: {"task": "Elenca i file sul desktop e dimmi se ce ne sono di nuovi"}
  → IF node (new files detected in result)
    → Email: notify user
```

### Example 4: Long-running Web Research (Async)
```
Webhook A (Trigger)
  → HTTP Request POST http://localhost:8000/run_async
    body: {"webhook_url": "http://localhost:5678/webhook/argos-done", "task": "Leggi 3 blog..."}
  → Wait for Webhook B
  
Webhook B (http://localhost:5678/webhook/argos-done)
  → Read body.result
  → Save to Notion / Google Sheets
```

---

## Security Notes

- Set `require_confirmation: true` for untrusted triggers
- ARGOS API should run on localhost only (not exposed to internet)
- For remote access, use a reverse proxy with authentication
