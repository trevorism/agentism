"""Repository file tools: read, list, create, and write files."""
from __future__ import annotations

import config
from langchain_core.tools import tool

from tools.discovery_filters import should_ignore_relative_path
from tools.repo_paths import repo_path


@tool
def read_file_in_repo(repo_name: str, relative_path: str) -> str:
    """Read the full contents of a file inside a local repository."""
    target = repo_path(repo_name) / relative_path
    if not target.exists():
        return f"File not found: {target}"
    if not target.is_file():
        return f"Path is not a file: {target}"
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def list_repo_files(repo_name: str, subdir: str = "", pattern: str = "*") -> str:
    """List files in a local repository directory, filtered by glob pattern."""
    root = repo_path(repo_name)
    search_dir = root / subdir if subdir else root
    if not search_dir.exists():
        return f"Directory not found: {search_dir}"

    try:
        files = sorted(search_dir.glob(pattern))
        visible_files = [
            f for f in files if f.is_file() and not should_ignore_relative_path(f.relative_to(root))
        ]
        if not visible_files:
            return f"No files matching '{pattern}' in {search_dir}"
        return "\n".join(str(f.relative_to(root)) for f in visible_files)
    except Exception as e:
        return f"Error listing files: {e}"


@tool
def write_file_in_repo(repo_name: str, relative_path: str, content: str) -> str:
    """Write (create or overwrite) a file inside a local repository."""
    target = repo_path(repo_name) / relative_path
    if config.DRY_RUN:
        preview = content[:200] + ("..." if len(content) > 200 else "")
        return f"[DRY-RUN] Would write {len(content)} chars to: {target}\nPreview:\n{preview}"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written: {target}"


@tool
def create_file(repo_name: str, relative_path: str, content: str) -> str:
    """Create a new file inside a local repo without overwriting existing files."""
    target = repo_path(repo_name) / relative_path

    if target.exists():
        return f"Error: file already exists: {target}"

    if config.DRY_RUN:
        preview = content[:200] + ("..." if len(content) > 200 else "")
        return f"[DRY-RUN] Would create file: {target}\nPreview:\n{preview}"

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Created: {target}"
    except Exception as e:
        return f"Error creating file: {e}"

