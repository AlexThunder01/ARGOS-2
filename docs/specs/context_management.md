# SPEC — Context Management: Micro-compaction, Structured Compaction, Session Memory

## Obiettivo

Sostituire il naive `trim_history()` (drop dei messaggi più vecchi) con una pipeline a 3 livelli ispirata a Claude Code, più un sistema di Session Memory che preserva lo stato di lavoro attivo attraverso la compaction.

## File coinvolti

| File | Azione |
|------|--------|
| `src/agent.py` | modifica: `trim_history()` + aggiunta `micro_compact()` + `_call_for_compaction()` |
| `src/core/compaction.py` | nuovo: prompt + logica compaction strutturata |
| `src/core/session_memory.py` | nuovo: SessionMemory class |
| `src/core/engine.py` | modifica: integra SessionMemory in reasoning loop e context builder |
| `tests/test_agent_history.py` | aggiunta test micro_compact e tiered trim_history |
| `tests/test_compaction.py` | nuovo: test compact_conversation |
| `tests/test_session_memory.py` | nuovo: test SessionMemory |

## Architettura

### Tier 1 — Micro-compaction (`src/agent.py: micro_compact()`)

- Trigger: `total_tokens > token_budget * 0.8`
- Nessuna chiamata LLM
- Identifica messaggi "comprimibili": tool results (`role=user, content starts TOOL RESULT:`), WorldState snapshots (`role=system` con marker noti), JSON tool calls (`role=assistant, content starts {"action":`)
- Mantiene i `MICRO_COMPACT_KEEP_RECENT` più recenti (default: 5, override: `ARGOS_MICRO_COMPACT_KEEP`)
- Rimpiazza il content dei più vecchi con `"[cleared]"`

### Tier 2 — Structured Compaction (`src/core/compaction.py`)

- Trigger: `total_tokens > token_budget * 0.9` AND `len(history) >= 5`
- Chiama LLM (lightweight model) con prompt 9-sezioni + blocco `<analysis>` (scrippato prima di salvare il summary)
- Il summary sostituisce tutta la history: `[system_msg, summary_user_msg, ack_assistant_msg]`
- Fallback trasparente: se LLM fail → history originale, cade nel Tier 3

### Tier 3 — Drop (fallback, comportamento originale)

- Trigger: `total_tokens > token_budget` dopo Tier 1 e 2
- Drop dei messaggi più vecchi come prima

### Session Memory (`src/core/session_memory.py`)

- File: `.argos_session_memory.md` (ignorato da git)
- Aggiornato ogni `ARGOS_SESSION_MEMORY_UPDATE_EVERY` tool calls (default: 5)
- Aggiornamento via `call_lightweight` in background (asyncio.create_task + to_thread)
- Iniettato in `_build_llm_context` prima del task message
- NON viene cancellato tra task — ponticella richieste consecutive nella stessa sessione server

## Vincoli

- `trim_history()` deve essere backward-compatible: Tier 3 produce lo stesso comportamento dell'originale
- Nessuna chiamata LLM reale nei test (Tier 2 gated da `len(history) >= 5`, test usano mock)
- Il blocco `<analysis>` viene sempre strippato dal summary prima di inserirlo in history
- `compact_conversation` è exception-safe: qualsiasi errore → ritorna history originale
- Tutti i test esistenti devono continuare a passare

## Costanti configurabili via env

| Variabile | Default | Significato |
|-----------|---------|-------------|
| `ARGOS_MICRO_COMPACT_KEEP` | `5` | Tool results recenti da preservare |
| `ARGOS_COMPACT_THRESHOLD` | non usata (hardcoded 0.9) | — |
| `ARGOS_SESSION_MEMORY_UPDATE_EVERY` | `5` | Tool calls tra aggiornamenti session memory |
| `ARGOS_SESSION_MEMORY_PATH` | `.argos_session_memory.md` | Path del file session memory |
