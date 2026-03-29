"""Shared utility functions for all tool modules."""
import os


def _get_desktop_path():
    home = os.path.expanduser("~")
    # Try XDG user-dirs config
    xdg_config = os.path.join(home, ".config", "user-dirs.dirs")
    if os.path.exists(xdg_config):
        try:
            with open(xdg_config, "r") as f:
                for line in f:
                    if line.startswith("XDG_DESKTOP_DIR"):
                        parts = line.split("=")
                        if len(parts) > 1:
                            path = parts[1].strip().strip('"')
                            path = path.replace("$HOME", home)
                            if os.path.isdir(path): return path
        except: pass
    
    # Common fallback directory names
    for c in ["Scrivania", "Desktop", "Escritorio"]:
        path = os.path.join(home, c)
        if os.path.isdir(path): return path
    return home

def _normalize_path(path_str):
    if not path_str: return _get_desktop_path()
    path_str = str(path_str).strip()
    
    # FIX: Handle Windows-style paths (C:/Users/...) hallucinated by the LLM on Linux
    if ":" in path_str and not path_str.startswith("/"):
        base_name = os.path.basename(path_str.replace("\\", "/"))
        return os.path.join(_get_desktop_path(), base_name)

    if "~" in path_str:
        path_str = os.path.expanduser(path_str)

    if os.path.isabs(path_str):
        return path_str
        
    return os.path.join(_get_desktop_path(), path_str)


def _get_arg(inp, keys, default=None):
    """Extracts an argument by searching across multiple possible key names."""
    if isinstance(inp, str): return inp
    if isinstance(inp, dict):
        for k in keys:
            if k in inp and inp[k]: return inp[k]
    return default
