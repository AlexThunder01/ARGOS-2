"""
Tests for CLI attachment helpers in scripts/main.py.
Tests _resolve_attachments and _extract_inline_attachments directly.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")

import pytest

import src.upload as upload_module


@pytest.fixture(autouse=True)
def _reset_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(upload_module, "_registry", {})
    monkeypatch.setattr(upload_module, "_get_upload_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(upload_module, "_get_max_bytes", lambda: 20 * 1024 * 1024)


def _import_helpers():
    """Import CLI helpers after sys.path is set up."""
    import importlib
    import scripts.main as cli
    importlib.reload(cli)
    return cli._resolve_attachments, cli._extract_inline_attachments


# ── _resolve_attachments ───────────────────────────────────────────────────

class TestResolveAttachments:
    def test_valid_file_returns_upload_id(self, tmp_path):
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 fake content")
        _resolve, _ = _import_helpers()
        uids, ctx = _resolve([str(f)], user_id=0)
        assert len(uids) == 1
        assert "ATTACHMENTS" in ctx
        assert "report.pdf" in ctx

    def test_nonexistent_file_is_skipped(self, tmp_path, capsys):
        _resolve, _ = _import_helpers()
        uids, ctx = _resolve([str(tmp_path / "missing.pdf")], user_id=0)
        assert uids == []
        assert ctx == ""
        out = capsys.readouterr().out
        assert "not found" in out.lower() or "skipped" in out.lower()

    def test_invalid_extension_is_skipped(self, tmp_path, capsys):
        f = tmp_path / "virus.exe"
        f.write_bytes(b"MZ payload")
        _resolve, _ = _import_helpers()
        uids, ctx = _resolve([str(f)], user_id=0)
        assert uids == []
        out = capsys.readouterr().out
        assert "rejected" in out.lower() or "skipped" in out.lower()

    def test_multiple_files_all_registered(self, tmp_path):
        f1 = tmp_path / "a.pdf"
        f2 = tmp_path / "b.csv"
        f1.write_bytes(b"%PDF data")
        f2.write_bytes(b"col,val\n1,2")
        _resolve, _ = _import_helpers()
        uids, ctx = _resolve([str(f1), str(f2)], user_id=0)
        assert len(uids) == 2
        assert "read_pdf" in ctx
        assert "read_csv" in ctx

    def test_empty_list_returns_empty(self):
        _resolve, _ = _import_helpers()
        uids, ctx = _resolve([], user_id=0)
        assert uids == []
        assert ctx == ""


# ── _extract_inline_attachments ────────────────────────────────────────────

class TestExtractInlineAttachments:
    def test_extracts_at_file_token(self, tmp_path):
        f = tmp_path / "note.txt"
        f.write_bytes(b"hello world")
        _, _extract = _import_helpers()
        text = f"Analyze this @file:{f}"
        cleaned, ctx = _extract(text, user_id=0)
        assert "@file:" not in cleaned
        assert "note.txt" in ctx

    def test_no_at_file_token_returns_unchanged(self):
        _, _extract = _import_helpers()
        text = "Just a normal message"
        cleaned, ctx = _extract(text, user_id=0)
        assert cleaned == text
        assert ctx == ""

    def test_multiple_at_file_tokens(self, tmp_path):
        f1 = tmp_path / "a.pdf"
        f2 = tmp_path / "b.png"
        f1.write_bytes(b"%PDF")
        f2.write_bytes(b"\x89PNG")
        _, _extract = _import_helpers()
        text = f"Look at @file:{f1} and @file:{f2}"
        cleaned, ctx = _extract(text, user_id=0)
        assert "@file:" not in cleaned
        assert "read_pdf" in ctx
        assert "analyze_image" in ctx
