"""Repository file tools: read, list, create, and write files."""
from __future__ import annotations

from pathlib import Path

from agentism import config
from langchain_core.tools import tool

from tools.discovery_filters import should_ignore_relative_path
from tools.repo_paths import repo_path

# Entry-point filenames checked (in priority order) when surveying a repo.
_ENTRY_POINT_NAMES = [
    "README.md", "readme.md", "README.rst", "readme.rst",
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json",
    "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "pom.xml",
    "Makefile", "makefile",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".env.example",
    "application.yml", "application.yaml", "application.properties",
]

_MAX_OVERVIEW_FILES = 10        # max entry-point files to inline


@tool
def read_file_in_repo(repo_name: str, relative_path: str) -> str:
    """Read the full contents of a file inside a local repository."""
    target = repo_path(repo_name) / relative_path
    if not target.exists():
        return f"File not found: {target}"
    if not target.is_file():
        return f"Path is not a file: {target}"
    try:
        return target.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def create_file_in_repo(repo_name: str, relative_path: str, content: str) -> str:
    """
    Create a new file in a local repository.

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.
        relative_path: Path relative to the repo root (e.g. "src/main.py").
        content: File content to write.

    Returns:
        Confirmation message, or an error.
    """
    if config.DRY_RUN:
        return f"[DRY-RUN] Would create file at '{relative_path}' in '{repo_name}'."
    target = repo_path(repo_name) / relative_path
    if target.exists():
        return f"Error: file already exists at {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Created: {target}"


# Backwards-compatible alias for tools/__init__.py
create_file = create_file_in_repo


@tool
def write_file_in_repo(repo_name: str, relative_path: str, content: str) -> str:
    """
    Overwrite a file in a local repository (creates parent dirs if needed).

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.
        relative_path: Path relative to the repo root (e.g. "src/main.py").
        content: File content to write.

    Returns:
        Confirmation message, or an error.
    """
    if config.DRY_RUN:
        return f"[DRY-RUN] Would write to file at '{relative_path}' in '{repo_name}'."
    target = repo_path(repo_name) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written: {target}"


@tool
def read_repo_overview(repo_name: str) -> str:
    """
    Return a concise overview of a local repository (top-level files + first few entry points).
    """
    root = repo_path(repo_name)
    if not root.exists():
        return f"Repo not found: {root}"

    top_files = sorted(
        [p.name for p in root.iterdir() if p.is_file()],
        key=lambda n: n.lower(),
    )

    entry_points = []
    for name in _ENTRY_POINT_NAMES:
        candidate = root / name
        if candidate.exists():
            entry_points.append(candidate.name)

    inlined = []
    for ep in entry_points[:_MAX_OVERVIEW_FILES]:
        candidate = root / ep
        try:
            text = candidate.read_text(encoding="utf-8")
            inlined.append(f"\n--- {ep} ---\n{text[:1500]}")
        except Exception:
            inlined.append(f"\n--- {ep} ---\n[unreadable]")

    return (
        f"Repo: {root}\n"
        f"Top-level files ({len(top_files)}):\n"
        + "\n".join(f"  {f}" for f in top_files) +
        "\n\nEntry points found:\n"
        + "\n".join(f"  {e}" for e in entry_points) +
        "\n\n" + "\n".join(inlined)
    )


@tool
def list_repo_files(repo_name: str, recursive: bool = True, max_results: int = 500) -> str:
    """
    List files in a local repository, filtering out noise files.

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.
        recursive: If True (default), recurse into subdirectories.
        max_results: Maximum number of files to return.

    Returns:
        List of relative file paths, or an error.
    """
    root = repo_path(repo_name)
    if not root.exists():
        return f"Repo not found: {root}"

    files = []
    if recursive:
        iterator = root.rglob("**/*")
    else:
        iterator = root.iterdir()

    for p in sorted(iterator):
        if p.is_file():
            rel = p.relative_to(root)
            if should_ignore_relative_path(rel):
                continue
            files.append(str(rel))
            if len(files) >= max_results:
                files.append(f"... truncated at {max_results} files")
                break

    return "\n".join(files)
