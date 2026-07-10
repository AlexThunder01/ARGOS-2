"""
ARGOS-2 Tool — Secure File Downloader.

Downloads files from the internet to a local path within the user's home
directory.  Designed with defence-in-depth:

Security measures:
  1. Path sandboxing — saves only inside $HOME (via _normalize_path).
  2. Blocked extensions — executables (.exe, .sh, .bat, .msi, .deb, .rpm,
     .appimage, .com, .cmd, .ps1, .vbs, .jar) are rejected.
  3. Size cap — aborts if Content-Length exceeds MAX_DOWNLOAD_BYTES (100 MB).
  4. HTTPS enforced — plain HTTP URLs are rejected unless explicitly allowed.
  5. Streaming — downloads in chunks so RAM is never fully loaded.
  6. Content-Disposition — extracts server-suggested filename when available.

Dependencies:
  - requests (already in requirements.txt)
"""

import logging
import os
import re

import requests as http_client

from .helpers import _get_arg, _normalize_path

logger = logging.getLogger("argos")

# ── Constraints ───────────────────────────────────────────────────────────────

# Maximum download size (100 MB)
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

# Download timeout — connect / read (seconds)
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 300

# Extensions that are NEVER allowed to be downloaded
_BLOCKED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".exe",
        ".msi",
        ".bat",
        ".cmd",
        ".com",
        ".ps1",
        ".vbs",
        ".sh",
        ".bash",
        ".csh",
        ".ksh",
        ".zsh",
        ".deb",
        ".rpm",
        ".appimage",
        ".snap",
        ".flatpak",
        ".jar",
        ".war",
        ".elf",
        ".dll",
        ".so",
        ".dylib",
    }
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_filename_from_cd(content_disposition: str) -> str | None:
    """Extracts filename from Content-Disposition header (RFC 6266)."""
    if not content_disposition:
        return None
    # Try filename*= (RFC 5987 — UTF-8 encoded)
    match = re.search(
        r"filename\*=(?:UTF-8''|utf-8'')(.+?)(?:;|$)",
        content_disposition,
        re.IGNORECASE,
    )
    if match:
        from urllib.parse import unquote

        return unquote(match.group(1).strip().strip('"'))
    # Try plain filename=
    match = re.search(r'filename="?([^";]+)"?', content_disposition, re.IGNORECASE)
    if match:
        return match.group(1).strip().strip('"')
    return None


def _extract_filename_from_url(url: str) -> str:
    """Extracts a reasonable filename from the URL path."""
    from urllib.parse import unquote, urlparse

    path = urlparse(url).path
    name = os.path.basename(unquote(path))
    # Remove query strings that leaked into the filename
    name = name.split("?")[0].split("#")[0]
    return name if name else "download"


def _is_blocked(filename: str) -> bool:
    """Returns True if the file extension is in the block list."""
    _, ext = os.path.splitext(filename.lower())
    return ext in _BLOCKED_EXTENSIONS


# ── Tool ──────────────────────────────────────────────────────────────────────


def download_file_tool(inp: dict) -> str:
    """
    Downloads a file from a URL and saves it to a local path.

    Input:
        {"url": "https://example.com/file.pdf", "save_path": "/home/user/Desktop/file.pdf"}
        or {"url": "https://example.com/file.pdf"} (saves to Desktop with auto-detected name)

    Returns:
        Success message with file path and size, or error.
    """
    url = _get_arg(inp, ["url", "link", "href"])
    if not url:
        return "Error: No URL specified. Use {'url': 'https://...'}."

    url = str(url).strip()

    # ── Security: enforce HTTPS ────────────────────────────────────────────
    if url.startswith("http://"):
        return "Error: HTTP (non-encrypted) URLs are blocked for security. Use HTTPS instead."
    if not url.startswith("https://"):
        url = "https://" + url

    # ── Resolve save path ──────────────────────────────────────────────────
    save_path = _get_arg(inp, ["save_path", "path", "filename", "destination"], default=None)

    try:
        # Start the download (streaming for large files)
        response = http_client.get(
            url,
            headers=HEADERS,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            stream=True,
            allow_redirects=True,
        )
        response.raise_for_status()

        # ── Determine filename ─────────────────────────────────────────────
        cd = response.headers.get("Content-Disposition", "")
        server_name = _extract_filename_from_cd(cd)
        url_name = _extract_filename_from_url(url)

        if save_path:
            # User specified a path — normalize it (sandbox check)
            try:
                resolved = _normalize_path(save_path)
            except ValueError as ve:
                return f"Error: {ve}"
            # If save_path is a directory, append the auto-detected filename
            if os.path.isdir(resolved):
                final_name = server_name or url_name
                resolved = os.path.join(resolved, final_name)
        else:
            # No save_path — save to Desktop with auto-detected name
            final_name = server_name or url_name
            try:
                resolved = _normalize_path(final_name)
            except ValueError as ve:
                return f"Error: {ve}"

        # ── Security: block dangerous extensions ───────────────────────────
        if _is_blocked(resolved):
            _, ext = os.path.splitext(resolved)
            return (
                f"Error: Downloading files with extension '{ext}' is blocked for security reasons."
            )

        # ── Security: check size before downloading ────────────────────────
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
            size_mb = int(content_length) / (1024 * 1024)
            limit_mb = MAX_DOWNLOAD_BYTES / (1024 * 1024)
            return (
                f"Error: File is too large ({size_mb:.1f} MB). Maximum allowed: {limit_mb:.0f} MB."
            )

        # ── Download in chunks ─────────────────────────────────────────────
        # Ensure parent directory exists
        parent = os.path.dirname(resolved)
        if parent:
            os.makedirs(parent, exist_ok=True)

        downloaded = 0
        with open(resolved, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    f.close()
                    os.remove(resolved)
                    return (
                        f"Error: Download aborted — exceeded size limit "
                        f"({MAX_DOWNLOAD_BYTES / (1024 * 1024):.0f} MB)."
                    )
                f.write(chunk)

        # ── Format result ──────────────────────────────────────────────────
        if downloaded < 1024:
            size_str = f"{downloaded} B"
        elif downloaded < 1024 * 1024:
            size_str = f"{downloaded / 1024:.1f} KB"
        else:
            size_str = f"{downloaded / (1024 * 1024):.1f} MB"

        logger.info(f"[download_file] Saved {url} → {resolved} ({size_str})")
        return f"✅ Downloaded successfully!\n📁 Path: {resolved}\n📦 Size: {size_str}"

    except http_client.exceptions.Timeout:
        return f"Error: Download timed out for '{url}'."
    except http_client.exceptions.ConnectionError:
        return f"Error: Could not connect to '{url}'. Check the URL or your network."
    except http_client.exceptions.HTTPError as e:
        return f"Error: HTTP {e.response.status_code} for '{url}'."
    except ValueError as ve:
        return f"Error: {ve}"
    except Exception as e:
        return f"Error downloading '{url}': {e}"
