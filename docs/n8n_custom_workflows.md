# 🔌 Guide: Creating Custom n8n Workflows for ARGOS-2

One of the greatest advantages of the **ARGOS-2** architecture is the ability to use the n8n visual engine to create any automation imaginable (Telegram, Google Sheets, Trello, etc.) while delegating the AI reasoning and computational heavy-lifting to the ARGOS Python backend.

Here is how to create a custom workflow from scratch and interface it with the ARGOS brain.

---

## 🏗️ 1. Create your n8n Trigger
Every automation begins with a Trigger.
1. Open **n8n** (`http://localhost:5678`).
2. Click **"Add Workflow"** in the top right.
3. Add the initial Trigger node. Examples:
   - **Schedule Trigger**: To run the agent every morning at 09:00 AM.
   - **Telegram Trigger**: To trigger ARGOS by typing a message in a chat.
   - **Webhook**: To trigger the agent via a custom HTTP call.

---

## 🧠 2. Delegate to ARGOS-2 (HTTP Request Node)
Once triggered, you need to instruct ARGOS on what to do. Since ARGOS and n8n share the same Docker bridge network (`argos-network`), they communicate natively and instantly via internal HTTP requests.

1. Add an **"HTTP Request"** node to your workflow.
2. Configure it as follows:
   - **Method**: `POST`
   - **URL**: `=http://argos-api:8000/analyze_email`
   - **Send Body**: `ON`
   - Select **Specify Body** -> **JSON**
3. In the **Body Parameters**, paste the JSON payload to trigger the agent:

```json
{
  "task": "The objective you want ARGOS to accomplish",
  "require_confirmation": false,
  "max_steps": 15
}
```

> 💡 **PRO Tip**: Make the `task` dynamic! For example, if your trigger is a Telegram message, you can map the task directly to the user's input: `=Search the internet for this: {{ $json.message.text }}`.

---

## 🎯 3. Handle the ARGOS Response
The `/analyze_email` endpoint processes tasks **Synchronously**. This means the HTTP Request node will wait (loading state) until ARGOS completes the entire cognitive loop (reading, prioritizing, summarizing, and drafting the final text).

Upon completion, ARGOS returns a JSON payload containing the final result, for example:
```json
{
  "status": "success",
  "result": "I searched the internet, Google's 2025 revenue was..."
}
```

1. Add a subsequent node (e.g., **Telegram** "Send Message" or **Google Sheets** "Add Row") after the HTTP Request.
2. Extract the result dynamically by dragging the `result` variable into your desired field. n8n will map it natively as:
   `={{ $('HTTP Request').item.json.result }}`

You have just created a hybrid agent: **n8n routes the data, while ARGOS handles the cognitive reasoning!**

---

## 📦 4. Bundled Workflows (Ready to Test)

To see this decoupled architecture in a powerful real-world scenario, ARGOS-2 natively includes **two pre-built workflows** (located in the `workflows/` directory) designed for intelligent email management:

1. **`03_gmail_analizzatore_hitl.json`**: Automatically intercepts incoming emails, delegates reading/summarization/drafting to the Python LLM backend, and notifies you securely on Telegram using Inline Keyboard Buttons (`✅ SEND`, `❌ DISCARD`).
2. **`04_gmail_webhook_approval.json`**: Acts as the zero-latency Webhook receiver for the Telegram buttons. Upon clicking, the Python API atomically extracts the draft from the persistent FIFO queue and executes the Gmail reply, while dynamically editing your Telegram message to prevent duplicate clicks.

**How to Test Them:** Run the `inject_n8n.py` script and ensure you've configured your Gmail OAuth2 Credentials within the n8n UI!
