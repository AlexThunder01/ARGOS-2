# 🛡️ ARGOS-2: Personal AI Linux Agent & Workflow Hub

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![n8n](https://img.shields.io/badge/n8n-Workflow_Automation-FF6B6B.svg?logo=n8n)](https://n8n.io/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED.svg?logo=docker)](https://www.docker.com/)
[![Coverage](https://img.shields.io/badge/Coverage-36%25-green.svg)](https://pytest.org/)

**ARGOS-2** is an advanced agentic hub that bridges the gap between **visual workflow orchestration (n8n)** and **high-performance cognitive reasoning (FastAPI + Python)**. 

Unlike traditional "chatbots", ARGOS features a decoupled **Brain-Body architecture** designed for reliable, scalable, and secure automation.

---

## ✨ Key Features (v2.0)

- **🧠 Brain-Body Split Architecture**: n8n handles all I/O and routing (the Body), while a dedicated Python/FastAPI backend handles LLM reasoning, state management, and memory (the Brain).
- **💻 Interactive Linux Terminal**: A rich command-line interface (CLI) powered by `rich` for direct local interaction, real-time logging, and system monitoring directly from your Linux terminal without needing a messaging app.
- **⚙️ Native Linux Agent**: ARGOS is not just a chat bot; it acts as a local system agent. It can execute bash commands, manage local files, parse system logs, and autonomously assist with Linux server management via the sandboxed Python reasoning engine.
- **💬 Telegram Agent with RAG Memory**: A fully functional conversational assistant with persistent, long-term memory. It uses configurable embeddings (OpenAI-compatible or local) and cosine similarity to remember user preferences, facts, and tasks over time.
- **🛡️ 4-Layer Cognitive Security**: Protection against prompt injection and data poisoning via regex blocklists, regex heuristics, conversational anomaly detection, and a dedicated paranoid LLM Judge.
- **📧 Gmail HITL (Human-In-The-Loop)**: Automatic email analysis and prioritization with Telegram push notifications for one-tap approvals.
- **⚡ Production Hardened**: Thread-local SQLite connection pooling, modular tool architecture, and a test suite with 101 passing tests (mocked network, in-memory DB fixtures).

---

## 🎯 Why ARGOS-2? (The Architectural Philosophy)

Most AI chatbots exist in a vacuum. ARGOS is built to act on the real world by solving three core engineering challenges:

### 1. The Cloud Orchestrator (n8n Fusion)
Writing boilerplate Python code to handle OAuth2 flows, API rate limits, polling loops, and webhook parsing is a tedious nightmare. **ARGOS solves this through complete n8n fusion.** 
n8n acts as the system's *sensory and motor cortex*: it connects to Gmail, listens to Telegram webhooks, and handles deterministic routing. Once data is cleaned and structured, n8n fires a precise payload to the Python FastAPI backend (The Brain). 
This **Brain-Body Split** means if you decide to migrate your assistant from Telegram to Slack tomorrow, you only swap out one visual node in n8n—*zero Python code changes are required.*

### 2. The Local Powerhouse (Linux System Agent)
ARGOS isn't trapped in the cloud. While it serves external users via messaging apps, it grants the owner full **Agentic OS Control** locally on Linux. 
Using a beautifully formatted command-line interface powered by `rich`, you can interact with ARGOS directly from your Linux terminal. Because the Python backend runs locally, it wields an arsenal of native tools: it can navigate your directories, read and write to your local filesystem, execute complex bash pipelines, analyze system logs, and write code. It acts as an autonomous system administrator and developer assistant rolled into one, directly integrated into your Linux environment.

### 3. Solving Real-World Asynchrony
How does an AI reply to a Telegram user regarding an email it analyzed 10 minutes ago? ARGOS implements an atomic SQLite state queue in WAL mode. This guarantees thread-safety and allows the system to pause workflows, await Human-In-The-Loop approvals on mobile, and resume execution deterministically. 

### 4. Robust Cognitive Defense
Public-facing AI agents are vulnerable to prompt injection. ARGOS doesn't just pass user input to the LLM; it routes it through a **4-Layer Cognitive Security pipeline**. A paranoid LLM Judge sanitizes inputs before they are allowed to enter the RAG vector database, preventing long-term behavioral poisoning.

---

## 📑 Table of Contents
- [🚀 Quickstart](#-quickstart)
- [🏗️ Architecture](#️-architecture)
- [🎛️ Configuration](#️-configuration)
- [🛠️ Developer Documentation](#️-developer-documentation)

---

## 🚀 Quickstart: Deploy in 2 Minutes

ARGOS is fully containerized. You can go from zero to a live, memory-augmented Telegram assistant in minutes.

### 1. Configure the Environment
Clone the repository and prepare your environment file:
```bash
cp .env.example .env
```
Open the `.env` file and configure your preferred AI provider. ARGOS-2 is **model-agnostic** and natively supports Anthropic or any OpenAI-compatible API. 

**Example (Using Groq for blazing fast inference):**
```env
LLM_BACKEND=openai-compatible
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_your_groq_api_key_here
LLM_MODEL=llama-3.3-70b-versatile
```
*(Check `.env.example` for OpenAI, Anthropic, vLLM, and Ollama templates).*

You will also need to populate your messaging credentials:
- `TELEGRAM_BOT_TOKEN`: The token for your primary/admin bot (from BotFather).
- `TELEGRAM_CHAT_BOT_TOKEN`: The token for the conversational AI bot.
- `ADMIN_CHAT_ID`: Your personal Telegram User ID to receive access requests.

### 2. Launch the Orchestrator
Start the FastAPI Cognitive Backend and the n8n automation engine:
```bash
docker compose up -d --build
```

### 3. Bootstrap AI Workflows
Once the Docker containers are healthy and running, run the automated injector script. This will automatically configure n8n with the correct Telegram webhook registrations, internal API keys, and ARGOS workflows:
```bash
python3 scripts/inject_n8n.py
```

### 4. Authorize Google (Optional, for Gmail HITL)
If you rely on the Gmail Human-In-The-Loop reading features:
1. Open n8n at `http://localhost:5678`.
2. Go to **Credentials** -> **Gmail account** -> **Sign in with Google**.

---

## 🏗️ Architecture

ARGOS separates the **Nervous System** from the **Brain**:

- **[Architecture Deep Dive](docs/ARCHITECTURE.md)**: How n8n communicates with Python securely.
- **[Telegram RAG Module Spec](docs/TELEGRAM_MODULE_SPEC.md)**: Details on the sliding-window context, debounced memory extraction, vectors, and Garbage Collection.
- **[Technical Specification](docs/TECHNICAL_SPECIFICATION.md)**: Exhaustive HLD architecture, Sequence Flow diagrams, and Data Models.

### Security Model
- **Non-Root Execution**: Containers run as a restricted `argos` user.
- **Internal Isolation**: The FastAPI backend is never exposed to the public internet. n8n acts as the only API Gateway.
- **Admin Approval**: The Telegram bot is whitelist-only. New users trigger an approval workflow sent to the `ADMIN_CHAT_ID`.

---

## 🎛️ Configuration

All agent behavior is controlled via a centralized, hot-reloadable YAML file. Avoid hardcoding prompts!

- **[Configuration Guide](docs/CONFIGURATION_GUIDE.md)**: Mastering the `config.yaml` file.

```yaml
telegram_assistant:
  enabled: true
  identity:
    bot_name: "ARGOS"
    persona: "You are a stark, precise AI assistant. You value clarity."
  behavior:
    default_language: "it"
    rag_similarity_threshold: 0.70
    max_memories_retrieved: 3
    enable_memory_extraction: true
```

---

## 🛠️ Developer Documentation

Want to build your own tools or integrate new platforms?

- **[Development Guide](docs/DEVELOPMENT.md)**: Extending the Python backend, adding new modular tools, and writing tests.
- **[Custom n8n Workflows](docs/n8n_custom_workflows.md)**: How to build custom n8n branches that interact with the FastAPI brain.

### Running Tests
ARGOS uses `pytest` with an in-memory database and mocked network dependencies for deterministic CI/CD:
```bash
pip install -r requirements.txt
pytest tests/ -v --cov=src --cov=api --cov-report=term-missing
```

---

## 🔮 Future Roadmap (v3.0)
- **PostgreSQL + pgvector**: Migrating off SQLite for horizontal scaling and HNSW indexing.
- **Multimodal Vision**: Native support for analyzing images/PDFs in incoming chats.
- **WhatsApp Integration**: Expanding the Body surface area beyond Telegram and Gmail.

---
**Powered by n8n & Python ✨**