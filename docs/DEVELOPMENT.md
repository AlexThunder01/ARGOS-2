# ARGOS-2 Development: Extending the Unified Agent

This document is for developers who want to extend ARGOS-2's capabilities beyond the defaults.

---

## 1. Modular Tool Architecture

Tool development is now highly modular. Tools are organized by function in `src/tools/`.

### Step 1: Create a Tool Module
Find the appropriate submodule in `src/tools/` (e.g., `code_exec.py`, `documents.py`, `web.py`) or create a new one.

```python
def my_custom_tool(inp: dict):
    """
    Brief description.
    Input: {"param": "value"}
    """
    # Logic here
    return "Result string"
```

### Step 2: Register the Tool
Add the function to the `TOOLS` registry in `src/tools/__init__.py`.

```python
from .my_tools import my_custom_tool

TOOLS = {
    "my_custom_tool": my_custom_tool,
    # ...
}
```

### Step 3: Update reasoning engine (Optional)
If the tool is powerful (e.g., deletes files, executes code), add its name to `self._dangerous_tools` in `src/core/engine.py`. This ensures it's protected by the CLI security gate.

---

## 2. Extending the CoreAgent

The `CoreAgent` (`src/core/engine.py`) handles the primary reasoning loop.

- **`run(task: str)`**: The main entry point for tasks.
- **`step(task: str)`**: Executes a single reasoning turn.

To modify the reasoning flow (e.g., adding a "Critic" loop), subclass `CoreAgent` or edit the `run()` method.

---

## 3. Security Middleware Development

If adding new API entry points in `api/routes/`, always protect textual inputs with the `paranoid_guard` middleware.

```python
from api.middleware.paranoid import paranoid_guard

@router.post("/new_feature")
async def new_feature(req: MyRequest, _ = Depends(paranoid_guard)):
    # Logic here
```

All new endpoints exposing sensitive data (infrastructure, stats) must include the `verify_api_key` dependency:

```python
from api.security import verify_api_key

@router.get("/my_endpoint", dependencies=[Depends(verify_api_key)])
async def my_endpoint():
    ...
```

---

## 4. Dashboard Development

The Command Center frontend lives in `dashboard/` and uses **Vite + React + CSS Modules**.

### Setup
```bash
cd dashboard
npm install
npm run dev    # Starts Vite HMR on localhost:5173
               # API calls are proxied to localhost:8000 automatically
```

### Project Structure
```
dashboard/src/
├── api/argos.js              ← Centralized API SDK (REST + SSE)
├── hooks/useSSEChat.js       ← React hook for streaming LLM responses
├── components/
│   ├── ChatTerminal/         ← Main chat interface
│   ├── CommandMonitor/       ← Docker container stats widget
│   └── RateLimitWidget/      ← API quota tracker
├── App.jsx                   ← Root layout (2-column grid)
└── index.css                 ← Global design tokens (CSS variables)
```

### CSS Convention
All component styles use **CSS Modules** (`ComponentName.module.css`). Global tokens (colors, fonts, blur effects) are in `index.css`.

### Production Build
```bash
cd dashboard && npm run build    # Generates dist/
# FastAPI serves dist/ automatically via StaticFiles
```

---

## 5. Code Execution Sandbox

Code tools (`python_repl`, `bash_exec`) run in **ephemeral Docker containers** via `docker-socket-proxy`.

- **Image**: `python:3.12-slim`
- **Limits**: 128MB RAM, 25% CPU, no network
- **I/O**: Only `./workspace/` is mounted as `/workspace`

The Docker client is lazy-initialized (singleton) to avoid TCP handshake overhead per call.

---

## 6. Rate Limiting

Rate limits are enforced atomically via `INSERT ... ON CONFLICT DO UPDATE` (no Redis needed).

- **Config**: `RATE_LIMIT_PER_HOUR` and `RATE_LIMIT_PER_MINUTE` in `.env`
- **Auto-cleanup**: Expired windows (> 2 hours) are purged inline on every request

---

## 7. Testing & Code Quality

### Test Suite
```bash
# Run all tests
pytest tests/ -v

# With coverage report
pytest tests/ -v --cov=src --cov=api
```

> **Note**: `asyncio_mode = "auto"` is configured in `pyproject.toml` for pytest-asyncio compatibility.

### Linting
```bash
ruff check .          # Find issues
ruff check . --fix    # Auto-fix what's possible
ruff format .         # Format all files
```

### Load Testing
```bash
cd tests/load && locust -f locustfile.py --host http://localhost:8000
```

### Non-Interactive CLI testing
You can test the CLI engine directly using strings:
```bash
python3 scripts/main.py --memory "What is 2+2?"
```
