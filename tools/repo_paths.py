"""Shared repository path resolution helpers."""
from __future__ import annotations

from pathlib import Path

from agentism.config import DEV_DIR, WORKSPACE_DIR


def find_repo(name: str) -> Path | None:
    """Search DEV_DIR for a repository folder by name, including one nested level."""
    if not DEV_DIR or not DEV_DIR.exists():
        return None

    candidate = DEV_DIR / name
    if candidate.exists():
        return candidate

    try:
        for subdir in DEV_DIR.iterdir():
            if subdir.is_dir() and not subdir.name.startswith("."):
                candidate = subdir / name
                if candidate.exists():
                    return candidate
    except PermissionError:
        pass

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

