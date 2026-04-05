# ARGOS-2: Personal AI Agent & Automation Hub

ARGOS-2 is an autonomous AI agent for Linux that connects a local CLI, a Telegram bot, a React dashboard, and an n8n automation engine — all sharing a single reasoning core.

---

## Prerequisites

Before you begin, make sure the following are installed:

| Dependency | Minimum version | Notes |
|---|---|---|
| Python | 3.12 | Required for CLI and scripts |
| Docker & Docker Compose | 24+ | Required for the full stack |
| Node.js + npm | 18+ | Required only for dashboard development |

---

## Setup

### 1. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

| Variable | Required | Description |
|---|---|---|
| `LLM_API_KEY` | Yes | API key for your LLM provider (Groq, OpenAI, etc.) |
| `LLM_BASE_URL` | Yes | Base URL of the OpenAI-compatible endpoint |
| `LLM_MODEL` | Yes | Model name (e.g. `llama-3.3-70b-versatile`) |
| `ARGOS_API_KEY` | Yes | Secret key for the internal API and dashboard auth |
| `TELEGRAM_BOT_TOKEN` | For Telegram | Token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | For Telegram | Your Telegram user ID |
| `NGROK_AUTHTOKEN` | For webhooks | ngrok auth token for external webhook tunneling |
| `NGROK_DOMAIN` | For webhooks | Your static ngrok domain |
| `GOOGLE_CLIENT_ID` | For Gmail | OAuth2 client ID for Gmail workflow |
| `GOOGLE_CLIENT_SECRET` | For Gmail | OAuth2 client secret for Gmail workflow |

### 2. Build the dashboard

The dashboard is served as static files by the FastAPI container, so it must be compiled before the Docker build.

```bash
cd dashboard
VITE_ARGOS_API_KEY=<your ARGOS_API_KEY> npm install && npm run build
cd ..
```

> `VITE_ARGOS_API_KEY` must match the `ARGOS_API_KEY` value in your `.env`. This key is embedded in the JS bundle at build time.

### 3. Start the stack

```bash
docker compose up -d --build
```

This starts: PostgreSQL, the ARGOS API, n8n, ngrok, Jaeger, and the Docker Socket Proxy.

### 4. Inject n8n workflows

Once the stack is running, obtain the n8n API key:

1. Open n8n at [http://localhost:5678](http://localhost:5678)
2. Go to **Settings → API → Create API Key**
3. Copy the key into your `.env` as `N8N_API_KEY`

Then run the injector:

```bash
python3 scripts/inject_n8n.py
```

This script automatically waits for n8n to be ready, creates credentials, and activates all workflows.

> **Gmail note**: After injection, go to **Credentials → Gmail account** in n8n and complete the OAuth flow once to authorize Gmail access.

---

## Usage

### CLI

Interact with ARGOS directly from the terminal:

```bash
# Stateless — no memory between runs
python3 scripts/main.py

# Session memory — kept in RAM for the current session only
python3 scripts/main.py --session

# Persistent memory — uses pgvector RAG, shared with the Telegram bot
python3 scripts/main.py --memory
```

### Web Dashboard

After deployment, the dashboard is available at [http://localhost:8000](http://localhost:8000).

For local frontend development with hot reload:

```bash
cd dashboard
echo "VITE_ARGOS_API_KEY=<your ARGOS_API_KEY>" > .env.local
npm run dev
```

The Vite dev server (port 5173) automatically proxies `/api`, `/run`, `/chat`, and `/status` to the FastAPI backend on port 8000.

### Telegram Bot

Once the stack is running and the workflows are injected, start a conversation with your bot on Telegram.

New users are placed in a pending state until approved by the admin via:
- `/approve_<user_id>` — approve access
- `/reject_<user_id>` — reject

Available user commands: `/reset`, `/status`, `/language`, `/tone`, `/name`, `/tasks`, `/help`.

---

## Architecture

```
CLI (scripts/main.py)  ─┐
Dashboard (React)       ├──► FastAPI ──► CoreAgent (src/core/)
Telegram Bot            ─┘        │         ├── Planner & Reasoning
n8n Orchestrator ────────────────►│         ├── Tool Registry (23 tools)
                                             ├── RAG Memory (pgvector)
                                             └── Security Pipeline
```

**Infrastructure:**
- **PostgreSQL 17 + pgvector** — persistent storage and vector similarity search for RAG
- **Docker Socket Proxy** — sandboxed code execution in ephemeral containers (no host network, 128 MB RAM limit)
- **OpenTelemetry + Jaeger** — distributed tracing (UI at [http://localhost:16687](http://localhost:16687))
- **ngrok** — exposes n8n webhooks to the internet via a static domain
- **GitHub Actions** — CI runs tests against both SQLite and PostgreSQL

For a detailed breakdown, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Tool Arsenal (23 tools)

| Category | Tools |
|---|---|
| **Code Execution** | `python_repl` (Docker sandboxed), `bash_exec` (Docker sandboxed) |
| **Document Parsing** | `read_pdf`, `read_csv`, `read_json`, `read_file` |
| **Web & Finance** | `web_search`, `web_scrape`, `crypto_price`, `finance_price`, `get_weather` |
| **Filesystem** | `list_files`, `create_file`, `modify_file`, `rename_file`, `delete_file`, `create_directory`, `delete_directory` |
| **GUI Automation** | `visual_click`, `keyboard_type`, `launch_app`, `describe_screen` |
| **System** | `system_stats` |

---

## Security

Key security settings in `.env`:

```env
# Internal API key — must be set before deploying. Used by the dashboard and n8n.
ARGOS_API_KEY=<generate a strong random string>

# Enables the LLM-based input validator on all entry points (adds latency)
ARGOS_PARANOID_MODE=false

# Rate limiting (applies to both API and Telegram)
RATE_LIMIT_PER_HOUR=50
RATE_LIMIT_PER_MINUTE=10

# Docker sandbox (set automatically by docker-compose; override only for local dev)
DOCKER_HOST=tcp://argos-docker-proxy:2375
WORKSPACE_DIR=./workspace
```

Security layers:
1. **API Key Auth** — all endpoints require `X-ARGOS-API-KEY`
2. **Paranoid Judge** — optional LLM middleware that validates every input for prompt injection
3. **Risk Scoring** — real-time threat evaluation stored in the database
4. **Rate Limiting** — atomic sliding-window quotas via PostgreSQL (no Redis required)
5. **Docker Sandbox** — code execution isolated in ephemeral containers via `docker-socket-proxy`

---

## Troubleshooting

**Dashboard loads but shows no data**
The dashboard requires `ARGOS_API_KEY` to be set in `.env` and `VITE_ARGOS_API_KEY` to be set at build time. See [Setup → Build the dashboard](#2-build-the-dashboard).

**`inject_n8n.py` fails with connection error**
The script includes a built-in retry loop (30 attempts × 3s). If it still fails, check that n8n is healthy: `docker ps` should show `argos-n8n` as `healthy`.

**Telegram bot returns an AI error message**
Usually a transient network issue reaching the LLM provider. Check `docker logs argos-api` for the actual error. If it persists, verify `LLM_API_KEY` and `LLM_BASE_URL` in `.env`.

**`N8N_API_KEY` missing / inject fails with 401**
You need to create the API key in the n8n UI first (Settings → API), then add it to `.env` and re-run `inject_n8n.py`.

---

## Developer Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | CoreAgent internals, component diagram, data flow |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Adding tools, running tests, contributing |
| [CONFIGURATION_GUIDE.md](docs/CONFIGURATION_GUIDE.md) | All `config.yaml` options explained |
| [TELEGRAM_MODULE_SPEC.md](docs/TELEGRAM_MODULE_SPEC.md) | RAG memory pipeline, conversation window, security |
| [TECHNICAL_SPECIFICATION.md](docs/TECHNICAL_SPECIFICATION.md) | Full HLD, security protocols, API reference |
| [n8n_custom_workflows.md](docs/n8n_custom_workflows.md) | Writing and injecting custom n8n workflows |
