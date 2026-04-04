# ARGOS-2 Telegram Chat Module — Technical Specification

**Version:** 1.2 (Unified Architecture Revision)
**Date:** 2026-04-03
**Status:** Implemented (Phase 1 & 3 complete)

---

## 1. Executive Summary

This document specifies the integration of the **Telegram Chat Module**, which provides a persistent, conversational AI surface for ARGOS-2. Since v2.1, the reasoning and memory engine have been unified under the `CoreAgent` architecture, meaning the Telegram module is a thin interface over the core engine.

---

## 2. System Architecture: Unified Brain

The module follows a **Body-Brain** pattern using the unified `src/core/` package.

- **Body (n8n):** Handles the Telegram Webhook, performs media checks, and routes text to the API.
- **Brain (FastAPI + CoreAgent):** Handles authentication, memory retrieval, and LLM reasoning.

### 2.1 The Memory Promotion
Crucially, the RAG memory system (embeddings, sliding window, and extraction) has been promoted from the Telegram-specific module to `src/core/memory.py`. 
- **Shared Memory**: If enabled, the Linux CLI and Telegram share the same SQLite vector store, allowing for a cross-platform memory experience.

---

## 3. Data Flow: Converged Logic

### 3.1 Conversational Reasoning
1. **Webhook**: Incoming Telegram message (text-only).
2. **FastAPI (`api/routes/telegram.py`)**: Sanitizes input and authenticates the user.
3. **CoreAgent Engine**: 
   - Retrieves the last 20 messages (Sliding Window).
   - Retrieves top-3 relevant memories from `tg_memory_vectors` (Cosine Similarity).
   - Constructs the system prompt (Persona + Profile).
   - Executes the tool-equipped reasoning loop (Advanced Tools).
4. **Memory Extraction**: A background task analyzes the final turn to extract new facts or preferences.

---

## 4. Advanced Reasoning Tools in Chat

The Telegram assistant now has access to the same 23-tool arsenal as the CLI, including:
- **`web_search` & `web_scrape`**: To answer real-time questions and read links.
- **`read_pdf` & `read_csv`**: To analyze documents sent to the assistant.
- **`python_repl`**: To perform precise mathematical and data operations.

---

## 5. Security Model: Multi-Layer Defense

1. **Whitelist Auth**: Access is restricted to `approved` users in the `tg_users` table.
2. **Admin HITL**: New users trigger an approval message to the `ADMIN_CHAT_ID`.
3. **Paranoid Mode**: All Telegram messages are audited by the `paranoid_guard` LLM middleware.
4. **Input Sanitization**: Length validation (max 4000 chars) and regex blocklisting.

---

## 6. Implementation Notes

The module is built on **SQLite in WAL Mode** and uses the `requests` library for model-agnostic LLM calls (Groq, OpenAI, Anthropic, or local). All behavioral logic (tone, context window, RAG similarity) is hot-reloadable via `config.yaml`.
