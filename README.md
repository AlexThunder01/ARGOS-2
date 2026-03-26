# 🛡️ ARGOS - AI Agent Framework (n8n + FastAPI)

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![n8n](https://img.shields.io/badge/n8n-Workflow_Automation-FF6B6B.svg?logo=n8n)](https://n8n.io/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED.svg?logo=docker)](https://www.docker.com/)

**ARGOS** is an autonomous hybrid agentic hub designed for intelligent and robust workflow automation. It couples the visual orchestration capabilities of the **n8n** visual engine with a high-performance cognitive backend developed in **FastAPI** (Python).

---

## 🚀 The Core Philosophy: n8n meets Python AI
ARGOS-2 is **not just an email bot**—it is a completely decoupled overarching framework.

By separating the "Nervous System" (n8n for routing I/O API events) from the "Brain" (FastAPI for LLM reasoning, visual actions, and persistent Queues), ARGOS gives you the ultimate sandbox. You can use n8n's visual builder to catch Shopify orders, listen to Slack channels, or read Google Sheets, and delegate the cognitive heavy-lifting to the ARGOS Python API.

👉 [Read the guide: How to build custom n8n Workflows for ARGOS](docs/n8n_custom_workflows.md)

---

## 🎯 Reference Implementation: Human-In-The-Loop (HITL) Gmail Automation
To demonstrate the sheer power of this decoupled architecture, ARGOS natively ships with a **fully integrated Customer Service proxy showcase**.

1. **Reading and Analysis**: ARGOS monitors the Gmail inbox in real-time. Upon receiving a new email, it extracts the content and queries the LLM (via FastAPI) to generate a categorized Summary (High/Medium/Low priority) and an HTML **Draft Response**.
2. **Telegram Webhooks**: Utilizing n8n's native Telegram nodes coupled with secure Ngrok tunneling, the draft is instantly pushed to a private chat with **Inline Keyboard Buttons** (`✅ SEND`, `❌ DISCARD`).
3. **Seamless Zero-Latency Approval**: Interacting with the buttons triggers an immediate Callback Query. n8n intercepts the payload, atomically destructs the context from the FastAPI queue, and autonomously replies to the origin Gmail thread while dynamically updating the Telegram UI to prevent duplicate clicks.

### 🔥 Engineering Solutions to Technical Constraints
*   **Absence of Public Webhook/HTTPS:** The HITL module in n8n was re-engineered leveraging Telegram API's long polling technique (`getUpdates`), intercepting `callback_query` events (inline buttons) while resolving subsequent `409 Conflict` errors via synchronous state consumption within the JavaScript nodes.
*   **Race Conditions in Asynchronous Queues:** Since n8n processes array batches concurrently, asynchronous clicks on disjointed Telegram messages ran the risk of overwriting memory variables. The pending state queue was offloaded to a designated key-value micro-database (RAM/Disk Dictionary) written in pure Python and exposed via **REST DELETE /pending_email/{message_id}**.
*   **File System (FS) Security**: Containerized n8n instances inherently prevent arbitrary Host OS file manipulation. All n8n nodes were intentionally decoupled, communicating securely via internal HTTP requests to the repository's ASGI Uvicorn ecosystem.

---

## 🏗️ Architecture & Structure
```bash
📂 agente/
├── 🐋 docker-compose.yml       # Orchestration for n8n + Python API
├── 🐋 Dockerfile               # FastAPI backend build configuration
├── 🐍 api/server.py            # Microservices & REST Endpoints (LLM / State Queue)
├── 🐍 main.py                  # Core Agent logic (LangGraph / LangChain)
├── 🐍 inject_n8n.py            # CLI Injector (Deploys workflows seamlessly to n8n)
├── 🐍 clear_n8n.py             # CLI Cleaner (Hard-resets n8n user space)
└── ⚙️ workflows/               # Pre-configured JSON Workflow Blueprints
    ├── 03_gmail_analizzatore_hitl.json
    └── 04_gmail_webhook_approval.json
```

---

## ⚖️ Dual Execution Modes (Headless vs. GUI)

ARGOS is architected with a bifurcated design to handle two distinct operational environments:

1. **Dockerized Headless Mode (Production Automation)**
   * **Components**: `n8n` + `argos-api` (FastAPI).
   * **Use Case**: Server-side workflow orchestration, Gmail processing, LLM generation, and Telegram HITL polling.
   * **Note**: No GUI dependencies are required. The system runs autonomously in the background and is fully containerized.

2. **Local Desktop Mode (Experimental Automation)**
   * **Components**: `main.py` executed natively on the host machine.
   * **Use Case**: Deep system control, GUI automation (`visual_click`, `keyboard_type`), and VLM Vision interactions.
   * **Note**: Containerized environments inherently lack access to the host OS display. To utilize GUI-bound tools, ARGOS must be run directly on the host (Linux/Xorg) rather than via Docker.

---

## 🚀 Quickstart (One-Click Deploy)

You can launch the entire agentic hub on your local machine in under exactly 3 minutes using **Docker**.

### 1. Environment Variables Configuration
Clone the repository and navigate into the root directory. Duplicate the environment template file:
```bash
cp .env.example .env
```
Populate the `.env` file with your minimum base credentials:
*   `TELEGRAM_BOT_TOKEN="your_telegram_token"`
*   `GROQ_API_KEY="gsk_yourkey"` (Required for high-speed Llama/Qwen frameworks)

### 2. Container Initialization
Start the Docker orchestrator to execute the entire architecture in detached mode. The required n8n and Python images will initialize dynamically.
```bash
docker compose up -d --build
```
*   **n8n UI**: `http://localhost:5678`
*   **ARGOS API**: `http://localhost:8000/docs` (Interactive Swagger UI)

### 3. Workflow Injection
Once the servers are online, the n8n database will be initially empty. Access the n8n dashboard (`Settings > API`), generate a new API Token, and append it to your `.env` file under: `N8N_API_KEY="<your_token>"`.

Execute the automated injection suite (requires local Python environment or shell execution within the Python container):
```bash
pip install -r requirements.txt
python3 clear_n8n.py
python3 inject_n8n.py
```

### 4. OAuth2 Configuration (Gmail)
1. Access n8n (`http://localhost:5678`), and navigate to `Credentials`.
2. Authorize a new **Gmail OAuth2 API** credential set.
3. Bind the credential to the `New Email Received`, `Gmail: Mark As Read` and `Gmail: Reply` nodes within the newly imported workflows to grant inbox read/write permissions.

---

## 🔮 Future Architecture (v2.0)

While ARGOS currently operates over secure Ngrok tunnels for optimal webhook latency, further production-grade upgrades could include:

- **Stateless API Backend**: Decoupling the `pending_emails` queue from FastAPI's volatile RAM and migrating it to a robust in-memory datastore like **Redis**. This facilitates horizontal auto-scaling and state preservation across node reboots.

---
**Powered by n8n & Python ✨**