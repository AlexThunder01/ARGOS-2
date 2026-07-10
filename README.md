# ARGOS-2: Personal AI Agent & Automation Hub

ARGOS-2 is an autonomous AI agent for Linux. You give it a task in natural language — via terminal, Telegram, or a web dashboard — and it plans and executes it using a library of 33 tools: web search, code execution, file management, browser automation, document parsing, finance data, and more.

---

## What ARGOS can do

```
You › Find the top 5 Python libraries for data validation, write a comparison table, and save it as comparison.md
You › Read the attached invoice.pdf and tell me the total amount due
You › Check the current BTC and ETH prices and send me a summary
You › Go to example.com, fill in the contact form with these details, and submit it
You › Run this script in a sandbox and show me the output
You › Every time a new email arrives, summarize it and send it to my Telegram
```

ARGOS reasons step-by-step, picks the right tools, executes them, and returns a result — all in one shot.

---

## Quick Start (CLI only, no Docker)

The fastest way to try ARGOS locally using SQLite and the terminal.

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Configure the environment**

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```env
LLM_API_KEY=your_key_here
LLM_BASE_URL=https://api.groq.com/openai/v1   # or any OpenAI-compatible endpoint
LLM_MODEL=llama-3.3-70b-versatile
DB_BACKEND=sqlite
```

**3. Run**

```bash
python3 scripts/main.py
```

That's it. ARGOS starts an interactive session in your terminal. No Docker, no n8n, no Telegram required.

> For persistent memory across sessions, add `--memory`. For the full stack (Telegram bot, dashboard, n8n automation), follow the [Full Setup](#full-setup) below.

---

## Prerequisites

| Dependency | Minimum version | Required for |
|---|---|---|
| Python | 3.12 | CLI and scripts |
| Docker & Docker Compose | 24+ | Full stack |
| Node.js + npm | 18+ | Dashboard development only |

---

## Full Setup

### 1. Configure environment variables

```bash
cp .env.example .env
```

**Core LLM**

| Variable | Required | Description |
|---|---|---|
| `LLM_API_KEY` | Yes | API key for your LLM provider (Groq, OpenAI, Mistral, etc.) |
| `LLM_BASE_URL` | Yes | Base URL of the OpenAI-compatible endpoint |
| `LLM_MODEL` | Yes | Model name (e.g. `llama-3.3-70b-versatile`) |
| `LLM_BACKEND` | No | Provider backend: `openai-compatible` (default) or `anthropic` |
| `LLM_LIGHTWEIGHT_MODEL` | No | Model for background tasks (memory extraction). Defaults to `llama-3.1-8b-instant` |
| `LLM_API_KEY_2` | No | Secondary LLM API key (load balancing / fallback) |

**Security & API**

| Variable | Required | Description |
|---|---|---|
| `ARGOS_API_KEY` | Yes | Secret key for the internal API and dashboard auth |
| `ARGOS_PARANOID_MODE` | No | Set to `true` to enable LLM-based input validation on all endpoints (default: `false`) |
| `ARGOS_PERMISSIVE_MODE` | No | Set to `true` to bypass API key auth — local dev only, never in production (default: `false`) |

**Database**

| Variable | Required | Description |
|---|---|---|
| `DB_BACKEND` | No | `sqlite` (default for local dev) or `postgres` (production with Docker) |
| `DATABASE_URL` | For postgres | PostgreSQL connection string (e.g. `postgresql://user:pass@host:5432/db`) |
| `POSTGRES_PASSWORD` | For postgres | PostgreSQL password (used by `docker-compose`) |

**RAG Memory (Embeddings)**

| Variable | Required | Description |
|---|---|---|
| `EMBEDDING_BASE_URL` | For RAG memory | Embeddings API endpoint (default: Groq) |
| `EMBEDDING_API_KEY` | For RAG memory | Embeddings API key |
| `EMBEDDING_MODEL` | For RAG memory | Embedding model name (default: `nomic-embed-text-v1.5`) |
| `EMBEDDING_DIM` | For RAG memory | Embedding vector dimensions (default: `768`) |

**Vision**

| Variable | Required | Description |
|---|---|---|
| `VISION_BASE_URL` | For vision tools | Vision LLM endpoint (defaults to `LLM_BASE_URL`) |
| `VISION_API_KEY` | For vision tools | Vision LLM API key (defaults to `LLM_API_KEY`) |
| `VISION_MODEL` | For vision tools | Vision model name |

**Voice / Speech-to-Text**

| Variable | Required | Description |
|---|---|---|
| `ENABLE_VOICE` | No | Set to `true` to enable voice input in the CLI (default: `false`) |
| `STT_BACKEND` | For voice | STT provider: `groq` (default), `openai`, or `custom` |
| `STT_CUSTOM_URL` | For custom STT | Whisper-compatible endpoint URL |
| `STT_CUSTOM_API_KEY` | For custom STT | API key for the custom STT endpoint |

**Telegram**

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | For Telegram n8n bot | Token from [@BotFather](https://t.me/BotFather) — used by n8n workflows |
| `TELEGRAM_CHAT_ID` | For Telegram n8n bot | Your Telegram user ID — used by n8n workflows |
| `TELEGRAM_CHAT_BOT_TOKEN` | For Telegram chat bot | Token for the direct chat bot (separate from the n8n bot) |
| `ADMIN_CHAT_ID` | For Telegram chat bot | Admin Telegram user ID for approval commands |

**n8n & Webhooks**

| Variable | Required | Description |
|---|---|---|
| `N8N_API_KEY` | For n8n injection | API key created in the n8n UI (Settings → API) |
| `NGROK_AUTHTOKEN` | For webhooks | ngrok auth token for external webhook tunneling |
| `NGROK_DOMAIN` | For webhooks | Your static ngrok domain |

**Gmail (OAuth2)**

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` | For Gmail | OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | For Gmail | OAuth2 client secret |

**File Upload**

| Variable | Required | Description |
|---|---|---|
| `UPLOAD_MAX_BYTES` | No | Max size per uploaded file in bytes (default: `20971520` = 20 MB) |
| `UPLOAD_MAX_FILES` | No | Max number of attachments per message (default: `5`) |
| `UPLOAD_TTL_HOURS` | No | Hours before uploaded files are auto-deleted; `0` = never (default: `24`) |

**Rate Limiting**

| Variable | Required | Description |
|---|---|---|
| `RATE_LIMIT_PER_HOUR` | No | Max requests per hour per user (default: `50`) |
| `RATE_LIMIT_PER_MINUTE` | No | Max requests per minute per user (default: `5`) |

**Context Management**

| Variable | Required | Description |
|---|---|---|
| `ARGOS_ENABLE_COMPACTION` | No | Set to `1` to enable Tier-2 structured compaction (LLM-based context summarisation) |
| `ARGOS_MC_TTL_MINUTES` | No | Minutes of idle time before a pre-emptive micro-compact fires (default: `60`) |
| `ARGOS_MICRO_COMPACT_KEEP` | No | Number of recent compactable messages preserved by micro-compact (default: `5`) |
| `ARGOS_SESSION_MEMORY_PATH` | No | Path for the session working-memory file (default: `.argos_session_memory.md`) |
| `ARGOS_SESSION_MEMORY_UPDATE_EVERY` | No | Tool calls between session-memory refreshes (default: `5`) |

**CLI**

| Variable | Required | Description |
|---|---|---|
| `MAX_TOOL_LOOPS` | No | Default max reasoning steps for the CLI (default: `10`; overridable via `--max-steps`) |

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

```bash
# Stateless — no memory between runs
python3 scripts/main.py

# Session memory — kept in RAM for the current session only
python3 scripts/main.py --session

# Persistent memory — uses pgvector RAG, shared with the Telegram bot
python3 scripts/main.py --memory

# One-shot mode — run a single prompt and exit
python3 scripts/main.py "summarise today's news"

# Attach files to a prompt
python3 scripts/main.py --attach report.pdf image.png

# Additional flags
#   --max-steps N   Max reasoning steps per task (default: 10, env: MAX_TOOL_LOOPS)
#   --user-id N     Override the auto-generated user ID
#   --debug         Enable verbose debug logging
```

Voice input is available when `ENABLE_VOICE=true` is set in `.env`.

### Web Dashboard

After deployment, the dashboard is available at [http://localhost:8000](http://localhost:8000).

It includes a chat terminal (SSE streaming), live Docker container monitor, CPU/RAM telemetry, and a security audit log.

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
n8n Orchestrator ────────────────►│         ├── Tool Registry (33 tools)
                                             ├── Context Management (micro-compact, session memory)
                                             ├── RAG Memory (pgvector / SQLite)
                                             └── Security Pipeline
```

**Infrastructure:**
- **PostgreSQL 17 + pgvector** — persistent storage and vector similarity search for RAG
- **SQLite WAL** — lightweight local fallback for development (selected via `DB_BACKEND=sqlite`)
- **Docker Socket Proxy** — sandboxed code execution in ephemeral containers (no host network, 128 MB RAM limit, read-only workspace)
- **OpenTelemetry + Jaeger** — distributed tracing (UI at [http://localhost:16687](http://localhost:16687))
- **ngrok** — exposes n8n webhooks to the internet via a static domain
- **GitHub Actions** — CI runs tests against both SQLite and PostgreSQL

For a detailed breakdown, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Tool Arsenal (33 tools)

| Category | Tools |
|---|---|
| **Code Execution** | `python_repl` (Docker sandboxed), `bash_exec` (Docker sandboxed) |
| **Document Parsing** | `read_pdf`, `read_csv`, `read_json`, `read_excel`, `read_file`, `query_table`, `analyze_image`, `transcribe_audio` |
| **Web & Search** | `web_search`, `web_scrape`, `download_file`, `get_weather` |
| **Browser Automation** | `browser_navigate`, `browser_click`, `browser_type`, `browser_get_content` |
| **Finance** | `crypto_price`, `finance_price` |
| **Filesystem** | `list_files`, `create_file`, `modify_file`, `rename_file`, `delete_file`, `create_directory`, `delete_directory` |
| **GUI Automation** | `visual_click`, `keyboard_type`, `launch_app`, `describe_screen` |
| **System** | `system_stats`, `search_tools` |

---

## Context Management

ARGOS uses a three-tier pipeline to keep the conversation context within the LLM token budget while preserving reasoning quality.

| Tier | Trigger | Mechanism | LLM call? |
|---|---|---|---|
| **Micro-compact** | >80 % of budget | Clears content of old tool results, WorldState snapshots, and raw JSON tool calls. Keeps the `ARGOS_MICRO_COMPACT_KEEP` most recent. | No |
| **Structured compaction** | >90 % of budget, ≥5 messages, `ARGOS_ENABLE_COMPACTION=1` | Calls the lightweight LLM to summarise the conversation into a 9-section structured summary. Replaces all history with 3 messages. Falls back silently on error. | Yes (lightweight model) |
| **Drop** | >100 % of budget | Drops the oldest non-system messages until the budget fits. Original behaviour, always available as last resort. | No |

Additional context features:
- **Time-based micro-compact**: if >`ARGOS_MC_TTL_MINUTES` of idle time pass since the last LLM call (cache TTL likely expired), micro-compact fires pre-emptively before the next call.
- **Session working memory**: every `ARGOS_SESSION_MEMORY_UPDATE_EVERY` tool calls, a background task writes a compact task-state summary to `.argos_session_memory.md` via the lightweight model. Injected into the next task's context to bridge consecutive sessions.
- **Tool RAG**: at the start of each task, only the top-12 most relevant tools (TF-IDF cosine similarity) are injected into the system prompt. The `search_tools` tool lets the model discover additional tools at runtime if it suspects it needs one not in its current context.
- **`<analysis>` scratchpad**: the planner schema allows the model to prepend an `<analysis>` block for chain-of-thought reasoning. It is stripped automatically before parsing and never reaches the user.
- **Post-compact cleanup**: after a structured compaction, git context cache and session memory are reset so stale derived state is not carried into the compacted history.

---

## Security

Key security settings in `.env`:

```env
# Internal API key — must be set before deploying. Used by the dashboard and n8n.
ARGOS_API_KEY=<generate a strong random string>

# Enables the LLM-based input validator on all entry points (adds latency)
ARGOS_PARANOID_MODE=false

# Bypasses API key auth entirely (local dev only — NEVER use in production)
ARGOS_PERMISSIVE_MODE=false

# Rate limiting (applies to both API and Telegram)
RATE_LIMIT_PER_HOUR=50
RATE_LIMIT_PER_MINUTE=5

# Docker sandbox (set automatically by docker-compose; override only for local dev)
DOCKER_HOST=tcp://argos-docker-proxy:2375
WORKSPACE_DIR=./workspace
```

Security layers:
1. **API Key Auth** — all endpoints require `X-ARGOS-API-KEY` (bypass with `ARGOS_PERMISSIVE_MODE` for local dev)
2. **Paranoid Judge** — optional LLM middleware that validates every input for prompt injection (`ARGOS_PARANOID_MODE`)
3. **Risk Scoring** — heuristic-based (regex + structural patterns) threat evaluation for memory inputs
4. **LLM Judge** — secondary model validates suspicious memories before storage (anti-poisoning)
5. **Rate Limiting** — atomic sliding-window quotas via PostgreSQL (no Redis required)
6. **Docker Sandbox** — code execution isolated in ephemeral containers via `docker-socket-proxy` (read-only workspace, no network, 128 MB RAM)
7. **Non-Root Container** — the API container runs as a restricted `argos` user
8. **Circuit Breaker** — `pybreaker` on API routes prevents thread pool saturation when LLM is down

---

## Troubleshooting

**Dashboard loads but shows no data**
The dashboard requires `ARGOS_API_KEY` to be set in `.env` and `VITE_ARGOS_API_KEY` to be set at build time. See [Full Setup → Build the dashboard](#2-build-the-dashboard).

**`inject_n8n.py` fails with connection error**
The script includes a built-in retry loop (30 attempts × 3s). If it still fails, check that n8n is healthy: `docker ps` should show `argos-n8n` as `healthy`.

**Telegram bot returns an error message**
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
