# Argos Modernization — Design Spec
**Data:** 2026-04-19  
**Tipo:** Upgrade strategico (non riscrittura totale)  
**Principio:** ogni componente rimpiazzato porta un beneficio misurabile

---

## Contesto

Argos-2 è un codebase di 23.609 righe Python (~120 file) con 9.400 righe di test. L'analisi approfondita ha rivelato che il 70% dell'architettura è già moderna e production-grade. Una riscrittura totale butterebbe 9.400 righe di test e mesi di lavoro senza benefici netti.

**Strategia scelta:** upgrade chirurgico in 4 fasi che porta Argos allo stato dell'arte senza toccare ciò che funziona.

---

## Cosa rimane invariato

| Componente | Motivazione |
|------------|-------------|
| `src/tools/` | Tool registry solido, 17+ tool in 9 categorie, ToolSpec single source of truth |
| `src/core/engine.py` | Hook system, permission audit, diminishing returns detection — tutto funziona |
| `api/` | FastAPI + SSE + OTEL già production-grade |
| `dashboard/` | React 19 + Vite 8 — già moderni |
| `tests/` | 9.400 righe da preservare e ampliare |
| `src/telegram/` | Integrazione esistente |
| `src/world_model/` | WorldState dataclass |

---

## Fase 1 — LLM Layer: LiteLLM + Parallel Tool Calls

**Durata stimata:** 2 settimane  
**Impatto:** Alto

### 1.1 LiteLLM come provider layer

`src/agent.py` oggi gestisce manualmente client HTTP per Anthropic + OpenAI-compatible con key rotation, retry e parsing custom. LiteLLM unifica tutto.

**Prima:**
```python
response = requests.post(
    f"{self.base_url}/chat/completions",
    headers={"Authorization": f"Bearer {self._rotate_key()}"},
    json={...},
    timeout=120,
)
```

**Dopo:**
```python
from litellm import acompletion
response = await acompletion(
    model="mistral/mistral-large-latest",
    messages=history,
    tools=tool_schemas,
    parallel_tool_calls=True,
)
```

LiteLLM gestisce nativamente: key rotation, fallback tra provider, cost tracking, retry con backoff esponenziale.

### 1.2 Parallel Tool Calls

Il motore oggi esegue un tool per turno (vincolo del system prompt). Con parallel tool calls il modello richiede più tool contemporaneamente e il loop li esegue in parallelo.

**Nuovo executor in `src/core/engine.py`:**
```python
async def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
    tasks = [self._execute_single(tc) for tc in tool_calls]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

**Modifiche necessarie:**
- `src/planner/planner.py` — parsare array di tool call invece di singolo
- `src/agent.py` — system prompt rimuove vincolo "un tool per turno"
- `tests/test_reasoning_loop.py` — adattare per async con pytest-asyncio

### 1.3 Dipendenze

```
+ litellm
+ pytest-asyncio
- requests (rimosso, sostituito da litellm + httpx già presente)
- pybreaker (sostituito da tenacity + litellm fallback nativo)
+ tenacity
```

---

## Fase 2 — Memory Layer: mem0

**Durata stimata:** 1 settimana  
**Impatto:** Medio-Alto

### 2.1 Integrazione mem0

mem0 si appoggia sopra pgvector esistente — non lo sostituisce. Aggiunge entity extraction automatica, deduplication, forgetting curve, user profiles.

**Prima (`src/core/memory.py`):**
```python
embedding = get_embedding(text)
similarities = cosine_similarity(embedding, stored_embeddings)
```

**Dopo:**
```python
from mem0 import Memory
m = Memory.from_config({
    "vector_store": {"provider": "pgvector", "config": {...}}
})
m.add(text, user_id=user_id)
results = m.search(query, user_id=user_id)
```

### 2.2 Cosa rimane di `src/core/memory.py`

- `get_embedding()` — rimane come utility interna
- `check_embedding_dimensions()` — rimane per boot-time check
- Logica di debounced extraction → delegata a mem0
- GC ogni 50 messaggi → gestito da mem0

### 2.3 Dipendenze

```
+ mem0
```

---

## Fase 3 — Code Quality: Async + Type Hints

**Durata stimata:** 2 settimane  
**Impatto:** Medio

### 3.1 Async coverage

**Target:** tutti i file in `src/core/`, `src/agent.py`, `src/tools/` usano `async def`.

- Tool executor usa `asyncio.gather` per operazioni I/O (web, filesystem, DB)
- Nessun `requests.post` sync rimane nel codebase
- `src/executor/executor.py` diventa completamente async

### 3.2 Type hints

**Target:** mypy strict su tutti i moduli core.

- Ogni funzione pubblica ha return type esplicito
- Ogni dataclass usa `@dataclass` o `BaseModel`
- I `dict` ambigui diventano `TypedDict` o Pydantic models
- Coverage: 15% → 80%

### 3.3 Dipendenze

```
+ ruff (linter, sostituisce flake8/black)
+ mypy (strict mode)
```

---

## Fase 4 — Config + Observability

**Durata stimata:** 1 settimana  
**Impatto:** Medio

### 4.1 Pydantic Settings

Unifica `src/config.py` (statico) e `src/workflows_config.py` (hot-reload YAML) in un unico entry point type-safe.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class ArgosSettings(BaseSettings):
    llm_model: str = "mistral/mistral-large-latest"
    tool_rag_top_k: int = 12
    memory_mode: str = "persistent"
    # ... tutti i parametri da config.py + config.yaml

    model_config = SettingsConfigDict(
        env_file=".env",
        yaml_file="config.yaml",
        env_prefix="ARGOS_",
    )

settings = ArgosSettings()
```

### 4.2 Logging JSON strutturato

Compatible con Jaeger/OTEL già in uso. I trace_id vengono propagati automaticamente via contextvars.

**Prima:**
```python
logger.info(f"[Step {n}] Tool {tool_name} executed in {elapsed:.2f}s")
```

**Dopo:**
```python
logger.info("tool_executed", extra={
    "step": n,
    "tool": tool_name,
    "duration_ms": round(elapsed * 1000),
    "trace_id": ctx_trace_id.get(),
})
```

### 4.3 Dipendenze

```
+ pydantic-settings
+ python-json-logger
- scikit-learn (rimosso: Tool RAG migra da TF-IDF a LiteLLM embeddings in Fase 1)
```

**Nota:** Il Tool RAG attuale (`ToolRegistry.select_for_query()`) usa TF-IDF di scikit-learn. Con LiteLLM disponibile in Fase 1, il Tool RAG migra agli stessi embedding usati dalla memory — eliminando scikit-learn come dipendenza e migliorando la qualità della selezione tool.

---

## Dipendenze: riepilogo delta

| | Package |
|-|---------|
| **Aggiunte** | `litellm`, `mem0`, `pydantic-settings`, `python-json-logger`, `tenacity`, `pytest-asyncio`, `ruff`, `mypy` |
| **Rimosse** | `requests`, `pybreaker`, `scikit-learn` |

---

## Metriche di successo

| Metrica | Prima | Target |
|---------|-------|--------|
| Async file coverage | 4/120 (3%) | 80%+ |
| Type hint coverage | 15% | 80%+ |
| Provider switching | manuale | 1 riga config |
| Tool calls/turno | 1 (seriale) | N (parallelo) |
| Memory entity extraction | manuale | automatica (mem0) |
| Config entry points | 2 separati | 1 unificato |
| Log formato | plain text | JSON strutturato |

---

## Ordine di esecuzione raccomandato

```
Fase 1 (LiteLLM + parallel calls) → Fase 2 (mem0) → Fase 3 (async/types) → Fase 4 (config/logging)
```

La Fase 1 va prima perché LiteLLM cambia il transport layer da cui dipendono async e type hints delle fasi successive. La Fase 3 viene dopo mem0 perché i nuovi tipi di mem0 informano i type hints da scrivere.

---

## Rischi e mitigazioni

| Rischio | Mitigazione |
|---------|-------------|
| LiteLLM non supporta feature Mistral X | Testare su branch prima del merge |
| mem0 incompatibile con schema pgvector esistente | Migration script + fallback manuale |
| Parallel tool calls rompono logica sequenziale del planner | Feature flag per abilitare progressivamente |
| Async refactor introduce race condition | pytest-asyncio + test per ogni tool async |
