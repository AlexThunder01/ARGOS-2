"""
ARGOS-2 Upload Service — centralised file upload management.

Responsibilities:
- File type validation (extension whitelist aligned with existing tools)
- Size enforcement (UPLOAD_MAX_BYTES)
- Safe storage in workspace/uploads/<user_id>/<ts>_<filename>
- Opaque UUID registry — callers never receive raw filesystem paths
- TTL-based cleanup via cleanup_expired()
- Prompt context generation for LLM injection
"""

import os
import time
import uuid
from pathlib import Path

# Imported lazily after load_dotenv() has been called by the app entry point.
# At module import time we only store the reference; constants are resolved on
# first use so tests can monkeypatch src.upload.UPLOAD_MAX_BYTES etc.

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Documents
        ".pdf",
        ".csv",
        ".json",
        ".xlsx",
        ".xls",
        ".xlsm",
        ".txt",
        ".md",
        ".log",
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".webp",
        ".tiff",
        # Audio
        ".wav",
        ".flac",
        ".ogg",
        ".aiff",
        ".mp3",
        # Archives (storage only — no auto-extraction)
        ".zip",
    }
)

# Extension → tool name hint (for prompt injection)
_EXT_TO_TOOL: dict[str, str] = {
    ".pdf": "read_pdf",
    ".csv": "read_csv",
    ".xlsx": "read_excel",
    ".xls": "read_excel",
    ".xlsm": "read_excel",
    ".json": "read_json",
    ".png": "analyze_image",
    ".jpg": "analyze_image",
    ".jpeg": "analyze_image",
    ".gif": "analyze_image",
    ".bmp": "analyze_image",
    ".webp": "analyze_image",
    ".tiff": "analyze_image",
    ".wav": "transcribe_audio",
    ".flac": "transcribe_audio",
    ".ogg": "transcribe_audio",
    ".aiff": "transcribe_audio",
    ".mp3": "transcribe_audio",
    ".txt": "read_file",
    ".md": "read_file",
    ".log": "read_file",
    ".zip": "read_file",
}

# In-memory registry: upload_id → (abs_path, created_at_epoch)
# Not shared across processes — add a SQLite table for multi-worker deployments.
_registry: dict[str, tuple[str, float]] = {}


def _get_upload_dir() -> Path:
    """Resolves the upload root from config (deferred to avoid circular imports)."""
    from src.config import WORKSPACE_DIR

    return Path(WORKSPACE_DIR) / "uploads"


def _get_max_bytes() -> int:
    from src.config import UPLOAD_MAX_BYTES

    return UPLOAD_MAX_BYTES


def _sanitize_filename(filename: str) -> str:
    """Strip path components and characters that could enable path traversal."""
    # Take only the basename, then replace unsafe characters
    name = Path(filename).name
    # Replace any remaining slashes or dots sequences
    name = name.replace("..", "_").replace("/", "_").replace("\\", "_")
    return name or "upload"


def validate_upload(filename: str, size: int) -> None:
    """
    Raises ValueError if the file is not acceptable.
    Callers should propagate this as HTTP 422.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File type not supported: {suffix!r}. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    max_bytes = _get_max_bytes()
    if size > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise ValueError(
            f"File too large (max {mb} MB, got {size // (1024 * 1024)} MB)"
        )


def save_upload(user_id: int, filename: str, content: bytes) -> str:
    """
    Validates, stores, and registers an uploaded file.

    Returns an opaque upload_id (UUID string).
    The raw filesystem path is never returned to callers.
    """
    validate_upload(filename, len(content))

    safe_name = _sanitize_filename(filename)
    ts = int(time.time())
    dest_dir = _get_upload_dir() / str(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{ts}_{safe_name}"
    dest.write_bytes(content)

    upload_id = str(uuid.uuid4())
    _registry[upload_id] = (str(dest), time.time())
    return upload_id


def resolve_upload_id(upload_id: str) -> str:
    """
    Returns the absolute path for a registered upload_id.
    Raises KeyError if the ID is unknown or the file has been deleted.
    """
    if upload_id not in _registry:
        raise KeyError(f"upload_id not found: {upload_id!r}")
    path, _ = _registry[upload_id]
    if not os.path.exists(path):
        del _registry[upload_id]
        raise KeyError(f"File no longer on disk: {upload_id!r}")
    return path


def build_attachment_context(upload_ids: list[str]) -> str:
    """
    Builds the prompt block injected before the user task so the LLM knows
    which files are available and which tool to use for each.
    """
    lines = [
        "ATTACHMENTS PROVIDED BY USER:",
        "The user has attached the following files. "
        "Use the appropriate tool to read/analyze each file.",
    ]
    for uid in upload_ids:
        try:
            path = resolve_upload_id(uid)
            size_bytes = os.path.getsize(path)
            size_kb = size_bytes / 1024
            size_str = (
                f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            )
            suffix = Path(path).suffix.lower()
            ftype = suffix.upper().lstrip(".")
            tool = _EXT_TO_TOOL.get(suffix, "read_file")
            lines.append(f"- [{ftype}] {path} ({size_str}) → use `{tool}`")
        except KeyError:
            lines.append(f"- [ERROR] upload_id {uid!r} not found or expired")
    lines.append("")
    return "\n".join(lines)


def cleanup_expired(ttl_hours: int) -> int:
    """
    Removes files older than ttl_hours from disk and the registry.
    Returns the number of files removed.
    Called from the server lifespan and can be scheduled periodically.
    """
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
