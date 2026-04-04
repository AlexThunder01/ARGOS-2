# 🛡️ ARGOS-2: Personal AI Linux Agent & Workflow Hub

**ARGOS-2** is an advanced agentic ecosystem built on a **Unified Core Engine** that bridges the gap between **visual workflow orchestration (n8n)** and **high-performance cognitive reasoning (FastAPI + Python)**.

Unlike traditional "chatbots", ARGOS features a **CoreAgent** architecture: a single, robust brain shared by the Linux Terminal, Telegram, and the n8n automation engine.

---

## ✨ Key Features (v2.2)

- **🧠 Unified CoreAgent Architecture**: A single cognitive engine (`src/core/`) handles all reasoning, planning, and memory. Whether you use the CLI, Telegram, or the Web Dashboard, you're talking to the same "brain."
- **🖥️ Command Center Dashboard**: A premium React web interface (Vite + Glassmorphism UI) with real-time SSE chat streaming, Docker container monitoring, and Rate Limit tracking.
- **💻 Power-User Linux CLI**: A rich Command Line Interface (`scripts/main.py`) with three memory modes:
  - **Stateless (default)**: Clean slate for every command.
  - **`--session`**: Ephemeral RAM-only memory for the current session.
  - **`--memory`**: Full persistent RAG memory (shared with Telegram).
- **⚙️ Advanced Reasoning Tools**: ARGOS wields 23 built-in tools, including:
  - **Code Interpreter (REPL)**: Executes Python code in a **Docker-isolated sandbox** (128MB RAM limit, no network).
  - **Document Parser**: Native reading of **PDF**, **CSV**, and **JSON** files.
  - **Web Scraper**: Converts any URL into readable text for deep analysis.
  - **OS Control**: Filesystem management, Bash execution, and GUI automation.
- **🛡️ 5-Layer Cognitive Security**:
  - **Paranoid Judge**: An LLM-based middleware that sanitizes every input.
  - **Risk Scoring**: Real-time evaluation of prompt-injection threats.
  - **Atomic Rate Limiting**: Database-native sliding window quotas (per-minute/per-hour) without Redis.
  - **Docker Sandbox Isolation**: Code execution in ephemeral containers via `docker-socket-proxy`.
  - **Interactive Security Gate**: Dangerous tools (bash, python, delete) always ask for `(y/N)` confirmation on the CLI.
- **💬 Telegram Agent with RAG**: A conversational assistant with long-term memory, whitelist-only access, and Admin Human-In-The-Loop (HITL) approvals.

---

## 🚀 Quickstart: Interaction Modes

### 1. The Linux Terminal (CLI)
Interact with ARGOS directly on your local machine.

```bash
# Basic stateless interaction
python3 scripts/main.py

# Interaction with persistent memory (Remembers you!)
python3 scripts/main.py --memory

# Temporary session memory
python3 scripts/main.py --session
```

### 2. The Server (Telegram & n8n)
Deploy the full stack at once:
```bash
docker compose up -d --build
python3 scripts/inject_n8n.py
```

### 3. The Web Dashboard
Access the Command Center at `http://localhost:8000/` after deployment.

For local development:
```bash
cd dashboard && npm install && npm run dev
```
The Vite dev server proxies API calls to FastAPI automatically.

---

## 🏗️ Architecture

ARGOS separates the **Nervous System** from the **Brain**:

- **The Body (n8n)**: Handles I/O, Gmail polling, and Telegram webhooks.
- **The Brain (CoreAgent)**: A modular FastAPI/Python backend that manages state, memory, and tool execution.
- **The Shield (Infrastructure)**:
  - **PostgreSQL 17 + pgvector**: Vector similarity search for RAG memory.
  - **Docker Socket Proxy**: Secure, isolated code execution in ephemeral containers.
  - **Atomic Rate Limiting**: Database-native sliding window quotas.
  - **OpenTelemetry + Jaeger**: Distributed tracing for full observability.
  - **GitHub Actions CI/CD**: Automated testing on SQLite + PostgreSQL matrices.
- **[Architecture Deep Dive](docs/ARCHITECTURE.md)**: How the CoreAgent unifies the experience.
- **[Technical Specification](docs/TECHNICAL_SPECIFICATION.md)**: Exhaustive HLD and Security protocols.

---

## 🛠️ Tool Arsenal (23 Tools)

| Category | Tools |
|:---|:---|
| **Code & Scripting** | `python_repl` (Docker sandboxed), `bash_exec` (Docker sandboxed) |
| **Documents** | `read_pdf`, `read_csv`, `read_json`, `read_file` |
| **Web & Search** | `web_search`, `web_scrape`, `crypto_price`, `finance_price` |
| **Filesystem** | `list_files`, `create_file`, `modify_file`, `delete_file`, `rename_file` |
| **Automation** | `visual_click`, `keyboard_type`, `launch_app`, `describe_screen` |
| **System** | `system_stats`, `get_weather` |

---

## 🛡️ Security Configuration

ARGOS-2 introduces a global **Paranoid Mode**. Edit your `.env`:

```env
# Enables the LLM security validator on all entry points
ARGOS_PARANOID_MODE=true

# Rate Limiting (API & Telegram protection)
RATE_LIMIT_PER_HOUR=50
RATE_LIMIT_PER_MINUTE=10

# Docker Sandbox Isolation
DOCKER_HOST=tcp://localhost:2375
WORKSPACE_DIR=./workspace
```

---

## 🛠️ Developer Documentation

- **[Development Guide](docs/DEVELOPMENT.md)**: Adding new tools, running tests, and dashboard development.
- **[Configuration Guide](docs/CONFIGURATION_GUIDE.md)**: Mastering `config.yaml`.
- **[Telegram RAG Spec](docs/TELEGRAM_MODULE_SPEC.md)**: How memory extraction works.

---
**Powered by n8n & Python ✨**