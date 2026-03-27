# ARGOS-2 Development: Extending the Agent

This document is for developers who want to add new capabilities to ARGOS, beyond the default Gmail assistant.

## 1. Adding New n8n Workflows
The easiest way to extend ARGOS is by using n8n's visual builder.
1. Create a new workflow in the n8n UI (`http://localhost:5678`).
2. Use the **HTTP Request** node to call the FastAPI backend (`http://argos-api:8000`).
3. If your workflow needs a custom tool, add it to `main.py` (see below).
4. Export your workflow as JSON and save it in the `workflows/` directory.

---

## 2. Adding Custom Tools to the Agent
Tools are the ways the agent interacts with the world. They are defined in `main.py`.

### Step 1: Define the Python Function
Create a function that performs the action (e.g., fetching weather, querying a database).
```python
def fetch_weather(location: str):
    """Fetches the current weather for a specific location."""
    # Your logic here
    return f"The weather in {location} is sunny."
```

### Step 2: Register the Tool
Add the function to the `Agent`'s tools dictionary in `main.py`.
```python
self.tools = {
    "fetch_weather": fetch_weather,
    # ...
}
```

### Step 3: Document the Tool in the System Prompt
Update the `SYSTEM_PROMPT` in `main.py` so the LLM knows when and how to call your new tool.

---

## 3. Modifying the API Endpoints
To add new REST endpoints, edit `api/server.py`.

### Example: Adding a Slack Webhook Listener
```python
@app.post("/slack_update")
async def slack_update(payload: dict):
    # Process the slack message
    return {"status": "ok"}
```

---

## 4. Testing & Contributions
- **Unit Tests**: Run tests using `pytest` in the `tests/` directory.
- **Linting**: We recommend using `ruff` or `flake8` for Python code consistency.
- **Docker Rebuilds**: If you change `requirements.txt` or the `Dockerfile`, remember to rebuild:
  ```bash
  docker compose up -d --build
  ```
