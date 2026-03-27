# 🛡️ ARGOS-2: Autonomous AI Agent Framework (n8n + FastAPI)

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![n8n](https://img.shields.io/badge/n8n-Workflow_Automation-FF6B6B.svg?logo=n8n)](https://n8n.io/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED.svg?logo=docker)](https://www.docker.com/)

**ARGOS-2** is an advanced, hybrid agentic hub designed for intelligent and robust workflow automation. It couples the visual orchestration capabilities of the **n8n** engine with a high-performance cognitive backend powered by **FastAPI** (Python). 

---

## 🚀 The Core Philosophy: n8n meets Python AI

ARGOS-2 is **not just an email bot**—it is a completely decoupled architectural framework.

By separating the **"Nervous System"** (n8n for routing I/O API events) from the **"Brain"** (FastAPI for LLM reasoning, code execution, and persistent queues), ARGOS gives you the ultimate sandbox. You can use n8n's visual builder to catch Shopify orders, listen to Slack channels, or read Google Sheets, and seamlessly delegate the cognitive heavy-lifting to the ARGOS Python API.

👉  **[Read the Guide: How to build custom n8n Workflows for ARGOS-2](docs/n8n_custom_workflows.md)**

---

## 🎯 Reference Implementation: Human-In-The-Loop (HITL) Automation

To demonstrate the sheer power of this decoupled architecture, ARGOS natively ships with a **fully integrated Customer Service proxy showcase**. 

This reference implementation handles emails autonomously while maintaining a mandatory standard of human review:

1. **Reading and Analysis**: ARGOS monitors the Gmail inbox in real-time. Upon receiving a new email, it extracts the content and queries the LLM (via FastAPI) to generate a categorized Summary (High/Medium/Low priority) and a structured HTML **Draft Response**.
2. **Telegram Webhooks**: Utilizing n8n's native Telegram nodes coupled with secure Ngrok tunneling, the summary and the draft are instantly pushed to a private chat with **Inline Keyboard Buttons** (`✅ SEND`, `❌ DISCARD`).
3. **Seamless Zero-Latency Approval**: Interacting with the buttons triggers an immediate Callback Query. n8n intercepts the payload, atomically destructs the email context from the FastAPI queue, and autonomously replies to the origin Gmail thread while dynamically updating the Telegram UI to prevent duplicate clicks.

### 🔥 Engineering Solutions to Technical Constraints
- **Race Conditions in Asynchronous Queues**: Since n8n processes array batches concurrently, asynchronous clicks on disjointed Telegram messages ran the risk of overwriting memory variables. The pending state queue was offloaded to a designated key-value micro-database (RAM/Disk Dictionary) written in pure Python and exposed via `REST DELETE /pending_email/{message_id}`.
- **File System (FS) Security**: Containerized n8n instances inherently prevent arbitrary Host OS file manipulation. All n8n nodes were intentionally decoupled, communicating securely via internal HTTP requests to the repository's ASGI Uvicorn ecosystem.

---

## 🏗️ Architecture & Structure

```bash
📂 agente/
├── 🐋 docker-compose.yml       # Orchestration for n8n + Python API + Ngrok
├── 🐋 Dockerfile               # FastAPI backend build configuration
├── 🐍 api/server.py            # Microservices & REST Endpoints (LLM / State Queue)
├── 🐍 main.py                  # Core Agent logic (Reasoning Loop & Tool Execution)
├── 🐍 inject_n8n.py            # CLI Injector (Deploys workflows seamlessly to n8n)
├── 🐍 clear_n8n.py             # CLI Cleaner (Hard-resets n8n user space)
└── ⚙️ workflows/               # Pre-configured JSON Workflow Blueprints
    ├── 03_gmail_analizzatore_hitl.json
    └── 04_gmail_webhook_approval.json

### 🛡️ Production Hardening (v2.0)
The framework has been hardened for secure remote deployment:
- **API Security**: Mandatory `X-ARGOS-API-KEY` header authentication for all sensitive endpoints.
- **Docker Security**: Containers run as a **non-root user** (`argos`) with minimal privileges.
- **Monitoring**: Built-in `/health` and `/metrics` endpoints for uptime and task tracking.
- **Persistence**: Log files and n8n data are persisted via Docker volumes.
```

---

## ⚖️ Dual Execution Modes

ARGOS is architected with a bifurcated design to handle two distinct operational environments:

1. **Dockerized Headless Mode (Production Automation)**
   - **Components**: `n8n` + `argos-api` (FastAPI) + `ngrok`.
   - **Use Case**: Server-side workflow orchestration, Gmail processing, LLM generation, and Telegram HITL operations.
   - **Note**: No GUI dependencies are required. The system runs autonomously in the background and is fully containerized.

2. **Local Desktop Mode (Experimental Automation)**
   - **Components**: `main.py` executed natively on the host Linux machine.
   - **Use Case**: Deep system control, GUI automation (`visual_click`, `keyboard_type`), and VLM Vision interactions.
   - **Note**: Containerized environments inherently lack access to the host OS display. To utilize GUI-bound visual tools, ARGOS must be run directly on the host rather than via Docker.

---

## 🚀 Quickstart: Zero-Touch Deploy

You can launch the entire agentic hub and inject the fully functional workflows on your local machine in under 5 minutes using **Docker** and our zero-touch deployer.

### 1. Environment Variables Configuration
Clone the repository and duplicate the environment template file:
```bash
cp .env.example .env
```
Populate the `.env` file with your base credentials:
- `TELEGRAM_BOT_TOKEN="your_telegram_token"` & `TELEGRAM_CHAT_ID="your_telegram_chat_id"`
- `GOOGLE_CLIENT_ID="your_client_id"` & `GOOGLE_CLIENT_SECRET="your_client_secret"` (from Google Cloud Console)
- `GROQ_API_KEY="gsk_yourkey"` *(Required for high-speed Llama/Qwen frameworks)*
- `NGROK_AUTHTOKEN="your_ngrok_token"` *(Required for exposing local Webhooks to Telegram)*
- `NGROK_DOMAIN="your_static_domain"` *(e.g., your-domain.ngrok-free.app)*

### 2. Container Initialization
Start the Docker orchestrator to execute the architecture in detached mode:
```bash
docker compose up -d --build
```

### 3. Automated Workflow Injection
ARGOS ships with a zero-touch pipeline that automatically creates n8n credentials, patches JSON workflows with your unique IDs, injects them via REST API, and activates them.

1. **Create Account**: Open `http://localhost:5678` and create your initial admin account.
2. **Setup API Key**: Inside n8n, navigate to **Settings > API**, generate a new API Key, and append it to your `.env` file as `N8N_API_KEY="<your_token>"`.
3. **Inject**: Run the setup script locally:
   ```bash
   pip install -r requirements.txt
   python3 inject_n8n.py
   ```
4. **Register Webhooks**: Restart the n8n container to force the routing table to register your new webhook URLs:
   ```bash
   docker restart argos-n8n
   ```

### 4. Gmail OAuth2 Authorization
Google strictly requires manual user consent for email access.
1. Open n8n at `http://localhost:5678`.
2. Navigate to **Credentials** -> **Gmail account**.
3. Click **Sign in with Google** to complete the OAuth flow.

> 🎉 **Done!** Send an email to your inbox and you will immediately receive the AI analysis and approval interface on your Telegram app.

---

## 🔮 Future Scope (v3.0)

While ARGOS currently operates over secure Ngrok tunnels for optimal webhook latency, further production-grade upgrades could include:

- **Stateless API Backend**: Decoupling the `pending_emails` queue from FastAPI's volatile RAM and migrating it to a robust in-memory datastore like **Redis**. This facilitates horizontal auto-scaling and state preservation across node reboots.

---
**Powered by n8n & Python ✨**