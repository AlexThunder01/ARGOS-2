# 🛡️ ARGOS-2: Professional Agentic Workflow Framework

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![n8n](https://img.shields.io/badge/n8n-Workflow_Automation-FF6B6B.svg?logo=n8n)](https://n8n.io/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED.svg?logo=docker)](https://www.docker.com/)

**ARGOS-2** is an enterprise-grade agentic hub that bridges the gap between **visual workflow orchestration (n8n)** and **high-performance cognitive reasoning (FastAPI + Python)**. 

Unlike traditional "chatbots", ARGOS is a decoupled architecture designed for reliable, scalable, and human-in-the-loop automation.

---

## 📑 Table of Contents
- [🚀 Quickstart](#-quickstart)
- [🏗️ Architecture](#️-architecture)
- [🎛️ Configuration](#️-configuration)
- [📧 Reference Implementation: Gmail HITL](#-reference-implementation-gmail-hitl)
- [🛠️ Developer Documentation](#️-developer-documentation)

---

## 🚀 Quickstart: Deploy in 2 Minutes

ARGOS is fully containerized. You can go from zero to a live, AI-powered Gmail assistant in minutes.

### 1. Configure the Environment
```bash
cp .env.example .env
# Open .env and populate:
# - GROQ_API_KEY (Your LLM brain)
# - TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID (Your UI)
# - NGROK_AUTHTOKEN & NGROK_DOMAIN (Your secure tunnel)
```

### 2. Launch the Orchestrator
```bash
docker compose up -d --build
```

### 3. Inject AI Workflows
Once the containers are healthy, run the automated injector:
```bash
pip install -r requirements.txt
python3 inject_n8n.py
```

### 4. Authorize Google
1. Open n8n at `http://localhost:5678`.
2. Go to **Credentials** -> **Gmail account** -> **Sign in with Google**.

---

## 🏗️ Architecture
ARGOS separates the **Nervous System** from the **Brain**:
- **[Technical Specification](docs/TECHNICAL_SPECIFICATION.md)**: Exhaustive HLD architecture, Sequence Flow diagrams, and Data Models.
- **[Architecture Deep Dive](docs/ARCHITECTURE.md)**: How n8n communicates with Python.
- **[Cognitive Backend](api/server.py)**: The FastAPI server handling reasoning and state queues.

---

## 🎛️ Configuration
All agent behavior is controlled via a centralized YAML file. No code changes required to change the agent's persona or filtering rules.
- **[Configuration Guide](docs/CONFIGURATION_GUIDE.md)**: mastering the `config.yaml` file.

```yaml
gmail_assistant:
  enabled: true
  filters:
    min_priority: "MEDIUM"  # Ignore LOW/SPAM automatically
  behavior:
    tone_of_voice: "professional yet empathetic"
```

---

## 📧 Reference Implementation: Gmail HITL
ARGOS ships with a production-ready showcase of **Human-In-The-Loop (HITL)** email management.
- **Automatic Analysis**: LLM prioritizes and summarizes incoming emails.
- **Telegram Webhooks**: Instant UI cards for mobile approval.
- **Atomic Operations**: Secure queue management prevents duplicate replies.

---

## 🛠️ Developer Documentation
Want to build your own tools or integrate Slack, Shopify, or custom logic?
- **[Development Guide](docs/DEVELOPMENT.md)**: Extending the agent.
- **[Custom n8n Workflows](docs/n8n_custom_workflows.md)**: How to build for ARGOS.

---

## 🔮 Future Roadmap (v3.0)
- **Redis Queue**: Moving the state from RAM/Disk to Redis for horizontal scaling.
- **Multimodal Vision**: Native support for analyzing images/PDFs in Gmail via VLM.
- **Voice Response**: Auto-generating audio summaries of your inbox.

---
**Powered by n8n & Python ✨**