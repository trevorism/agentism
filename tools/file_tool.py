"""File operations for local repositories – read, write, create, and list."""
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from tools.discovery_filters import should_ignore_relative_path
from tools.repo_paths import repo_path


def _list_files(
    repo_root: Path,
    recursive: bool = True,
    max_results: int = 200,
) -> tuple[list[Path], bool]:
    """List filtered files and whether the output had to be truncated."""
    files = []
    if recursive:
        iterator = repo_root.rglob("*")
    else:
        iterator = repo_root.glob("*")
    for item in iterator:
        if not item.is_file():
            continue
        rel = item.relative_to(repo_root)
        if should_ignore_relative_path(rel):
            continue
        files.append(rel)
    files.sort()
    is_truncated = len(files) > max_results
    return files[:max_results], is_truncated


@tool
def read_repo_overview(repo_name: str) -> str:
    """
    Return a concise overview of a local repository (top-level files + first few entry points).

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.

    Returns:
        Overview of top-level files and key entry points, or an error message.
    """
    repo_root = repo_path(repo_name)
    if not repo_root.exists():
        return f"Repo not found: {repo_root}. Use git_clone first."

    # List top-level files and directories
    top_level = []
    for item in sorted(repo_root.iterdir()):
        if should_ignore_relative_path(item.relative_to(repo_root)):
            continue
        kind = "dir" if item.is_dir() else "file"
        top_level.append(f"  [{kind}] {item.name}")

    output = f"Repository: {repo_root.name}\nTop-level items:\n"
    output += "\n".join(top_level[:50])

    # Look for common entry points
    entry_points = []
    for pattern in ["main.py", "app.py", "__main__.py", "index.js", "index.ts", "program.cs", "Cargo.toml", "pom.xml", "build.gradle", "package.json"]:
        ep = repo_root / pattern
        if ep.exists():
            entry_points.append(f"  - {pattern}")

    if entry_points:
        output += "\n\nEntry points:\n"
        output += "\n".join(entry_points)

    return output


@tool
def list_repo_files(
    repo_name: str,
    recursive: bool = True,
    max_results: int = 200,
) -> str:
    """
    List files in a local repository, filtering out noise files.

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.
        recursive: If True, list files recursively through all subdirectories.
        max_results: Maximum number of files to return.

    Returns:
        Newline-separated list of relative file paths, or an error message.
    """
    repo_root = repo_path(repo_name)
    if not repo_root.exists():
        return f"Repo not found: {repo_root}. Use git_clone first."

    files, is_truncated = _list_files(repo_root, recursive=recursive, max_results=max_results)
    output = "\n".join(str(f) for f in files)
    if is_truncated:
        output += f"\n... truncated at {max_results} files (use max_results to show more)"
    return output


@tool
def read_file_in_repo(repo_name: str, relative_path: str) -> str:
    """
    Read the contents of a file in a local repository.

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.
        relative_path: Path to the file relative to the repo root.

    Returns:
        File contents as text, or an error message.
    """
    repo_root = repo_path(repo_name)
    target = repo_root / relative_path
    if not target.exists():
        return f"File not found: {target}"
    if not target.is_file():
        return f"Not a file: {target}"
    try:
        return target.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def write_file_in_repo(repo_name: str, relative_path: str, content: str) -> str:
    """
    Write content to a file in a local repository.

    Creates parent directories if needed. Overwrites existing files.

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.
        relative_path: Path to the file relative to the repo root.
        content: Text content to write.

    Returns:
        Confirmation message, or an error message.
    """
    repo_root = repo_path(repo_name)
    target = repo_root / relative_path
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Written: {target}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def create_file(repo_name: str, relative_path: str, content: str) -> str:
    """
    Create a new file in a local repository.

    Fails if the file already exists to prevent accidental overwrites.
    Use write_file_in_repo to overwrite existing files intentionally.

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.
        relative_path: Path to the file relative to the repo root.
        content: Text content to write.

    Returns:
        Confirmation message, or an error message.
    """
    repo_root = repo_path(repo_name)
    target = repo_root / relative_path
    if target.exists():
        return f"Error: file already exists: {target}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Created: {target}"
    except Exception as e:
        return f"Error creating file: {e}"