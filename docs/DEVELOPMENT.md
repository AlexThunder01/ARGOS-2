# ARGOS-2 Development: Extending the Unified Agent

This document is for developers who want to extend ARGOS-2's capabilities beyond the defaults.

---

## 1. Modular Tool Architecture

Tools are defined as `ToolSpec` objects in `src/tools/registry.py`. Each tool is a single source of truth for: executor function, Pydantic input schema, risk level, category, dashboard metadata, and system prompt text.

### Step 1: Create the Executor Function

Find the appropriate module in `src/tools/` (e.g., `code_exec.py`, `documents.py`, `web.py`) or create a new one.

```python
# src/tools/my_tools.py

def my_custom_tool(inp: dict) -> str:
    """Brief description of what this tool does."""
    value = inp.get("param", "")
    # Tool logic here
    return f"Result: {value}"
```

### Step 2: Create a Pydantic Input Schema

Define the input schema in `src/tools/registry.py` alongside the existing schemas:

```python
from pydantic import Field
from .spec import ToolInput

class MyCustomInput(ToolInput):
    param: str = Field(description="Description of the parameter", examples=["example_value"])
    optional_flag: bool = Field(default=False, description="An optional boolean flag")
```

The `examples` list in `Field()` is used to generate the JSON example shown in the LLM system prompt.

### Step 3: Register the ToolSpec

Add a `ToolSpec` entry to the `REGISTRY` list in `src/tools/registry.py`:

```python
from .my_tools import my_custom_tool

REGISTRY = ToolRegistry([
    # ... existing tools ...
    ToolSpec(
        name="my_custom_tool",
        description="Does something useful",
        input_schema=MyCustomInput,
        executor=my_custom_tool,
        risk="low",            # "none" | "low" | "medium" | "high" | "critical"
        category="web",        # "filesystem" | "web" | "finance" | "code" | "system" | "gui" | "documents"
        icon="🔧",
        label="My Custom Tool",
        dashboard_allowed=True, # Show in dashboard tool list
        group="research",      # "coding" | "research" | "automation" | None (all)
    ),
])
```

**That's it.** The tool is now:
- Available in the LLM system prompt (with auto-generated JSON example)
- Protected by the security gate based on its `risk` level
- Visible in the dashboard based on `dashboard_allowed`
- Subject to the hook system (PreToolUse / PostToolUse)

### Risk Levels and Security Gate

| Risk | CLI Behavior | API Behavior |
|------|-------------|-------------|
| `none` / `low` | Auto-approved | Auto-approved |
| `medium` / `high` / `critical` | Requires `(y/N)` confirmation | Auto-blocked (unless callback provided) |

---

## 2. Extending the CoreAgent

The `CoreAgent` (`src/core/engine.py`) handles the primary reasoning loop.

- **`run_task(task: str) -> TaskResult`**: Sync entry point — delegates to `run_task_async` via `asyncio.run()`.
- **`run_task_async(task: str) -> TaskResult`**: Canonical async implementation of the full cognitive pipeline.
- **`run_task_stream(task: str) -> Generator`**: Streaming variant for single-turn, no-tool queries.

To modify the reasoning flow (e.g., adding a "Critic" loop), subclass `CoreAgent` or edit the `_reasoning_loop()` method.

### Hook System

Instead of subclassing, prefer the hook system for cross-cutting concerns:

```python
from src.hooks.registry import on, HookEvent

@on(HookEvent.PRE_TOOL_USE, tools=["delete_file", "delete_directory"])
def block_at_night(tool_name, tool_input) -> bool:
    """Block destructive tools outside business hours."""
    from datetime import datetime
    return 8 <= datetime.now().hour < 22

@on(HookEvent.POST_TOOL_USE, tools=["web_search"])
def log_searches(tool_name, tool_input, result, success):
    """Log all web searches for audit."""
    print(f"Search: {tool_input.get('query')} -> success={success}")
```

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

The Command Center frontend lives in `dashboard/` and uses **Vite 8 + React + CSS Modules**.

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
- **I/O**: `./workspace/` is mounted as `/workspace` in **read-only** mode. User code can read input files but cannot write to the host filesystem.

The Docker client is lazy-initialized (singleton) to avoid TCP handshake overhead per call.

---

## 6. Rate Limiting

Rate limits are enforced atomically via `INSERT ... ON CONFLICT DO UPDATE` (no Redis needed).

- **Config**: `RATE_LIMIT_PER_HOUR` (default: 50) and `RATE_LIMIT_PER_MINUTE` (default: 5) in `.env`
- **Auto-cleanup**: Expired windows (> 2 hours) are purged inline on every request

---

## 7. Testing & Code Quality

### Test Suite
```bash
# Run all tests
pytest tests/ -v

# Run dashboard-specific telemetry tests
pytest tests/test_dashboard.py -v

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
