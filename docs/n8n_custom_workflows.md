# Custom n8n Workflows for ARGOS-2

By using the n8n visual orchestrator, you can extend the reach of ARGOS-2 beyond its built-in modules.

---

## 1. Interacting with the Unified Brain

All communication between n8n and the cognitive engine is done via the **HTTP Request** node calling the FastAPI backend.

### 🧩 The Primary Endpoint: `POST /run`

When building a custom workflow (e.g., a Slack listener, a Cron job), send the user's task to this endpoint:

- **URL**: `http://argos-api:8000/api/v1/agent/run`
- **Method**: `POST`
- **Body (JSON)**:
  ```json
  {
    "task": "Extract the key points from this meeting...",
    "user_id": "optional_id",
    "memory_mode": "off" 
  }
  ```

---

## 2. Advanced Reasoning Features in n8n

Custom workflows can now leverage the **Advanced Tools** built into the `CoreAgent`.

### 📄 Analyzing PDF Attachments
If n8n receives a PDF via a webhook (e.g., from a form submission):
1. Use the **Write to File** node to save the PDF in a shared volume (e.g., `/tmp/argos/`).
2. Call the `POST /run` endpoint with the task: `"Process and summarize this file: /tmp/argos/report.pdf"`.
3. The `CoreAgent` will automatically trigger the `read_pdf` tool, extract the text, and return the result to n8n.

---

## 3. Human-In-The-Loop (HITL) Patterns

The most powerful n8n workflows implement the **HITL Sequence**:

1. **Trigger**: New event (Email, Webhook).
2. **Brain Call**: `POST /analyze_email` or `POST /run`.
3. **Suspension**: n8n sends a message to the Telegram HITL bot with **Inline Buttons**.
4. **Resume**: User clicks "Accept," and n8n executes the final action (e.g., Send Reply, Call API).

---

## 4. Security Requirements

Every request from n8n to the FastAPI backend must include the **API Key Header**:
- **Key**: `X-ARGOS-API-KEY`
- **Value**: Your `.env` configured key.

If you are sending user-generated text from a public source, the **Paranoid Judge** middleware will automatically validate it if enabled in your `.env`. No extra n8n configuration is required for this protection.
