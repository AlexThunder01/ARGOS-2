"""
Unit tests for src/upload.py — upload service.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")

import pytest

import src.upload as upload_module
from src.upload import (
    ALLOWED_EXTENSIONS,
    build_attachment_context,
    cleanup_expired,
    resolve_upload_id,
    save_upload,
    validate_upload,
)


@pytest.fixture(autouse=True)
def isolated_upload(tmp_path, monkeypatch):
    """Redirect uploads to a temp dir and reset the in-memory registry."""
    monkeypatch.setattr(upload_module, "_registry", {})

    # Patch _get_upload_dir to use tmp_path
    monkeypatch.setattr(upload_module, "_get_upload_dir", lambda: tmp_path / "uploads")
    # Patch _get_max_bytes to a small value (20 MB) for most tests
    monkeypatch.setattr(upload_module, "_get_max_bytes", lambda: 20 * 1024 * 1024)
    yield


# ── validate_upload ────────────────────────────────────────────────────────


def test_validate_accepts_pdf():
    validate_upload("report.pdf", 100)  # no error


def test_validate_accepts_png():
    validate_upload("screenshot.png", 500)


def test_validate_rejects_unknown_extension():
    with pytest.raises(ValueError, match="not supported"):
        validate_upload("malware.exe", 100)


def test_validate_rejects_no_extension():
    with pytest.raises(ValueError, match="not supported"):
        validate_upload("Makefile", 100)


def test_validate_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(upload_module, "_get_max_bytes", lambda: 1024)
    with pytest.raises(ValueError, match="too large"):
        validate_upload("report.pdf", 2048)


def test_validate_exact_limit_is_ok(monkeypatch):
    monkeypatch.setattr(upload_module, "_get_max_bytes", lambda: 1024)
    validate_upload("report.pdf", 1024)  # no error


# ── save_upload ────────────────────────────────────────────────────────────


def test_save_upload_returns_uuid(tmp_path):
    uid = save_upload(user_id=1, filename="test.pdf", content=b"%PDF-1.4 fake")
    assert len(uid) == 36  # UUID format
    assert "-" in uid


def test_save_upload_file_exists_on_disk(tmp_path):
    uid = save_upload(user_id=1, filename="data.csv", content=b"a,b,c\n1,2,3")
    path = resolve_upload_id(uid)
    assert os.path.isfile(path)
    assert open(path, "rb").read() == b"a,b,c\n1,2,3"


def test_save_upload_in_correct_directory(tmp_path):
    uid = save_upload(user_id=42, filename="img.png", content=b"\x89PNG fake")
    path = resolve_upload_id(uid)
    # Must be inside uploads/42/
    assert "/42/" in path or "\\42\\" in path


def test_save_upload_sanitizes_path_traversal(tmp_path):
    uid = save_upload(user_id=0, filename="../../etc/passwd.txt", content=b"root:x")
    path = resolve_upload_id(uid)
    # The filename should NOT contain .. or /
    filename = os.path.basename(path)
    assert ".." not in filename
    assert "/" not in filename


def test_save_upload_rejects_invalid_extension():
    with pytest.raises(ValueError, match="not supported"):
        save_upload(user_id=0, filename="bad.exe", content=b"MZ payload")


# ── resolve_upload_id ──────────────────────────────────────────────────────


def test_resolve_returns_existing_path():
    uid = save_upload(user_id=0, filename="note.txt", content=b"hello")
    path = resolve_upload_id(uid)
    assert os.path.exists(path)


def test_resolve_raises_for_unknown_id():
    with pytest.raises(KeyError):
        resolve_upload_id("00000000-0000-0000-0000-000000000000")


def test_resolve_raises_if_file_deleted(tmp_path):
    uid = save_upload(user_id=0, filename="temp.txt", content=b"x")
    path = resolve_upload_id(uid)
    os.remove(path)
    with pytest.raises(KeyError):
        resolve_upload_id(uid)


# ── build_attachment_context ───────────────────────────────────────────────


def test_build_context_contains_path_and_tool():
    uid = save_upload(user_id=0, filename="report.pdf", content=b"%PDF")
    ctx = build_attachment_context([uid])
    assert "ATTACHMENTS" in ctx
    assert "read_pdf" in ctx
    assert "PDF" in ctx


def test_build_context_multiple_files():
    u1 = save_upload(user_id=0, filename="data.csv", content=b"a,b")
    u2 = save_upload(user_id=0, filename="photo.png", content=b"\x89PNG")
    ctx = build_attachment_context([u1, u2])
    assert "read_csv" in ctx
    assert "analyze_image" in ctx


def test_build_context_unknown_id():
    ctx = build_attachment_context(["nonexistent-uuid"])
    assert "[ERROR]" in ctx


# ── cleanup_expired ────────────────────────────────────────────────────────


def test_cleanup_removes_expired(monkeypatch):
    uid = save_upload(user_id=0, filename="old.txt", content=b"old data")
    # Backdate the registry entry
    upload_module._registry[uid] = (upload_module._registry[uid][0], time.time() - 7200)
    removed = cleanup_expired(ttl_hours=1)
    assert removed == 1
    assert uid not in upload_module._registry


def test_cleanup_keeps_recent():
    uid = save_upload(user_id=0, filename="new.txt", content=b"new data")
    removed = cleanup_expired(ttl_hours=24)
    assert removed == 0
    assert uid in upload_module._registry


def test_cleanup_handles_missing_file(monkeypatch):
    uid = save_upload(user_id=0, filename="gone.txt", content=b"x")
    path, created_at = upload_module._registry[uid]
    os.remove(path)
    # Backdate
    upload_module._registry[uid] = (path, time.time() - 7200)
    # Should not raise
    removed = cleanup_expired(ttl_hours=1)
    assert removed == 1
