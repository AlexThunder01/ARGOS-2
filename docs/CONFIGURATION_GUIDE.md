# ARGOS-2 Configuration Guide: `config.yaml`

The `config.yaml` file is the central source of truth for your agent's behavior. It allows you to modify how ARGOS perceives and reacts to data without touching any code.

## 📁 File Structure
The file is located in the project root and is automatically mounted into the Docker container. Changes are detected and applied in real-time via a `watchdog` Python file watcher that safely updates the in-memory cache without requiring a container restart.

---

## 📧 Gmail Assistant Configuration

### `enabled` (Boolean)
- **Effect**: Master kill-switch. 
- **Usage**: Set to `false` to instantly stop the agent from processing any new emails or sending notifications.

### `filters` (Object)

#### `ignore_senders` (List)
- **Effect**: A list of glob/regex patterns.
- **Usage**: Emails from these addresses are strictly discarded at the API level.
- **Example**:
  ```yaml
  ignore_senders:
    - "*@newsletter.com"  # Ignores all newsletters
    - "noreply@*"         # Ignores automated system notifications
  ```

#### `allowed_languages` (List)
- **Effect**: Whitelist of ISO language codes.
- **Usage**: The LLM will check the primary language of the email. If it's not in this list, the priority is set to LOW and no draft is generated.
- **Example**: `["it", "en"]`

#### `min_priority` (Enum)
- **Effect**: Sets the minimum threshold for user notification.
- **Available Levels**: `HIGH` > `MEDIUM` > `LOW` > `SPAM`.
- **Behavior**:
  - `HIGH`: Only notifies you for urgent/critical emails.
  - `MEDIUM`: The default. Notifies for Medium and High. Silently ignores Low and Spam.
  - `SPAM`: Notifies for absolutely everything.

---

### `behavior` (Object)

#### `tone_of_voice` (String)
- **Effect**: Instructs the LLM on the persona to adopt.
- **Usage**: You can be extremely specific.
- **Example**: `"Empathetic customer support representative who uses emojis and is very polite."`

#### `custom_signature` (String)
- **Effect**: Appended to every draft response.
- **Usage**: Use `\n` for new lines.
- **Note**: This ensures transparency, letting the recipient know an AI participated in the draft.

#### `auto_discard_spam` (Boolean)
- **Effect**: Automatically drops emails the LLM classifies as SPAM.
- **Usage**: If `true`, these won't even appear in your "Ignored" logs inside n8n.

---

## 💬 Telegram Assistant Configuration

The `telegram_assistant` block controls the conversational agent and its memory system.

### `identity` (Object)
- **`persona`**: The core system prompt injected before every conversation. Defines how the agent thinks and acts.
- **`welcome_message`**: The text sent when a user types `/start`.
- **`unauthorized_message`**: The text sent to unapproved users while they wait for admin approval.

### `behavior` (Object)
- **`default_language`**: ISO code for the language to use if the user doesn't specify one (default: `it`).
- **`conversation_window`**: Number of recent messages to keep in the sliding window context.
- **`enable_memory_extraction`**: If `true`, the agent will extract long-term facts/preferences in the background and store them as embeddings.
- **`rag_similarity_threshold`**: (Float 0.0-1.0). Minimum cosine similarity required to inject a memory into the prompt. Higher means stricter memory matching.

### `memory` (Object: Cognitive Security)
- **`enable_poisoning_detection`**: If `true`, activates the 4-layer security pipeline (regex heuristics + LLM Judge) to protect the DB from prompt injection.
- **`risk_threshold`**: (Float 0.0-1.0). The maximum acceptable risk score before the system blocks the memory insertion.
- **`suspicious_retention`**: Number of suspicious memories to retain in the audit log for admin review before garbage collection.

### `admin` (Object)
- **`notify_on_new_user`**: If `true`, sends an InlineKeyboard approval message to the `ADMIN_CHAT_ID` when a new user types `/start`.
- **`auto_approve`**: If `true`, skips the whitelist and allows anyone on Telegram to use your LLM API limits. Use with extreme caution.
