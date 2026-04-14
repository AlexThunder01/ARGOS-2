# SPEC — Native Attachment Support (ARGOS-2)

> **Stato**: pronto per implementazione
> **Revisione**: v2 — incorpora feedback code review (opaque ID, user_id source, TTL, voice, auth)

---

## Obiettivo

Aggiungere la possibilità di allegare file a qualsiasi interfaccia (API REST, Dashboard,
CLI, Telegram) in modo che l'agente li analizzi automaticamente con i tool già esistenti
(`read_pdf`, `read_csv`, `analyze_image`, `transcribe_audio`, ecc.).

**Flusso core** (invariato rispetto a v1):
```
File allegato → Salva in workspace/uploads/ → Upload-ID opaco → Prompt injection → LLM usa tool giusto
```

Il CoreAgent non viene modificato.

---

## Decisioni architetturali (già prese)

| Decisione | Valore | Motivazione |
|-----------|--------|-------------|
| Max size per file | 20 MB | Allineato al limite cloud Telegram e uso comune |
| Max allegati per messaggio | 5 | Evita prompt injection eccessiva |
| TTL file upload | 24h (default) | Configurabile in `config.yaml` (hot-reload) |
| Path esposto al client | **No** — UUID opaco | Non esporre struttura filesystem |
| Telegram voice | Trascrizione automatica | UX più naturale; l'LLM decide per gli altri tipi |
| user_id per API/Dashboard | `0` (single-tenant) | Sistema non ha sessioni utente API |
| user_id per Telegram | `req.user_id` dal body | Già presente in ogni richiesta Telegram |

---

## File coinvolti

| File | Azione |
|------|--------|
| `src/upload.py` | **NUOVO** — servizio upload centralizzato |
| `api/routes/upload.py` | **NUOVO** — endpoint `POST /api/upload` (API/Dashboard/CLI) |
| `api/routes/telegram.py` | modifica — `TelegramChatRequest` + `POST /telegram/attach` + inject |
| `api/routes/dashboard.py` | modifica — `ChatRequest` + inject allegati |
| `api/routes/agent.py` | modifica — `TaskRequest` + inject allegati |
| `api/server.py` | modifica — registra upload router |
| `src/config.py` | modifica — `UPLOAD_MAX_BYTES`, `UPLOAD_TTL_HOURS`, `UPLOAD_MAX_FILES` |
| `src/workflows_config.py` | modifica — legge `upload_ttl_hours` da `config.yaml` |
| `dashboard/src/components/ChatTerminal/ChatTerminal.jsx` | modifica — UI allegati |
| `dashboard/src/components/ChatTerminal/ChatTerminal.module.css` | modifica — stili |
| `dashboard/src/api/argos.js` | modifica — `uploadFile()`, aggiorna `startChatStream()` |
| `scripts/main.py` | modifica — flag `--attach` e sintassi `@file:` |
| `workflows/05_telegram_chat.json` | modifica minima — nodo JS passa `file_id` a `/telegram/attach` |
| `tests/test_upload.py` | **NUOVO** |
| `tests/test_api_upload.py` | **NUOVO** |
| `tests/test_cli_attach.py` | **NUOVO** |
| `tests/test_telegram_attach.py` | **NUOVO** |

> **Architettura Telegram**: la logica di download file sta interamente in Python
> (`api/routes/telegram.py`), non in n8n. Il nodo JS n8n fa solo estrazione dati
> (file_id, filename, user_id) e chiama `POST /telegram/attach`. ARGOS scarica da
> Telegram internamente usando `TELEGRAM_BOT_TOKEN` (già in `.env`). N8n rimane
> thin router — nessuna logica di business nel JS.

---

## Vincoli e regole

- [ ] Nessun metadata hardcoded fuori da `ToolSpec`
- [ ] Nessun mock del DB nei test
- [ ] Un tool call per turno LLM
- [ ] L'endpoint `/api/upload` richiede `Depends(verify_api_key)` — stessa auth del resto
- [ ] Nessun path assoluto esposto al client
- [ ] Sanificazione nome file obbligatoria (no path traversal)
- [ ] Whitelist estensioni: solo tipi allineati ai tool esistenti

---

## Dettaglio implementazione

### `src/upload.py` — Servizio centralizzato

```python
import os
import uuid
import time
import hashlib
from pathlib import Path
from src.config import WORKSPACE_DIR, UPLOAD_MAX_BYTES, UPLOAD_MAX_FILES

UPLOAD_DIR = Path(WORKSPACE_DIR) / "uploads"

# Registry in-memory: upload_id → (abs_path, created_at)
# Per un sistema multi-worker usare Redis o tabella SQLite
_registry: dict[str, tuple[str, float]] = {}

ALLOWED_EXTENSIONS = {
    # Documenti
    ".pdf", ".csv", ".json", ".xlsx", ".xls", ".xlsm",
    ".txt", ".md", ".log",
    # Immagini
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff",
    # Audio
    ".wav", ".flac", ".ogg", ".aiff", ".mp3",
    # Archivi (solo salvataggio, no estrazione automatica)
    ".zip", ".tar.gz",
}

EXT_TO_TOOL = {
    ".pdf": "read_pdf",
    ".csv": "read_csv",
    ".xlsx": "read_excel", ".xls": "read_excel", ".xlsm": "read_excel",
    ".json": "read_json",
    ".png": "analyze_image", ".jpg": "analyze_image", ".jpeg": "analyze_image",
    ".gif": "analyze_image", ".bmp": "analyze_image",
    ".webp": "analyze_image", ".tiff": "analyze_image",
    ".wav": "transcribe_audio", ".flac": "transcribe_audio",
    ".ogg": "transcribe_audio", ".aiff": "transcribe_audio", ".mp3": "transcribe_audio",
    ".txt": "read_file", ".md": "read_file", ".log": "read_file",
}

def validate_upload(filename: str, size: int) -> None:
    """Lancia ValueError se il file non è ammesso."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Estensione non supportata: {suffix}")
    if size > UPLOAD_MAX_BYTES:
        mb = UPLOAD_MAX_BYTES // (1024 * 1024)
        raise ValueError(f"File troppo grande (max {mb} MB)")

def save_upload(user_id: int, filename: str, content: bytes) -> str:
    """
    Salva il file, registra l'UUID e ritorna l'upload_id opaco.
    NON ritorna mai il path assoluto al chiamante esterno.
    """
    validate_upload(filename, len(content))
    # Sanifica nome file (no path traversal)
    safe_name = Path(filename).name.replace("..", "").replace("/", "_")
    ts = int(time.time())
    dest_dir = UPLOAD_DIR / str(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{ts}_{safe_name}"
    dest.write_bytes(content)
    upload_id = str(uuid.uuid4())
    _registry[upload_id] = (str(dest), ts)
    return upload_id

def resolve_upload_id(upload_id: str) -> str:
    """
    Ritorna il path assoluto dato un upload_id.
    Lancia KeyError se non trovato o scaduto.
    """
    if upload_id not in _registry:
        raise KeyError(f"Upload non trovato: {upload_id}")
    path, created_at = _registry[upload_id]
    if not os.path.exists(path):
        del _registry[upload_id]
        raise KeyError(f"File rimosso: {upload_id}")
    return path

def build_attachment_context(upload_ids: list[str]) -> str:
    """Genera il blocco di contesto da iniettare nel prompt."""
    lines = [
        "ATTACHMENTS PROVIDED BY USER:",
        "The user has attached the following files. "
        "Use the appropriate tool to read/analyze each file.",
    ]
    for uid in upload_ids:
        try:
            path = resolve_upload_id(uid)
            size_kb = os.path.getsize(path) / 1024
            size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
            suffix = Path(path).suffix.lower()
            ftype = suffix.upper().lstrip(".")
            tool = EXT_TO_TOOL.get(suffix, "read_file")
            lines.append(f"- [{ftype}] {path} ({size_str}) → use `{tool}`")
        except KeyError:
            lines.append(f"- [ERROR] upload_id {uid!r} not found or expired")
    lines.append("")
    return "\n".join(lines)

def cleanup_expired(ttl_hours: int) -> int:
    """Rimuove file più vecchi di ttl_hours. Ritorna numero di file rimossi."""
    cutoff = time.time() - ttl_hours * 3600
    removed = 0
    for uid, (path, created_at) in list(_registry.items()):
        if created_at < cutoff:
            try:
                os.remove(path)
            except OSError:
                pass
            del _registry[uid]
            removed += 1
    return removed
```

---

### `src/config.py` — Nuove costanti

```python
# Upload settings
UPLOAD_MAX_BYTES: int = int(os.getenv("UPLOAD_MAX_BYTES", str(20 * 1024 * 1024)))  # 20 MB
UPLOAD_MAX_FILES: int = int(os.getenv("UPLOAD_MAX_FILES", "5"))
UPLOAD_TTL_HOURS: int = int(os.getenv("UPLOAD_TTL_HOURS", "24"))
```

---

### `api/routes/upload.py` — Endpoint REST

```python
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from api.security import verify_api_key
from src.upload import save_upload, validate_upload
from src.config import UPLOAD_MAX_FILES

router = APIRouter(tags=["Upload"])

@router.post("/api/upload", dependencies=[Depends(verify_api_key)])
async def upload_file(file: UploadFile = File(...)):
    """
    Carica un file e ritorna un upload_id opaco (UUID).
    user_id=0 per upload da API/Dashboard (sistema single-tenant).
    """
    content = await file.read()
    try:
        validate_upload(file.filename, len(content))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    upload_id = save_upload(user_id=0, filename=file.filename, content=content)
    return {"upload_id": upload_id, "filename": file.filename}
```

---

### `api/routes/dashboard.py` — ChatRequest

```diff
 class ChatRequest(BaseModel):
     task: str
     max_steps: int = 10
     history: list[dict] = []
+    attachments: list[str] = []  # Lista di upload_id (UUID) da /api/upload
```

In `sse_agent_stream()`:

```diff
+    if req.attachments:
+        from src.upload import build_attachment_context
+        attachment_ctx = build_attachment_context(req.attachments)
+        task = f"{task}\n\n{attachment_ctx}"
```

---

### `api/routes/agent.py` — TaskRequest

```diff
 class TaskRequest(BaseModel):
     task: str
     require_confirmation: bool = False
     max_steps: int = 5
+    attachments: list[str] = []  # upload_id UUID
```

Stesso pattern inject di dashboard.py.

---

### `api/routes/telegram.py` — Endpoint `/telegram/attach` + `TelegramChatRequest`

**Nuovo endpoint** `POST /telegram/attach` — scarica il file da Telegram e ritorna
un `upload_id`. Chiamato da n8n prima di `/telegram/chat`. Tutta la logica sta in Python.

```python
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.security import verify_api_key
from src.upload import save_upload, validate_upload

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

class TelegramAttachRequest(BaseModel):
    file_id: str
    filename: str          # es. "document.pdf", "voice.ogg"
    user_id: int

@router.post("/telegram/attach", dependencies=[Depends(verify_api_key)])
async def telegram_attach(req: TelegramAttachRequest):
    """
    Scarica un file da Telegram (via file_id) e lo salva come upload.
    Ritorna upload_id opaco da passare a /telegram/chat.
    """
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN non configurato")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
            params={"file_id": req.file_id},
        )
        if not r.is_success:
            raise HTTPException(status_code=502, detail="Telegram getFile fallito")
        tg_path = r.json()["result"]["file_path"]
        dl = await client.get(
            f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{tg_path}"
        )
        dl.raise_for_status()
    try:
        upload_id = save_upload(
            user_id=req.user_id,
            filename=req.filename,
            content=dl.content,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"upload_id": upload_id, "filename": req.filename}
```

**Modifica `TelegramChatRequest`**:

```diff
 class TelegramChatRequest(BaseModel):
     user_id: int
     chat_id: int
     text: str
+    attachments: list[str] = []  # upload_id UUID da /telegram/attach
     first_name: str = ""
     username: str = ""
```

In `telegram_chat()`, inject allegati nei messaggi LLM:

```diff
+    if req.attachments:
+        from src.upload import build_attachment_context
+        ctx = build_attachment_context(req.attachments)
+        messages.append({"role": "system", "content": ctx})
```

**Flusso voice/document in n8n** (modifiche minime al workflow):

Il nodo JS "Extract & Classify Message" viene aggiornato per estrarre `file_id`:
```javascript
// Aggiunta al nodo esistente — solo estrazione dati, nessuna logica HTTP
const doc = message.document || message.photo?.pop() || message.voice || message.audio;
if (doc) {
    return [{ json: {
        ...item.json,
        has_attachment: true,
        file_id: doc.file_id,
        filename: doc.file_name || `voice_${Date.now()}.ogg`,
        user_id: message.from.id,
    }}];
}
```

Viene aggiunto un nodo `HTTP Request` **"Download Telegram File"** (prima di "Call ARGOS Brain"):
- `POST {{$env.ARGOS_URL}}/telegram/attach`
- Body: `{ file_id, filename, user_id }`
- Headers: `X-ARGOS-API-KEY`
- Output: `upload_id`

"Call ARGOS Brain" (`/telegram/chat`) riceve poi `attachments: [upload_id]`.

Questo mantiene n8n come thin router: nessuna logica di download, nessun token
Telegram duplicato nel JS.

---

### Dashboard React

#### `argos.js`

```javascript
async uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/api/upload', {
        method: 'POST',
        headers: { 'X-ARGOS-API-KEY': API_KEY },
        body: formData,
    });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json(); // { upload_id, filename }
}
```

`startChatStream()` aggiornato:
```diff
-   body: JSON.stringify({ task, history, ... })
+   body: JSON.stringify({ task, history, attachments, ... })
+   // attachments = array di upload_id UUID
```

#### `ChatTerminal.jsx` — UI

Aggiungere:
1. `<input type="file" hidden ref={fileInputRef} multiple accept="..." />`
2. Bottone `📎` accanto a SEND — apre file picker
3. Zona drag & drop sull'area chat (con overlay `.dropZoneActive`)
4. Preview: chip per ogni file in attesa con ❌ per rimuovere
5. Al SEND: upload sequenziale (`POST /api/upload` per ciascuno),
   poi invio con `attachments: [upload_id, ...]`
6. Errore upload visibile nel chip (sfondo rosso)

#### `ChatTerminal.module.css`

Classi da aggiungere: `.attachBtn`, `.attachPreview`, `.attachChip`,
`.attachChipError`, `.dropZone`, `.dropZoneActive`.

---

### CLI — `scripts/main.py`

```diff
 parser.add_argument(
+    "--attach", "-a",
+    nargs="*",
+    default=[],
+    metavar="FILE",
+    help="File da allegare (es. --attach report.pdf immagine.png)")
```

Sintassi inline nel prompt interattivo:
```
👤 You: Analizza questo @file:/home/alex/report.pdf
```

Implementazione:
1. Estrarre path da `--attach` e da `@file:` con regex
2. Validare con `validate_upload(filename, size)` — errore immediato se non valido
3. Copiare in `workspace/uploads/0/` se fuori da workspace (via `save_upload`)
4. Iniettare `build_attachment_context([upload_ids])` nel task

---

## Prompt injection — formato finale

```
ATTACHMENTS PROVIDED BY USER:
The user has attached the following files. Use the appropriate tool to read/analyze each file.
- [PDF] /workspace/uploads/0/1713052800_report.pdf (245 KB) → use `read_pdf`
- [PNG] /workspace/uploads/0/1713052800_screenshot.png (1.2 MB) → use `analyze_image`
- [OGG] /workspace/uploads/42/1713052800_voice.ogg (45 KB) → use `transcribe_audio`
```

---

## Dipendenze

- [ ] Nessuna dipendenza Python nuova (usa `httpx` già presente per Telegram)
- [ ] Nessuna migrazione DB (registry in-memory)
- [ ] Nessuna nuova variabile d'ambiente obbligatoria (tutte hanno default)
- [ ] Variabili opzionali da aggiungere a `.env.example`:
  - `UPLOAD_MAX_BYTES` (default: 20971520)
  - `UPLOAD_MAX_FILES` (default: 5)
  - `UPLOAD_TTL_HOURS` (default: 24)

---

## Test da scrivere

### `tests/test_upload.py`

- [ ] `save_upload` salva il file nella directory corretta
- [ ] `validate_upload` rifiuta estensione non in whitelist
- [ ] `validate_upload` rifiuta file > `UPLOAD_MAX_BYTES`
- [ ] `resolve_upload_id` ritorna path corretto
- [ ] `resolve_upload_id` lancia `KeyError` per ID inesistente
- [ ] `build_attachment_context` genera testo corretto con tool hint
- [ ] `cleanup_expired` rimuove solo file scaduti
- [ ] Sanificazione nome file: `../../etc/passwd` → nome safe

### `tests/test_api_upload.py`

- [ ] `POST /api/upload` con file valido → `{"upload_id": "<uuid>", "filename": "..."}`
- [ ] `POST /api/upload` senza API key → 403
- [ ] `POST /api/upload` con estensione non ammessa → 422
- [ ] `POST /api/upload` con file > 20 MB → 422
- [ ] `POST /api/chat` (dashboard) con `attachments` → contesto iniettato nel task
- [ ] `POST /run` (agent) con `attachments` → contesto iniettato

### `tests/test_cli_attach.py`

- [ ] `--attach valid.pdf` → upload_id risolto, contesto iniettato
- [ ] `--attach nonexistent.pdf` → errore chiaro all'utente
- [ ] `@file:/path/to/file.csv` inline → estratto e risolto
- [ ] Path fuori da workspace → copiato in `workspace/uploads/0/`

### `tests/test_telegram_attach.py`

- [ ] `POST /telegram/attach` con file_id valido (mock httpx) → `{"upload_id": "...", "filename": "..."}`
- [ ] `POST /telegram/attach` senza API key → 403
- [ ] `POST /telegram/attach` con Telegram che ritorna errore → 502
- [ ] `POST /telegram/attach` con filename non ammesso → 422
- [ ] `POST /telegram/chat` con `attachments` → contesto iniettato nei messaggi LLM

### Telegram (manuale — workflow n8n)

- [ ] Inviare documento PDF → bot risponde con analisi contenuto
- [ ] Inviare messaggio vocale → bot risponde con trascrizione
- [ ] Inviare file > 20 MB → bot risponde con messaggio di errore chiaro (da Telegram, non arriva a ARGOS)

---

## Verification Plan

```bash
# Unit + integrazione
pytest tests/test_upload.py tests/test_api_upload.py tests/test_cli_attach.py -v

# CLI manuale
python3 scripts/main.py --attach workspace/uploads/test.pdf "Cosa contiene questo file?"

# API manuale
curl -H "X-ARGOS-API-KEY: $ARGOS_API_KEY" \
     -F "file=@test.pdf" \
     http://localhost:8000/api/upload

# Sicurezza
curl -F "file=@malware.exe" http://localhost:8000/api/upload  # → 422
curl -F "file=@../../etc/passwd" http://localhost:8000/api/upload  # → 422 o nome sanificato

# Dashboard
# 1. Drag & drop PDF sull'area chat → verificare chip preview
# 2. Premere SEND → verificare che ARGOS analizzi il PDF
```

---

## Note

- Il registry in-memory (`_registry`) non sopravvive al restart del processo.
  Per deployment multi-worker aggiungere una tabella SQLite `upload_registry`
  (fuori scope di questa spec, tracciare come tech debt).
- Il cleanup TTL va schedulato via APScheduler o chiamato a ogni startup.
  Implementazione minima: chiamare `cleanup_expired(UPLOAD_TTL_HOURS)` in
  `lifespan` di `api/server.py`.
