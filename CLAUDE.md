# ARGOS — Guida per Claude Code

## Stack tecnologico
- **Backend:** Python 3.11+, FastAPI, SQLite (default) / PostgreSQL
- **LLM:** multi-backend (OpenAI-compatible + Anthropic), config in `src/config.py`
- **Dashboard:** React (Vite), in `dashboard/`
- **Container:** Docker Compose (`docker-compose.yml`)
- **Test:** pytest, 180+ test, tutti devono passare prima di ogni merge

## Architettura — file principali

| File | Ruolo |
|------|-------|
| `src/tools/registry.py` | **UNICA sorgente di verità** per tutti i 23 tool |
| `src/tools/spec.py` | `ToolInput`, `ToolSpec`, `ToolRegistry` — classi base |
| `src/agent.py` | `ArgosAgent` — loop LLM, history, trim, streaming |
| `src/core/engine.py` | `CoreAgent` — orchestrazione: reasoning → planning → exec → memory |
| `src/executor/executor.py` | Esecuzione tool con retry e validazione Pydantic |
| `src/planner/planner.py` | Parsing output LLM → azioni strutturate |
| `src/core/memory.py` | Memoria semantica (TF-IDF cosine similarity + keyword fallback) |
| `api/server.py` | FastAPI app e routes |
| `src/config.py` | Variabili d'ambiente e configurazione |

## Regola #1 — Aggiungere un tool

Definire il tool **SOLO** in `src/tools/registry.py` come `ToolSpec`.
Tutto il resto (TOOLS dict, TOOL_METADATA, system prompt, dashboard whitelist) si aggiorna automaticamente.

```python
ToolSpec(
    name="my_tool",
    description="Cosa fa in una riga",
    input_schema=MyToolInput,   # Pydantic ToolInput subclass
    executor=my_tool_fn,        # (dict) -> str
    risk="none",                # none | low | medium | high | critical
    category="web",             # filesystem | web | finance | code | system | gui | documents
    icon="🔧",
    label="My Tool",
    dashboard_allowed=False,
    group="research",           # Opzionale: profilo tool (vedi sotto)
)
```

## Tool groups (profili)

`ToolRegistry.build_prompt_block(group=None)` filtra per gruppo.
Gruppi disponibili:

| Gruppo | Tool inclusi |
|--------|-------------|
| `"coding"` | filesystem, code |
| `"research"` | web, finance, documents |
| `"automation"` | gui, system |
| `None` | tutti (default) |

Usare `agent._init_history_with_tools(REGISTRY.build_prompt_block(group="coding"))` per inizializzare l'agente con un sottoinsieme di tool.

## Vincoli stilistici
- **No metadata hardcoded** fuori da `ToolSpec` — niente dizionari paralleli
- **No testo AVAILABLE TOOLS hardcoded** — sempre da `build_prompt_block()`
- **No mock del DB nei test** — usare SQLite reale (conftest imposta backend sqlite)
- **Un tool call per turno LLM** — regola del sistema prompt, non violarla

## Eseguire i test
```bash
pytest tests/ -x -q
```

## Variabili d'ambiente chiave
```
LLM_BACKEND=openai|anthropic
LLM_MODEL=...
LLM_API_KEY=...
LLM_BASE_URL=...           # per backend OpenAI-compatible
MAX_HISTORY_TOKENS=8000    # token budget history
```
