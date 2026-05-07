"""Repository file tools: read, list, create, and write files."""
from __future__ import annotations

from pathlib import Path

from agentism import config
from langchain_core.tools import tool

from tools.discovery_filters import should_ignore_relative_path, IGNORED_DIR_NAMES
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
        return target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def list_repo_files(
    repo_name: str,
    subdir: str = "",
    pattern: str = "*",
    recursive: bool = True,
    max_results: int = 2000,
) -> str:
    """List files in a local repository with optional recursion and glob filtering."""
    if max_results < 1:
        return "max_results must be at least 1"

    root = repo_path(repo_name)
    search_dir = root / subdir if subdir else root
    if not search_dir.exists():
        return f"Directory not found: {search_dir}"

    try:
        iterator = search_dir.rglob(pattern) if recursive else search_dir.glob(pattern)
        visible_files: list[Path] = []
        for entry in iterator:
            if not entry.is_file():
                continue
            rel = entry.relative_to(root)
            if should_ignore_relative_path(rel):
                continue
            visible_files.append(rel)

        visible_files.sort(key=lambda p: p.as_posix().lower())

        if not visible_files:
            return f"No files matching '{pattern}' in {search_dir}"

        limited = visible_files[:max_results]
        lines = [p.as_posix() for p in limited]
        if len(visible_files) > max_results:
            lines.append(
                f"... truncated at {max_results} files (found {len(visible_files)}). "
                "Refine with subdir/pattern or raise max_results."
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing files: {e}"


@tool
def read_repo_overview(repo_name: str) -> str:
    """
    Get a structural overview of a repository plus the contents of its key entry-point files.

    Call this first whenever you need to understand a repo. It:
    1. Lists the top-level directory tree (depth ≤ 2, skipping noise dirs).
    2. Auto-reads well-known entry-point files (README, pyproject.toml, package.json,
       build.gradle, Makefile, application.yml, etc.) from anywhere in the repo.

    Use the returned structure and file contents to decide *which* source files are
    relevant for the user's question — then call read_file_in_repo on those.
    Do NOT call list_repo_files recursively as a first step.
    """
    root = repo_path(repo_name)
    if not root.exists():
        return f"Repository not found: {root}"

    # --- 1. Shallow directory tree (depth ≤ 2) --------------------------------
    tree_lines: list[str] = [f"{root.name}/"]
    try:
        for item in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if item.name in IGNORED_DIR_NAMES or item.name.startswith("."):
                continue
            if item.is_dir():
                tree_lines.append(f"  {item.name}/")
                try:
                    for child in sorted(item.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                        if child.name in IGNORED_DIR_NAMES or child.name.startswith("."):
                            continue
                        suffix = "/" if child.is_dir() else ""
                        tree_lines.append(f"    {child.name}{suffix}")
                except PermissionError:
                    pass
            else:
                tree_lines.append(f"  {item.name}")
    except PermissionError:
        tree_lines.append("  (permission denied)")

    # --- 2. Read entry-point files --------------------------------------------
    found_entry_files: list[tuple[Path, Path]] = []  # (abs_path, rel_path)
    seen_names: set[str] = set()

    # Check root first, then walk up to depth 2
    for candidate_name in _ENTRY_POINT_NAMES:
        if len(found_entry_files) >= _MAX_OVERVIEW_FILES:
            break
        # root-level
        p = root / candidate_name
        if p.exists() and p.is_file() and candidate_name not in seen_names:
            found_entry_files.append((p, p.relative_to(root)))
            seen_names.add(candidate_name)

    # Also walk one level deep for nested entry points (e.g. src/pyproject.toml)
    if len(found_entry_files) < _MAX_OVERVIEW_FILES:
        try:
            for subdir in sorted(root.iterdir()):
                if not subdir.is_dir():
                    continue
                if subdir.name in IGNORED_DIR_NAMES or subdir.name.startswith("."):
                    continue
                for candidate_name in _ENTRY_POINT_NAMES:
                    if len(found_entry_files) >= _MAX_OVERVIEW_FILES:
                        break
                    p = subdir / candidate_name
                    if p.exists() and p.is_file() and candidate_name not in seen_names:
                        found_entry_files.append((p, p.relative_to(root)))
                        seen_names.add(candidate_name)
        except PermissionError:
            pass

    entry_sections: list[str] = []
    for abs_path, rel_path in found_entry_files:
        try:
            raw = abs_path.read_text(encoding="utf-8", errors="replace")
            header = f"### {rel_path.as_posix()}"
            entry_sections.append(f"{header}\n```\n{raw }\n```")
        except Exception as e:
            entry_sections.append(f"### {rel_path.as_posix()}\n(could not read: {e})")

    parts = [
        "## Directory tree (depth ≤ 2)\n```\n" + "\n".join(tree_lines) + "\n```",
    ]
    if entry_sections:
        parts.append("## Entry-point files\n" + "\n\n".join(entry_sections))
    else:
        parts.append("No standard entry-point files found at root or one level deep.")

    return "\n\n".join(parts)


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
