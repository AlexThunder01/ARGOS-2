"""Shared utility functions for all tool modules."""

import os

# Paths outside this set are rejected by _normalize_path.
# We allow the user's home directory tree and the upload workspace.
_HOME = os.path.expanduser("~")


def _get_allowed_roots() -> list[str]:
    """Returns the list of sandbox roots allowed by _normalize_path."""
    roots = [_HOME]
    try:
        from src.config import WORKSPACE_DIR

        workspace = os.path.realpath(WORKSPACE_DIR)
        if workspace not in roots:
            roots.append(workspace)
    except Exception:
        pass
    return roots


def _get_desktop_path():
    home = _HOME
    # Try XDG user-dirs config
    xdg_config = os.path.join(home, ".config", "user-dirs.dirs")
    if os.path.exists(xdg_config):
        try:
            with open(xdg_config) as f:
                for line in f:
                    if line.startswith("XDG_DESKTOP_DIR"):
                        parts = line.split("=")
                        if len(parts) > 1:
                            path = parts[1].strip().strip('"')
                            path = path.replace("$HOME", home)
                            if os.path.isdir(path):
                                return path
        except Exception:
            pass

    # Common fallback directory names
    for c in ["Scrivania", "Desktop", "Escritorio"]:
        path = os.path.join(home, c)
        if os.path.isdir(path):
            return path
    return home


def _normalize_path(path_str):
    """
    Resolves a path and enforces that the result stays inside the user's home
    directory (sandbox). Raises ValueError for path traversal attempts.
    """
    if not path_str:
        return _get_desktop_path()
    path_str = str(path_str).strip()

    # Handle Windows-style paths (C:/Users/...) hallucinated by the LLM on Linux
    if ":" in path_str and not path_str.startswith("/"):
        base_name = os.path.basename(path_str.replace("\\", "/"))
        return os.path.join(_get_desktop_path(), base_name)

    if "~" in path_str:
        path_str = os.path.expanduser(path_str)

    if os.path.isabs(path_str):
        candidate = path_str
    else:
        candidate = os.path.join(_get_desktop_path(), path_str)

    # Resolve symlinks and ".." components before the sandbox check
    real = os.path.realpath(candidate)

    # Enforce that the resolved path stays inside an allowed root
    allowed_roots = _get_allowed_roots()
    if not any(real == root or real.startswith(root + os.sep) for root in allowed_roots):
        raise ValueError(
            f"Path traversal attempt blocked: '{path_str}' resolves to '{real}' "
            f"which is outside the allowed directories."
        )

    return real


def _get_arg(inp, keys, default=None):
    """Extracts an argument by searching across multiple possible key names."""
    if isinstance(inp, str):
        return inp
    if isinstance(inp, dict):
        for k in keys:
            if k in inp and inp[k]:
                return inp[k]
    return default
