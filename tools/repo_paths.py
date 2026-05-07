"""Shared repository path resolution helpers."""
from __future__ import annotations

from collections import deque
from pathlib import Path

from agentism.config import DEV_DIR, WORKSPACE_DIR

_MAX_SEARCH_DEPTH = 8
_SKIPPED_DIR_NAMES = {".git", ".venv", "node_modules", "__pycache__", "build", "dist", "target", ".gradle"}


def _iter_search_dirs(root: Path, max_depth: int = _MAX_SEARCH_DEPTH):
    """Yield candidate directories under root breadth-first up to max_depth."""
    queue: deque[tuple[Path, int]] = deque([(root, 0)])
    while queue:
        current, depth = queue.popleft()
        yield current
        if depth >= max_depth:
            continue
        try:
            for child in current.iterdir():
                if not child.is_dir():
                    continue
                name = child.name
                if name.startswith(".") or name in _SKIPPED_DIR_NAMES:
                    continue
                queue.append((child, depth + 1))
        except PermissionError:
            continue


def find_repo(name: str) -> Path | None:
    """Search DEV_DIR recursively for a repository folder by name."""
    if not DEV_DIR or not DEV_DIR.exists():
        return None

    direct = DEV_DIR / name
    if direct.exists() and direct.is_dir():
        return direct

    for directory in _iter_search_dirs(DEV_DIR):
        if directory.name == name:
            return directory

    return None


def repo_path(repo_name: str) -> Path:
    """Resolve repository location from absolute path, DEV_DIR, or WORKSPACE_DIR."""
    if not repo_name or repo_name.strip() in (".", ".."):
        raise ValueError(
            "repo_name must be the repository folder name (e.g. 'my-repo'), "
            "not '.' or empty."
        )

    p = Path(repo_name)
    if p.is_absolute():
        return p

    found = find_repo(repo_name)
    if found:
        return found

    return WORKSPACE_DIR / repo_name

