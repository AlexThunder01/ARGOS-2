"""
ARGOS-2 Tool — Document Parser (PDF, CSV, JSON, XML).

Extracts text content from structured documents. Critical for GAIA
benchmark tasks that require reading and analyzing file contents.

Dependencies:
  - pypdf (PDF parsing, pure Python, zero system deps)
  - Built-in csv, json, xml modules
"""

import csv
import json
import os

from .helpers import _get_arg, _normalize_path


def read_pdf_tool(inp):
    """
    Extracts text from a PDF file.

    Input:
        {"filename": "report.pdf"}
        {"filename": "report.pdf", "pages": "1-3"}

    Returns:
        Extracted text content.
    """
    fname = _get_arg(inp, ["filename", "path", "file", "pdf"])
    if not fname:
        return "Error: No filename specified. Use {'filename': 'path/to/file.pdf'}."

    path = _normalize_path(fname)
    if not os.path.exists(path):
        return f"Error: File '{path}' not found."
    if not path.lower().endswith(".pdf"):
        return f"Error: '{os.path.basename(path)}' is not a PDF file."

    try:
        from pypdf import PdfReader
    except ImportError:
        return "Error: pypdf not installed. Run: pip install pypdf"

    try:
        reader = PdfReader(path)
        total_pages = len(reader.pages)

        # Parse page range if specified
        page_range = None
        if isinstance(inp, dict) and "pages" in inp:
            page_spec = str(inp["pages"])
            if "-" in page_spec:
                start, end = page_spec.split("-", 1)
                page_range = range(max(0, int(start) - 1), min(total_pages, int(end)))
            else:
                page_idx = int(page_spec) - 1
                if 0 <= page_idx < total_pages:
                    page_range = range(page_idx, page_idx + 1)

        if page_range is None:
            page_range = range(min(total_pages, 20))  # Default: first 20 pages

        text_parts = []
        for i in page_range:
            page_text = reader.pages[i].extract_text()
            if page_text and page_text.strip():
                text_parts.append(f"--- Page {i + 1} ---\n{page_text.strip()}")

        if not text_parts:
            return f"📄 PDF '{os.path.basename(path)}' ({total_pages} pages): No extractable text (may be image-based, use OCR)."

        content = "\n\n".join(text_parts)
        # Truncate very long documents
        if len(content) > 8000:
            content = (
                content[:8000]
                + f"\n\n... [truncated, showing {len(page_range)}/{total_pages} pages]"
            )

        return f"📄 PDF '{os.path.basename(path)}' ({total_pages} pages):\n\n{content}"

    except Exception as e:
        return f"Error reading PDF: {e}"


def read_csv_tool(inp):
    """
    Reads a CSV file and returns a structured summary.

    Input:
        {"filename": "data.csv"}
        {"filename": "data.csv", "rows": 10}

    Returns:
        Column headers and first N rows.
    """
    fname = _get_arg(inp, ["filename", "path", "file", "csv"])
    if not fname:
        return "Error: No filename specified."

    path = _normalize_path(fname)
    if not os.path.exists(path):
        return f"Error: File '{path}' not found."

    max_rows = 20
    if isinstance(inp, dict) and "rows" in inp:
        max_rows = min(int(inp["rows"]), 100)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            # Detect delimiter
            sample = f.read(4096)
            f.seek(0)
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            reader = csv.reader(f, dialect)

            rows = []
            for i, row in enumerate(reader):
                rows.append(row)
                if i >= max_rows:
                    break

        if not rows:
            return f"📊 CSV '{os.path.basename(path)}': Empty file."

        # Format as table
        header = " | ".join(rows[0])
        separator = "-" * len(header)
        data_rows = [" | ".join(r) for r in rows[1:]]

        output = f"📊 CSV '{os.path.basename(path)}' ({len(rows) - 1} rows shown):\n\n"
        output += f"{header}\n{separator}\n"
        output += "\n".join(data_rows)

        return output

    except Exception as e:
        return f"Error reading CSV: {e}"


def read_json_tool(inp):
    """
    Reads and pretty-prints a JSON file.

    Input:
        {"filename": "config.json"}

    Returns:
        Formatted JSON content.
    """
    fname = _get_arg(inp, ["filename", "path", "file"])
    if not fname:
        return "Error: No filename specified."

    path = _normalize_path(fname)
    if not os.path.exists(path):
        return f"Error: File '{path}' not found."

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        if len(formatted) > 5000:
            formatted = formatted[:5000] + "\n... [truncated]"

        return f"📋 JSON '{os.path.basename(path)}':\n\n{formatted}"

    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON file: {e}"
    except Exception as e:
        return f"Error reading JSON: {e}"
