# ARGOS-2 Configuration Guide: `config.yaml` & `.env`

The configuration of ARGOS-2 is split between the dynamic `config.yaml` (behavioral) and the environment file `.env` (systemic).

---

## 📁 System Configuration (`.env`)

New environment variables control the global security and LLM behavior.

### `ARGOS_PARANOID_MODE` (Boolean: true|false)
- **Effect**: Master switch for the **Paranoid Judge** middleware. 
- **Usage**: Set to `true` to enable an independent LLM audit of all incoming text to the FastAPI backend.
- **Why**: Protects the core engine from prompt injection before the request even reaches the business logic.

### `LLM_BACKEND` (Enum: groq|openai-compatible|anthropic|ollama)
- **Effect**: Defines the provider for the `CoreAgent`.

---

## 📁 Behavioral Configuration (`config.yaml`)

The `config.yaml` is hot-reloadable. Changes are detected in real-time.

### 🧠 Core Engine Settings
The `core_agent` block defines how the brain processes tasks.

- **`max_steps`**: Maximum number of tool iterations per task (default: 10).
- **`planner_temperature`**: Creativity of the reasoning loop (default: 0.1 for precision).

---

### 🛡️ Security Pipeline (`security` block)

- **`risk_threshold`**: (Float 0.0-1.0). The maximum acceptable score from the heuristic risk engine. If exceeded, the task is blocked by the CoreAgent.
- **`enable_blocklist`**: If `true`, checks inputs against the regex patterns in `src/core/security.py`.

---

### 💬 Unified Memory (`memory` block)

Since the RAG memory is now unified, these settings apply to both the Telegram assistant and the CLI (when used with `--memory`).

- **`rag_similarity_threshold`**: (Float 0.0-1.0). Minimum cosine similarity required to inject a memory into the current prompt (Core: 0.70).
- **`max_memories_retrieved`**: Number of context chunks pulled from SQLite (default: 3).
- **`enable_memory_extraction`**: If `true`, the agent will extract long-term facts/preferences after a conversation turn.

---

### 📧 Gmail Assistant Configuration

- **`enabled`**: Master kill-switch for email processing.
- **`min_priority`**: Sets the notification threshold (`HIGH` > `MEDIUM` > `LOW` > `SPAM`).
- **`allowed_languages`**: Whitelist (e.g., `["it", "en"]`).

---

## 🛠️ Tool Authorization (CLI Gate)

Dangerous tools like `bash_exec` or `python_repl` are restricted by an interactive gate on the terminal. You cannot disable this via config for security reasons—it requires manual user confirmation for every powerful OS-level action.
