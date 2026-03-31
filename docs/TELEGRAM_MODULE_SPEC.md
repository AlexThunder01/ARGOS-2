# ARGOS-2 Telegram Chat Module — Technical Specification

**Version:** 1.1 (Revised)
**Date:** 2026-03-28
**Status:** Approved for Implementation
**Scope:** Design and implementation of a public Telegram chat module with persistent RAG memory, integrated into the ARGOS-2 framework.

---

## 1. Executive Summary

This document specifies the integration of a **public Telegram chat module** into ARGOS-2. The module extends the system's capabilities by adding a conversational AI surface accessible to third-party users, governed by an **admin-managed whitelist**.

### Objectives

- Expose a public Telegram bot that responds in natural language via a configurable LLM (Cloud/Local)
- Implement per-user persistent memory with RAG (Retrieval-Augmented Generation) capabilities
- Maintain strict separation between the chat bot and the existing HITL email bot
- Build on the existing Docker Compose stack without additional containers in homelab
- Design for future VPS migration with zero application-code refactoring

### Design Principles

- **Zero new containers in homelab** — everything runs in the existing Docker ecosystem
- **Architectural coherence** — same Brain-Body Split pattern already present in ARGOS-2
- **Hot-configurability** — every behavioral parameter is modifiable via `config.yaml` at runtime
- **Separation of concerns** — chat bot and HITL bot are distinct Telegram instances with distinct n8n workflows

---

## 2. System Architecture

### 2.1 High-Level Design

The module follows the same **Brain-Body Split** pattern:

- **Body (n8n):** receives Telegram messages via Webhook, performs routing, manages the HTTP sequence
- **Brain (FastAPI):** handles user authentication, memory retrieval, prompt construction, LLM calls, and memory updates

```
[Telegram User]
       │
       │  HTTPS (Telegram API)
       ▼
[Telegram Servers]
       │
       │  Webhook HTTP POST
       ▼
[Ngrok Tunnel] ──► [n8n :5678]
                        │
                   Routing & Type Check
                        │
              ┌─────────┴──────────┐
              │                    │
         [Text msg]          [Non-text msg]
              │                    │
              ▼                    ▼
    [FastAPI :8000          [n8n → Telegram
    POST /telegram/chat]     "Text only for now"]
              │
    ┌─────────┼─────────────┐
    │         │             │
 [SQLite   [LLM Provider  [SQLite
  Memory]  LLM API]      Write-back]
    │                       │
    └───────────────────────┘
              │
              ▼
    [FastAPI → n8n Response]
              │
              ▼
    [n8n → Telegram sendMessage]
```

### 2.2 Container Topology

No new containers are added in homelab. The module uses:

| Container | Role | Modification |
|---|---|---|
| `argos-api` | New endpoint `/telegram/chat` | Python code addition |
| `argos-n8n` | New Telegram workflow | New workflow JSON |
| `argos-ngrok` | Tunnel already active | None |

The existing SQLite database (`argos_state.db`) is extended with new tables. No new Docker volumes.

### 2.3 Telegram Bot Separation

| Bot | Purpose | Token | n8n Workflow |
|---|---|---|---|
| Existing (HITL) | Email notifications, approve/discard buttons | `TELEGRAM_BOT_TOKEN` | `03_gmail_analizzatore_hitl.json` |
| **New (Chat)** | Public LLM conversation | `TELEGRAM_CHAT_BOT_TOKEN` | `05_telegram_chat.json` (new) |

The two bots operate on distinct tokens, distinct webhooks, and distinct n8n workflows. They share no state or routing. A message to the HITL bot never reaches the chat workflow and vice versa.

---

## 3. Data Flow

### 3.1 Standard Message Flow (authorized user)

```
User: "Hey, remember that I prefer short answers"
   │
   ▼
[Telegram Servers]
   │  POST https://{ngrok}/webhook/<uuid-chat>
   ▼
[n8n Webhook Trigger]
   │  Extracts: {chat_id, user_id, text, first_name}
   │  Checks: message.text exists? (non-text → fallback reply)
   ▼
[n8n HTTP Request]
   │  POST http://argos-api:8000/telegram/chat
   │  Header: X-ARGOS-API-KEY: {key}
   │  Body: {user_id, chat_id, text, first_name, username}
   ▼
[FastAPI /telegram/chat]
   │
   ├─► [Input Validation] len(text) <= max_input_length? (default 4000 chars)
   │
   ├─► [SQLite] SELECT * FROM tg_users WHERE user_id = ?
   │      → user found, status = 'approved' ✓
   │
   ├─► [SQLite] SELECT * FROM tg_user_profiles WHERE user_id = ?
   │      → {name, language, tone, ...}
   │
   ├─► [SQLite] SELECT * FROM tg_conversations
   │            WHERE user_id = ? ORDER BY ts DESC LIMIT 20
   │      → last 20 messages (sliding window)
   │
   ├─► [Embeddings API] embed(text)
   │      → float vector[DIM]
   │
   ├─► [SQLite] SELECT * FROM tg_memory_vectors WHERE user_id = ?
   │            → all user vectors
   │            → cosine_similarity(query_vec, stored_vecs) in numpy
   │            → top-3 relevant memories above threshold
   │
   ├─► [Prompt Builder] build_telegram_system_prompt(...)
   │
   ├─► [LLM API] chat completion (e.g. Llama-3.3, Claude-3.5, etc.)
   │      messages: [system, ...history, user]
   │      → text response
   │
   ├─► [SQLite] INSERT INTO tg_conversations (user + assistant turns)
   │
   ├─► [Debounced Memory Extraction — Background Task]
   │      Only runs if: msg_count_total % 5 == 0 OR len(text) > 100
   │      Uses: llama-3.1-8b-instant (lightweight model)
   │      → extracts key facts → embeds → UPSERT into tg_memory_vectors
   │
   └─► [Memory GC — Background Task, every 50 messages]
          Prunes memories with access_count == 0 AND age > 30 days
          Enforces hard cap: max 500 memories per user (drops lowest accessed)
   │
   ▼
[FastAPI] return {reply: "Got it! I'll keep responses concise.", ...}
   │
   ▼
[n8n] Telegram sendMessage(chat_id, reply)
```

### 3.2 Access Request Flow (unauthorized user)

```
New user: "/start"
   │
   ▼
[FastAPI POST /telegram/chat]
   │
   ├─► [SQLite] user_id not found
   ├─► [SQLite] INSERT INTO tg_users (status='pending')
   ├─► [Background] Notify admin via HITL bot:
   │     "New access request:\nID: {user_id}\nName: {first_name}"
   │     [InlineKeyboard: ✅ Approve | ❌ Deny]
   │
   └─► return {status: "pending", reply: "Access request registered..."}
```

### 3.3 Non-Text Message Handling

> **Critical fix**: The n8n workflow MUST handle non-text messages (photos, stickers, voice, location, etc.) **before** calling FastAPI. If `message.text` is null/undefined, n8n replies directly: *"Per ora supporto solo messaggi di testo. 📝"* — no HTTP call to FastAPI is made. This prevents Pydantic validation errors on the backend.

---

## 4. Database Schema

All tables are added to the existing `argos_state.db`. All operations use the WAL connection already configured.

### 4.1 `tg_users`

```sql
CREATE TABLE IF NOT EXISTS tg_users (
    user_id         INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'banned')),
    registered_at   TEXT NOT NULL DEFAULT (datetime('now')),
    approved_at     TEXT,
    approved_by     INTEGER,
    banned_at       TEXT,
    ban_reason      TEXT,
    msg_count_today INTEGER DEFAULT 0,
    msg_count_total INTEGER DEFAULT 0,
    last_seen       TEXT,
    last_daily_reset TEXT DEFAULT (date('now'))
);
CREATE INDEX IF NOT EXISTS idx_tg_users_status ON tg_users(status);
```

> **Fix**: Added `last_daily_reset` column. The `msg_count_today` counter is lazily reset: on each incoming message, if `last_daily_reset != date('now')`, the counter resets to 0 and the date is updated. No external cron job needed.

### 4.2 `tg_user_profiles`

```sql
CREATE TABLE IF NOT EXISTS tg_user_profiles (
    user_id         INTEGER PRIMARY KEY
                    REFERENCES tg_users(user_id) ON DELETE CASCADE,
    display_name    TEXT,
    language        TEXT DEFAULT 'it',
    preferred_tone  TEXT DEFAULT 'neutral',
    custom_prefs    TEXT DEFAULT '{}',
    updated_at      TEXT DEFAULT (datetime('now'))
);
```

### 4.3 `tg_conversations`

```sql
CREATE TABLE IF NOT EXISTS tg_conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL
                    REFERENCES tg_users(user_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    token_count     INTEGER,
    ts              TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tg_conv_user_ts
    ON tg_conversations(user_id, ts DESC);
```

> **Change**: Removed `embedding BLOB` from conversations table. Embeddings are only stored in the dedicated `tg_memory_vectors` table. Conversation rows are for sliding window context only — embedding every single message would consume unnecessary API tokens/compute for zero retrieval benefit.

### 4.4 `tg_memory_vectors`

```sql
CREATE TABLE IF NOT EXISTS tg_memory_vectors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL
                    REFERENCES tg_users(user_id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    embedding       BLOB NOT NULL,
    category        TEXT DEFAULT 'general'
                    CHECK(category IN ('preference','fact','task','interest','general')),
    source_turn_id  INTEGER,
    confidence      REAL DEFAULT 1.0,
    access_count    INTEGER DEFAULT 0,
    last_accessed   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tg_mem_user ON tg_memory_vectors(user_id);
```

### 4.5 `tg_tasks`

```sql
CREATE TABLE IF NOT EXISTS tg_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL
                    REFERENCES tg_users(user_id) ON DELETE CASCADE,
    description     TEXT NOT NULL,
    due_at          TEXT,
    status          TEXT DEFAULT 'open'
                    CHECK(status IN ('open', 'done', 'cancelled')),
    created_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_tg_tasks_user_status
    ON tg_tasks(user_id, status);
```

---

## 5. Memory System

### 5.1 Layer 1 — Sliding Window (Recent Context)

On each request, the last `N` messages are retrieved and injected into the LLM history.

```python
MAX_WINDOW_MESSAGES = 20    # Configurable via config.yaml
MAX_WINDOW_TOKENS   = 4000  # Safety limit to prevent context overflow

def get_conversation_window(user_id: int, db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path, timeout=10)
    rows = conn.execute(
        "SELECT role, content, token_count FROM tg_conversations "
        "WHERE user_id = ? ORDER BY ts DESC LIMIT ?",
        (user_id, MAX_WINDOW_MESSAGES)
    ).fetchall()
    conn.close()
    rows = list(reversed(rows))  # Chronological order
    total_tokens = 0
    trimmed = []
    for role, content, tokens in rows:
        total_tokens += (tokens or len(content) // 4)
        if total_tokens > MAX_WINDOW_TOKENS:
            break
        trimmed.append({"role": role, "content": content})
    return trimmed
```

### 5.2 Layer 2 — RAG with Configurable Embeddings

Long-term memories use embeddings from the configured provider (OpenAI-compatible or local) and cosine similarity computed in Python with `numpy`.

```python
GROQ_EMBEDDINGS_URL = "https://api.groq.com/openai/v1/embeddings"
EMBEDDING_MODEL = "nomic-embed-text-v1.5"
EMBEDDING_DIM = 768

def get_embedding(text: str) -> np.ndarray:
    response = requests.post(
        GROQ_EMBEDDINGS_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={"model": EMBEDDING_MODEL, "input": text},
        timeout=10
    )
    response.raise_for_status()
    return np.array(response.json()["data"][0]["embedding"], dtype=np.float32)
```

### 5.3 Debounced Memory Extraction

> **Critical improvement**: Memory extraction does NOT run on every message. It triggers only when:
> 1. `msg_count_total % 5 == 0` (every 5th message), OR
> 2. `len(text) > 100` (long messages are more likely to contain facts)
>
> This reduces LLM/Embedding API calls by ~70% compared to extracting on every turn. Short messages like "ok", "thanks", "yes" are never analyzed.

```python
def should_extract_memory(user_msg: str, msg_count: int) -> bool:
    if len(user_msg) > 100:
        return True
    if msg_count % 5 == 0:
        return True
    return False
```

The extraction LLM prompt explicitly instructs the model to return an empty array when there's nothing worth remembering.

### 5.4 Memory Garbage Collection

> **Critical addition**: Without GC, the memory table grows unbounded, degrading cosine similarity scan performance.

```python
MAX_MEMORIES_PER_USER = 500
GC_STALE_DAYS = 30
GC_EVERY_N_MESSAGES = 50

def gc_memories(user_id: int, db_path: str):
    """Prunes stale and excess memories for a user."""
    conn = sqlite3.connect(db_path, timeout=10)
    # 1. Delete never-accessed memories older than GC_STALE_DAYS
    conn.execute(
        "DELETE FROM tg_memory_vectors "
        "WHERE user_id = ? AND access_count = 0 "
        "AND created_at < datetime('now', ?)",
        (user_id, f'-{GC_STALE_DAYS} days')
    )
    # 2. Enforce hard cap: keep only top MAX_MEMORIES_PER_USER by access_count
    conn.execute(
        "DELETE FROM tg_memory_vectors WHERE user_id = ? AND id NOT IN ("
        "  SELECT id FROM tg_memory_vectors WHERE user_id = ? "
        "  ORDER BY access_count DESC, created_at DESC "
        "  LIMIT ?"
        ")",
        (user_id, user_id, MAX_MEMORIES_PER_USER)
    )
    conn.commit()
    conn.close()
```

GC triggers as a background task every `GC_EVERY_N_MESSAGES` messages per user.

---

## 6. Access Control & Whitelist

### 6.1 Access Model

```
Incoming message
        │
  user_id in tg_users?
    NO ──► INSERT status='pending' → "awaiting approval" → notify admin
   YES ──► status == 'approved'  → process message
        ── status == 'pending'   → "still waiting"
        ── status == 'banned'    → silence (no reply, no LLM call)
```

### 6.2 Admin Management via Telegram

The admin manages approvals directly from Telegram through the **existing HITL workflow** (new branch). When a new user requests access, the admin receives an InlineKeyboard notification with `✅ Approve` and `❌ Deny` buttons. Additional admin commands:

| Command | Action |
|---|---|
| `/ban_<user_id>` | Bans an approved user |
| `/unban_<user_id>` | Removes a ban |
| `/list_pending` | Lists pending users |
| `/stats` | System aggregate statistics |

### 6.3 Security Properties

- `user_id` is immutable and not modifiable by the user — used for auth
- `username` is informational only (can change, never used for auth decisions)
- No auto-approval by default — every user requires manual admin approval
- Banned users' messages are logged but never processed (zero LLM calls)

---

## 7. Bot Commands

| Command | Description | Available to |
|---|---|---|
| `/start` | Start session, show welcome message | All |
| `/help` | Show available commands | Approved |
| `/reset` | Clear current session context (sliding window) | Approved |
| `/status` | Access status, message count, saved memories | Approved |
| `/deleteme` | **Two-step**: requires `/deleteme CONFIRM` | Approved |
| `/language <code>` | Change response language (e.g. `/language en`) | Approved |
| `/tone <formal\|casual\|neutral>` | Change response tone | Approved |
| `/name <name>` | Set preferred display name | Approved |
| `/tasks` | List open tasks | Approved |

> **Critical fix**: `/deleteme` requires the user to type `/deleteme CONFIRM` explicitly. Without the confirmation keyword, the bot responds: *"⚠️ This will permanently delete ALL your data. Type `/deleteme CONFIRM` to proceed."* This prevents accidental data loss.

> **Improvement**: Task creation is handled implicitly by the LLM. When the user says "remind me to call the doctor tomorrow", the memory extraction LLM tags it as `category='task'` and the system inserts it into `tg_tasks`. No explicit `/addtask` command is needed — the conversation is the interface.

---

## 8. `config.yaml` Extension

```yaml
# ==============================================================================
# TELEGRAM CHAT BOT — Public Chat Module Configuration
# ==============================================================================

telegram_assistant:
  enabled: true

  identity:
    bot_name: "ARGOS"
    persona: >
      You are an intelligent and precise AI assistant. You are curious, direct,
      and value clarity. You don't use empty courtesy phrases.
      When you don't know something, you admit it without hesitation.
    welcome_message: >
      Hello! I'm ARGOS, your personal AI assistant.
      I can remember our previous conversations and adapt
      to your preferences over time. How can I help?
    unauthorized_message: >
      Hello! This bot is invite-only.
      Your access request has been registered.
      You'll receive a notification when approved.

  behavior:
    default_language: "it"
    default_tone: "neutral"
    conversation_window: 20
    max_memories_retrieved: 3
    rag_similarity_threshold: 0.70
    max_conversation_history: 200
    enable_memory_extraction: true
    max_input_length: 4000

  limits:
    max_messages_per_day: 0    # 0 = unlimited
    max_messages_per_hour: 0

  admin:
    notify_on_new_user: true
    auto_approve: false
```

All parameters are hot-reloadable via the existing `watchdog` file watcher.

---

## 9. FastAPI Endpoints

### 9.1 `POST /telegram/chat` — Main conversational endpoint

**Request:**
```json
{
  "user_id": 123456789,
  "chat_id": 123456789,
  "text": "Remember I prefer short answers",
  "first_name": "Alessandro",
  "username": "alex"
}
```

**Response:**
```json
{
  "status": "ok",
  "reply": "Got it! I'll keep responses concise.",
  "user_id": 123456789,
  "memories_used": 2,
  "is_new_user": false
}
```

Status values: `ok` | `unauthorized` | `pending` | `banned` | `disabled`

**Key implementation detail**: The endpoint validates `len(text) <= max_input_length` and returns a 400 error if exceeded.

### 9.2 `POST /telegram/admin/approve` / `POST /telegram/admin/ban`

Protected by `X-ARGOS-API-KEY` + `admin_chat_id` verification against `ADMIN_CHAT_ID` env var.

### 9.3 `GET /telegram/admin/users?status=pending`

Returns list of users filtered by status.

### 9.4 `/metrics` Extension

Adds: `telegram_messages_total`, `telegram_users_approved`, `telegram_users_pending`, `telegram_memories_total`.

---

## 10. New Method: `JarvisAgent.think_with_messages()`

> **Critical addition**: The existing `think()` method uses `self.history` internally. The Telegram module needs to pass an externally-constructed history (with per-user system prompts and RAG-injected context). This requires a new method:

```python
# Added to src/agent.py → class JarvisAgent

def think_with_messages(self, messages: list[dict]) -> str:
    """Executes a single LLM inference with an externally-provided message history.
    Used by the Telegram chat module where each user has their own context."""
    try:
        if self.backend == "groq":
            return self._call_groq_with_messages(messages)
        else:
            return self._call_ollama_with_messages(messages)
    except Exception as e:
        return f"LLM Error: {e}"

def _call_groq_with_messages(self, messages: list[dict], retries=0) -> str:
    """LLM API call with external message history and key rotation."""
    from .config import GROQ_API_KEY, GROQ_API_KEY2
    current_key = GROQ_API_KEY2 if (retries % 2 != 0 and GROQ_API_KEY2) else GROQ_API_KEY
    headers = {"Authorization": f"Bearer {current_key}", "Content-Type": "application/json"}
    payload = {"model": self.model, "messages": messages, "temperature": 0.3}
    try:
        response = requests.post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=30)
        if response.status_code == 429:
            if retries < 3:
                if retries % 2 == 0 and GROQ_API_KEY2:
                    return self._call_groq_with_messages(messages, retries + 1)
                else:
                    import time
                    time.sleep(5 * (retries + 1))
                    return self._call_groq_with_messages(messages, retries + 1)
            return "Error: Groq Rate Limit exceeded."
        if response.status_code != 200:
            return "API Error."
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Connection Error: {e}"
```

> **Note**: Temperature is set to `0.3` (not `0.0` like the agentic loop) to allow slightly more creative conversational responses.

---

## 11. n8n Workflow Structure

### 11.1 `05_telegram_chat.json` Node Flow

```
[Telegram Trigger (Chat Bot)]
        │
        ▼
[Switch — message.text exists?]
   ├── YES ──► [HTTP Request → POST /telegram/chat]
   │              │
   │              ▼
   │         [Switch — response.status]
   │            ├── "ok"       ──► [sendMessage(reply)]
   │            ├── "pending"  ──► [sendMessage(unauthorized_msg)]
   │            ├── "banned"   ──► [NoOp — silence]
   │            ├── "disabled" ──► [sendMessage("Bot disabled")]
   │            └── error      ──► [sendMessage("Temporary error")]
   │
   └── NO (photo/sticker/voice/etc.)
              ──► [sendMessage("I only support text messages for now 📝")]
```

### 11.2 Webhook Registration

The webhook path is a UUID generated by n8n's Telegram Trigger node (not a custom path). This is the correct n8n v2.x behavior — the path will be `/webhook/<uuid>` and n8n handles the Telegram `setWebhook` call automatically upon workflow activation.

---

## 12. Implementation Phases

### Phase 0 — Prerequisites (1h)
- [ ] Create new bot on BotFather, save token in `.env` as `TELEGRAM_CHAT_BOT_TOKEN`
- [ ] Add `ADMIN_CHAT_ID` to `.env`
- [ ] Add `numpy==1.26.4` to `requirements.txt`
- [x] Verify Embeddings API availability

### Phase 1 — Database (2h)
- [ ] Create `src/db/migrations/001_telegram_module.py` with all 5 tables
- [ ] Run migration and verify tables/indexes
- [ ] Create `src/telegram/db.py` with all helper functions

### Phase 2 — Memory System (3h)
- [ ] Create `src/telegram/memory.py` (embedding, RAG, sliding window, debounced extraction, GC)
- [ ] Write unit tests in `tests/test_telegram_memory.py`
- [ ] Test the full cycle: save → embed → retrieve → GC

### Phase 3 — FastAPI Endpoints (3h)
- [ ] Extend `src/workflows_config.py` with telegram properties
- [ ] Add `telegram_assistant` block to `config.yaml`
- [ ] Create `src/telegram/prompt.py` with system prompt builder
- [ ] Implement `handle_command()` with `/deleteme CONFIRM` safety
- [ ] Add `think_with_messages()` to `src/agent.py`
- [ ] Add all endpoints to `api/server.py`
- [ ] Test endpoints with `curl`

### Phase 4 — n8n Workflow (2h)
- [ ] Create `workflows/05_telegram_chat.json` with media-type routing
- [ ] Extend `inject_n8n.py` for new credential + workflow injection
- [ ] Extend HITL workflow with admin approval InlineKeyboard branch
- [ ] Test webhook registration

### Phase 5 — End-to-End Testing (2h)
- [ ] Test: new user → pending → admin approve → first message
- [ ] Test: multi-session memory persistence (second session remembers first)
- [ ] Test: commands `/reset`, `/language`, `/tone`, `/deleteme CONFIRM`
- [ ] Test: banned user → silence
- [ ] Test: `enabled: false` → disabled response
- [ ] Test: non-text message → direct fallback reply (no FastAPI call)
- [ ] Test: hot-reload `config.yaml` → behavior change without restart

---

## 13. New Files & Modified Files

### New Files
```
src/telegram/__init__.py
src/telegram/db.py           # SQLite helpers for Telegram module
src/telegram/memory.py       # Embeddings, RAG, sliding window, GC
src/telegram/prompt.py       # build_telegram_system_prompt()
src/db/migrations/001_telegram_module.py
workflows/05_telegram_chat.json
tests/test_telegram_memory.py
```

### Modified Files
```
api/server.py                # +4 endpoints, /metrics update
src/agent.py                 # +think_with_messages()
src/workflows_config.py      # +telegram_assistant properties
config.yaml                  # +telegram_assistant block
.env / .env.example          # +TELEGRAM_CHAT_BOT_TOKEN, +ADMIN_CHAT_ID
requirements.txt             # +numpy==1.26.4
inject_n8n.py                # +chat bot credential + workflow 05 injection
```

### New Dependencies
```
numpy==1.26.4    # Cosine similarity for RAG
```

All other dependencies are already present in the project.

---

## 14. Architectural Decisions & Rationale

### Why a separate bot instead of extending the existing one
The HITL bot has state-specific callbacks (`approve|msg_id`, `discard|msg_id`). Mixing it with free-text routing would create ambiguity in n8n and make debugging much harder. Separation costs nothing (two BotFather tokens, two n8n entries) and preserves architectural clarity.

### Why SQLite and not Redis for memory
Redis would be faster for frequent lookups, but adds a container and its management overhead. With `--workers 1` and WAL mode, SQLite handles the load of a personal/whitelist bot. Migration to PostgreSQL + `pgvector` is planned for VPS scaling (documented in the VPS migration section of the original spec).

### Why remote embeddings vs local models
While local embedding models (`sentence-transformers`) can be used (e.g. via Ollama), cloud providers offer extremely high-performance models like `nomic-embed-text` with <100ms latency at negligible cost, preserving local RAM.

### Why cosine similarity in Python via numpy
`sqlite-vec` requires C compilation and Docker complexity. With numpy and a maximum of ~500 vectors per user (enforced by GC), linear scan is <50ms. Migration to `pgvector` with HNSW indexing is planned for VPS.

### Why debounced memory extraction
Running a secondary LLM call on every message would double API usage. With the debounce strategy (every 5th message + long messages), API calls are reduced by ~70% while still capturing the important facts.

---

*End of specification — version 1.1 (Revised)*
