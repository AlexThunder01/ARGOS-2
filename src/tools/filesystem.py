"""File system CRUD tools."""
import os
import shutil
from .helpers import _get_arg, _normalize_path, _get_desktop_path


def list_files_tool(inp):
    raw_path = _get_arg(inp, ["path", "directory", "folder"])
    if raw_path in [".", "DESKTOP", None]: target = _get_desktop_path()
    else: target = _normalize_path(raw_path)

    if not os.path.exists(target): return f"Error: '{target}' does not exist."
    try:
        items = [f for f in os.listdir(target) if not f.startswith('.')]
        items.sort()
        return f"📂 '{os.path.basename(target)}': {', '.join(items[:50])}"
    except Exception as e: return f"Error: {e}"

def read_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "file"])
    path = _normalize_path(fname)
    if not os.path.exists(path): return "File not found."
    if os.path.isdir(path): return "Target is a directory, use list_files instead."
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f"📄 CONTENT:\n{f.read(3000)}"
    except Exception as e: return f"Error: {e}"

def create_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "name"], "untitled.txt")
    if "." not in fname: fname += ".txt"
    path = _normalize_path(fname)
    
    content = inp.get("content", "") if isinstance(inp, dict) else ""

    if os.path.exists(path): return f"⚠️ File '{os.path.basename(path)}' already exists."
    try:
        with open(path, "w", encoding="utf-8") as f: f.write(content)
        return f"✅ Created: {path}"
    except Exception as e: return f"Error: {e}"

def create_directory_tool(inp):
    name = _get_arg(inp, ["name", "path", "directory", "dirname"])
    if not name: return "Error: Please specify a directory name."
    
    path = _normalize_path(name)
    
    if os.path.exists(path):
        return f"⚠️ Directory or file '{os.path.basename(path)}' already exists."
    
    try:
        os.makedirs(path, exist_ok=True)
        return f"✅ Directory created: {path}"
    except Exception as e:
        return f"Directory creation error: {e}"
    
def delete_directory_tool(inp):
    name = _get_arg(inp, ["name", "path", "directory", "dirname"])
    if not name: return "Error: Please specify the directory name to delete."
    
    path = _normalize_path(name)
    
    if not os.path.exists(path):
        return f"Error: Directory '{path}' does not exist."
    if not os.path.isdir(path):
        return f"Error: '{path}' is not a directory (possibly a file)."
    
    try:
        shutil.rmtree(path)
        return f"🗑️ Directory successfully deleted: {path}"
    except Exception as e:
        return f"Directory deletion error: {e}"


def modify_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "file"])
    if not fname: return "Error: Please specify the filename to modify."
    
    path = _normalize_path(fname)
    if not os.path.exists(path): return "Error: File not found."

    content = inp.get("content", "") if isinstance(inp, dict) else ""
    mode = "a" if isinstance(inp, dict) and inp.get("mode") == "append" else "w"

    try:
        with open(path, mode, encoding="utf-8") as f:
            if mode == "a": f.write("\n" + content)
            else: f.write(content)
        return f"✅ Modified ({mode}): {path}"
    except Exception as e: return f"Error: {e}"

def rename_file_tool(inp):
    old = _get_arg(inp, ["old_name", "old_path", "filename", "current_name"])
    new = _get_arg(inp, ["new_name", "new_path", "name"])
    
    if not old or not new: return "Error: Both 'old_name' and 'new_name' are required."
    
    p_old = _normalize_path(old)
    p_new = _normalize_path(new)
    
    if not os.path.exists(p_old): return f"Error: '{old}' not found."
    if os.path.exists(p_new): return f"Error: '{new}' already exists."
    
    try:
        os.rename(p_old, p_new)
        return f"✅ Renamed: {old} -> {new}"
    except Exception as e: return f"Rename error: {e}"

def delete_file_tool(inp):
    fname = _get_arg(inp, ["filename", "path", "file"])
    path = _normalize_path(fname)
    if not os.path.exists(path): return "File not found."
    try:
        if os.path.isdir(path): shutil.rmtree(path)
        else: os.remove(path)
        return f"🗑️ Deleted: {path}"
    except Exception as e: return f"Error: {e}"
