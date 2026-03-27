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
