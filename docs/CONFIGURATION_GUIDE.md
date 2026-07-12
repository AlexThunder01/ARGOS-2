# ARGOS-2 Configuration Guide: `config.yaml` & `.env`

The configuration of ARGOS-2 is split between the dynamic `config.yaml` (behavioral, hot-reloadable) and the environment file `.env` (systemic, requires restart).

---

## 📁 System Configuration (`.env`)

Environment variables control global infrastructure and security behavior.

### LLM Backend

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BACKEND` | `openai-compatible` | Provider type: `openai-compatible` or `anthropic`. Ollama works via `openai-compatible`. |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | OpenAI-compatible API endpoint |
| `LLM_API_KEY` | *(none)* | Primary API key for the LLM provider |
| `LLM_API_KEY_2` | *(none)* | Secondary API key (automatic rotation on rate limits) |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Model name for the primary reasoning LLM |
| `LLM_LIGHTWEIGHT_MODEL` | `llama-3.1-8b-instant` | Model for background tasks (memory extraction) |
| `LLM_TIMEOUT_S` | `300` | HTTP timeout in seconds for LLM calls |
| `ANTHROPIC_MAX_TOKENS` | `4096` | Max tokens for Anthropic API responses |

### Vision

| Variable | Default | Description |
|----------|---------|-------------|
| `VISION_BASE_URL` | *(falls back to `LLM_BASE_URL`)* | Vision LLM endpoint |
| `VISION_API_KEY` | *(falls back to `LLM_API_KEY`)* | Vision LLM API key |
| `VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Vision model name |

### Embeddings (RAG Memory)

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_BASE_URL` | `https://api.groq.com/openai/v1` | Embeddings API endpoint |
| `EMBEDDING_API_KEY` | *(none)* | Embeddings API key |
| `EMBEDDING_MODEL` | `nomic-embed-text-v1.5` | Embedding model name |
| `EMBEDDING_DIM` | `768` | Embedding vector dimensions. Must match the model output. |

> **Docker note**: if `EMBEDDING_BASE_URL` points at a local server (e.g. Ollama on `localhost:11434`), remember that `localhost` inside the `argos-api` container refers to the container itself, not the host. Use `http://host.docker.internal:11434/v1` instead — this requires both `extra_hosts: ["host.docker.internal:host-gateway"]` in `docker-compose.yml` (Linux doesn't auto-map this, unlike Docker Desktop) and the local server actually bound to more than `127.0.0.1` (e.g. `OLLAMA_HOST=0.0.0.0`). Same class of issue as `N8N_BASE_URL` (see the main [README](../README.md)).

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_BACKEND` | `postgres` | `sqlite` for local dev or `postgres` for production |
| `DATABASE_URL` | `postgresql://argos:argos_secret@argos-db:5432/argos` inside Docker; `postgresql://argos:argos_secret@localhost:5433/argos` from the host (docker-compose publishes Postgres on host port **5433**, not 5432) | PostgreSQL connection string |

> **Docker note**: if you also run the CLI on the host with SQLite, leave `DB_BACKEND` unset in `.env` rather than setting it to `sqlite`. `docker-compose.yml`'s `argos-api` service only falls back to its own `DB_BACKEND=postgres` default when the variable is completely unset — Compose's `${VAR:-default}` syntax applies the default only when `VAR` is unset, not when it's set to a non-empty value like `sqlite`. An explicit `sqlite` in `.env` leaks into the container too, silently disabling persistent RAG memory there.

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `ARGOS_API_KEY` | *(none)* | Shared secret for dashboard and n8n authentication |
| `ARGOS_PARANOID_MODE` | `false` | Enables the LLM-based Paranoid Judge middleware on all API inputs |
| `ARGOS_PERMISSIVE_MODE` | `false` | Bypasses API key auth entirely (**local dev only**) |
| `RATE_LIMIT_PER_HOUR` | `50` | Max API requests per user per hour |
| `RATE_LIMIT_PER_MINUTE` | `5` | Max API requests per user per minute |

### Docker Sandbox

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKER_HOST` | `tcp://localhost:2375` | Docker socket proxy URL |
| `WORKSPACE_DIR` | `./workspace` | Path to the shared workspace directory |
| `HOST_WORKSPACE_DIR` | *(falls back to `WORKSPACE_DIR`)* | Host-side path for Docker volume mount |
| `DOCKER_EXEC_MEM_LIMIT` | `128m` | Memory limit for sandbox containers |
| `DOCKER_EXEC_TIMEOUT` | `30` | Execution timeout in seconds |

### CoreAgent

| Variable | Default | Description |
|----------|---------|-------------|
| `ARGOS_MAX_STEPS` | `20` | Maximum tool execution steps per task |
| `MAX_HISTORY_TOKENS` | `8000` | Token budget for conversation history trimming |

---

## 📁 Behavioral Configuration (`config.yaml`)

The `config.yaml` is hot-reloadable via `watchdog`. Changes are detected in real-time without restarting the server.

### 💬 Telegram Chat Module (`telegram_assistant` block)

**Identity:**
- `bot_name`: Display name for the bot
- `persona`: System prompt personality description
- `welcome_message`: First message to approved users
- `unauthorized_message`: Message for unapproved users

**Behavior:**
- `conversation_window`: Number of recent messages to include in context (default: `20`)
- `max_memories_retrieved`: Number of RAG memory chunks to retrieve per query (default: `3`)
- `rag_similarity_threshold`: Minimum cosine similarity for memory retrieval (default: `0.70`). Applies to the Telegram interface only; the CLI CoreAgent uses a hardcoded `0.25` threshold in `src/core/memory.py`.
- `max_input_length`: Maximum input message length in characters (default: `4000`)
- `enable_memory_extraction`: If `true`, the agent extracts long-term facts after conversations (default: `true`)

**Memory Security:**
- `enable_poisoning_detection`: Enables the 4-layer anti-poisoning pipeline (default: `true`)
- `risk_threshold`: Maximum risk score (0.0–1.0) before facts are blocked (default: `0.5`)
- `suspicious_retention`: How many suspicious entries to keep in the audit log (default: `500`)

**Admin:**
- `auto_approve`: If `true`, new users are auto-approved (default: `false`)
- `notify_on_new_user`: Send approval request to admin chat (default: `true`)

**Rate Limiting:**
- `max_messages_per_day`: Daily cap per user. `0` = unlimited.
- `max_messages_per_hour`: Hourly cap per user. `0` = unlimited.

### 📧 Gmail Assistant (`gmail_assistant` block)

- `enabled`: Master kill-switch for email processing
- `min_priority`: Notification threshold (`HIGH` > `MEDIUM` > `LOW` > `SPAM`)
- `allowed_languages`: Whitelist (e.g., `["it", "en"]`)
- `tone_of_voice`: Style for generated draft responses
- `custom_signature`: Appended to every drafted email
- `auto_discard_spam`: If `true`, low-priority/spam emails are auto-discarded without HITL

---

## 🛠️ Tool Authorization (CLI Gate)

Tools with `risk` level of `medium`, `high`, or `critical` (as defined in their `ToolSpec`) are restricted by an interactive gate on the terminal. The user must confirm each execution with `(y/N)`. This cannot be disabled via config for security reasons.

In API mode, these tools are auto-blocked unless a confirmation callback is provided.
