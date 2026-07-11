# SPEC — Multi-chat isolata per la Dashboard (condivisa con la CLI)

## Obiettivo

Estendere alla Dashboard il sistema di chat isolate già costruito per la CLI
(`--memory --chat ID` / `--new-chat` / `--list-chats`, commit `db865f4`), così
che ogni conversazione persistente abbia il proprio bucket di memoria isolato,
selezionabile da un dropdown nella topbar — e aggiungere la persistenza dello
storico messaggi (oggi assente sia in CLI che in Dashboard) così l'interfaccia
grafica può mostrare la trascrizione reale di una chat ripresa, non solo i
fatti estratti da mem0.

Motivazione: la Dashboard oggi deriva `user_id` da `sha256($USER)` in
`api/routes/dashboard.py` — lo stesso bug di identità condivisa già trovato e
risolto in CLI (vedi "Maria Francesca"/"Alessandro" mescolati in mem0).

## File coinvolti

| File | Azione |
|------|--------|
| `src/db/migrations/004_chat_messages.py` | nuovo — colonna `title` su `argos_chats`, tabella `argos_chat_messages` |
| `src/core/chats.py` | aggiungere `save_message()`, `generate_title_if_needed()`, aggiornare `list_chats()`/`create_chat()` per includere `title` |
| `api/routes/dashboard.py` | nuove route `GET/POST /api/chats`, `GET /api/chats/{id}/messages`; `chat_stream`/`sse_agent_stream` accettano `chat_id` invece di derivarlo da `$USER`, chiamano `save_message`/`generate_title_if_needed` |
| `scripts/main.py` | dopo la risoluzione di `--chat`/`--new-chat`, ogni turno (one-shot e loop interattivo) chiama `save_message`/`generate_title_if_needed` |
| `dashboard/src/components/ChatSwitcher/` | nuovo componente — dropdown topbar |
| `dashboard/src/api/argos.js` | nuove funzioni `listChats()`, `createChat()`, `getChatMessages(id)`; `startChatStream` passa `chat_id` |
| `dashboard/src/hooks/useSSEChat.js` | stato `currentChatId`, auto-resume ultima chat al mount, sostituzione storico al cambio chat |
| `dashboard/src/App.jsx` | monta `ChatSwitcher` nella topbar |
| `tests/test_migrations.py` | aggiornare il set di versioni attese (`{1,2,3,4}`) |
| nuovo `tests/test_chats.py` | test per `save_message`/`generate_title_if_needed`/`list_chats` con titolo |

## Vincoli e regole

- [ ] Nessuna modifica a `CoreAgent`/`engine.py`: la persistenza della trascrizione resta responsabilità delle interfacce (CLI, Dashboard), non del core condiviso — Telegram ha già `tg_conversations` e non va toccato
- [ ] `argos_chats`/`argos_chat_messages` condivise tra CLI e Dashboard (stessa tabella, stessi ID — una chat iniziata in un'interfaccia è ripresa identica nell'altra)
- [ ] Migrazione idempotente (`IF NOT EXISTS`), branching esplicito SQLite/Postgres (niente `conn.executescript` — verificato che `psycopg.Connection` non ha quel metodo, vedi migrazione 003 per il pattern corretto)
- [ ] Un tool call per turno LLM (invariato, non toccato da questa feature)
- [ ] No mock del DB nei test — SQLite reale

## Design conversazionale (riassunto dal brainstorming)

1. **Namespace condiviso CLI+Dashboard** — stessa tabella `argos_chats`, stessi ID.
2. **Selettore chat**: dropdown nella topbar (mockup approvato: pill vicino a
   "CoreAgent v2.2.0 | Model ..."), non un pannello sidebar permanente né un
   drawer a comparsa.
3. **Storico messaggi visibile**: riprendendo una chat dalla Dashboard si vede
   la trascrizione reale precedente, non solo i fatti mem0 — richiede la nuova
   tabella `argos_chat_messages`.
4. **Titoli auto-generati**: al primo messaggio di una chat nuova, il modello
   leggero genera un titolo breve (es. "Meteo a Milano" invece di "Chat #3"),
   salvato in `argos_chats.title`.
5. **Persistenza condivisa**: sia CLI che Dashboard chiamano le stesse funzioni
   di `src/core/chats.py` — non due implementazioni parallele.

## Input / Output atteso

### `POST /api/chats` (Dashboard)
**Input:** nessun body.
**Output:** `{"id": 4, "title": null, "created_at": "...", "last_used_at": "..."}`

### `GET /api/chats`
**Output:** lista ordinata per `last_used_at DESC`:
```json
[{"id": 4, "title": "Meteo a Milano", "created_at": "...", "last_used_at": "..."},
 {"id": 3, "title": null, "created_at": "...", "last_used_at": "..."}]
```
Una chat senza ancora un primo turno ha `title: null` — il frontend mostra
"Chat #N" come fallback.

### `GET /api/chats/{id}/messages`
**Output:** `[{"role": "user", "content": "...", "created_at": "..."}, {"role": "agent", ...}]`
404 se la chat non esiste.

### `POST /api/chat/stream`
**Input aggiornato:** `{"task": "...", "chat_id": 4, "attachments": [...]}` — il
campo `history` inviato dal frontend oggi viene sostituito da `chat_id`
lato server (lo storico si recupera da `argos_chat_messages`, non passato
dal client a ogni richiesta).
**Comportamento:** valida `chat_id` (404 se non esiste), aggiorna
`last_used_at`, esegue il task, salva turno utente + turno agente, genera il
titolo se assente, poi stream come oggi.

### CLI (`scripts/main.py`)
Nessun cambiamento all'interfaccia utente (`--chat`/`--new-chat`/`--list-chats`
restano identici) — internamente, ogni turno ora chiama anche `save_message`.
`--list-chats` mostra anche il titolo, se presente.

**Casi limite:**
- Chat esistente ma creata prima di questa feature (nessun messaggio salvato,
  nessun titolo): `GET .../messages` ritorna `[]`, dropdown mostra "Chat #N".
- `chat_id` inesistente passato a `/api/chat/stream`: 404, nessuna esecuzione.
- Generazione titolo fallisce (LLM down): non bloccante, la chat resta senza
  titolo, si ritenta al turno successivo se ancora `title IS NULL`.
- **Nessuna chat esistente al primo avvio della Dashboard** (`GET /api/chats`
  torna `[]`): il frontend chiama automaticamente `POST /api/chats` e passa
  alla chat appena creata — a differenza della CLI (dove la scelta è sempre
  esplicita), la Dashboard deve mostrare una chat funzionante al primo carico
  senza richiedere un click preliminare.

## Funzioni da aggiungere

```python
# src/core/chats.py

def save_message(chat_id: int, role: str, content: str) -> None:
    """Salva un turno (role: 'user' | 'agent') in argos_chat_messages."""

def get_messages(chat_id: int) -> list[dict]:
    """Storico completo di una chat, ordinato cronologicamente."""

def generate_title_if_needed(chat_id: int, first_message: str) -> None:
    """Se argos_chats.title è NULL, genera un titolo breve via call_lightweight
    e lo salva. Non solleva eccezioni: fallisce silenziosamente (retry al turno dopo)."""
```

## Dipendenze

- [x] Nessuna dipendenza nuova (riusa `call_lightweight` già esistente)
- [ ] Migrazione DB: `004_chat_messages.py`
- [ ] Nessuna nuova variabile d'ambiente

## Test da scrivere

- [ ] `save_message` + `get_messages` round-trip (SQLite reale)
- [ ] `generate_title_if_needed`: non sovrascrive un titolo esistente; non solleva eccezioni se il modello leggero fallisce
- [ ] `list_chats` include `title` (anche `None`)
- [ ] `POST /api/chats`, `GET /api/chats`, `GET /api/chats/{id}/messages` (incl. 404)
- [ ] `/api/chat/stream` con `chat_id` valido/non valido
- [ ] `test_migrations.py` aggiornato per la versione 4
- [ ] Frontend: `ChatSwitcher` mostra la lista, evidenzia la chat attiva, "+ Nuova chat" funziona (test manuale via browser, coerente con come è stata verificata la Dashboard finora in questa sessione)

## Limite noto (accettato in fase di design)

Le chat esistenti create prima di questa feature (sia CLI che eventuali test
precedenti in questa sessione) non hanno messaggi salvati — mostreranno uno
storico vuoto anche se mem0 ricorda ancora i fatti associati. Non è un bug:
è lo stato iniziale atteso per dati pre-esistenti.

## Note aggiuntive

- Nato da un bug reale osservato in questa sessione: due nomi diversi
  ("Alessandro", "Maria Francesca") nella stessa identità `$USER`-derivata si
  sono fusi in un unico fatto incoerente in mem0. Il fix CLI (`db865f4`) e
  questa estensione Dashboard risolvono la causa a monte (identità condivisa),
  non il sintomo.
- Verificare dal vivo con Playwright (come fatto per il fix "[Pensando...]" e
  per l'audit generale della Dashboard in questa sessione) prima di
  considerare il lavoro concluso.
