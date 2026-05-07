"""Local code search tool – fast text/regex search across repos using ripgrep or Python fallback."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from langchain_core.tools import tool
from agentism.config import DEV_DIR, WORKSPACE_DIR
from tools.discovery_filters import should_ignore_relative_path


def _rg_available() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


def _search_with_rg(
    pattern: str,
    search_root: Path,
    file_glob: str,
    max_results: int,
) -> str:
    """Search using ripgrep with proper exclusion/inclusion handling."""
    # Use --exclude for directory exclusions and --glob for file type inclusions
    # This is the standard and most reliable way to combine them in ripgrep
    args = [
        "rg",
        "--heading",
        "--line-number",
        "--color=never",
        f"--max-count={max_results}",
        pattern,
        str(search_root),
    ]

    # Add directory exclusions using --exclude
    for dirname in (".git", "node_modules", ".gradle", "build", "target", ".venv", "__pycache__"):
        args.extend(["--exclude", f"{dirname}/**"])

    # Add file type inclusions using --glob
    if file_glob and file_glob != "*":
        args.extend(["--glob", file_glob])

    proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    output = proc.stdout.strip()
    if not output and proc.stderr.strip():
        return f"ripgrep error: {proc.stderr.strip()}"
    return output or f"No matches for '{pattern}' in {search_root}"


def _search_python_fallback(
    pattern: str,
    search_root: Path,
    file_glob: str,
    max_results: int,
) -> str:
    """Pure-Python regex search with proper filtering."""
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex pattern: {e}"

    matches = []
    # Determine which files to search based on file_glob
    rglob_pattern = file_glob if file_glob != "*" else "**/*"

    for filepath in sorted(search_root.rglob(rglob_pattern)):
        if not filepath.is_file():
            continue
        rel = filepath.relative_to(search_root)
        if should_ignore_relative_path(rel):
            continue
        try:
            for lineno, line in enumerate(filepath.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if compiled.search(line):
                    matches.append(f"{rel}:{lineno}: {line.strip()}")
                    if len(matches) >= max_results:
                        matches.append(f"… (stopped at {max_results} results)")
                        return "\n".join(matches)
        except Exception:
            continue

    return "\n".join(matches) if matches else f"No matches for '{pattern}' in {search_root}"


@tool
def search_local_code(
    pattern: str,
    repo_name: str = "",
    file_glob: str = "*",
    max_results: int = 50,
) -> str:
    """
    Search for a text pattern or regex across local source files.

    Uses ripgrep (rg) if available, otherwise falls back to a pure-Python search.
    Automatically skips .git, node_modules, build, and .gradle directories.

    Use this to:
    - Find all usages of a function, class, or variable name across repos
    - Locate where a specific endpoint or route is defined
    - Understand what already exists before writing new code

    Args:
        pattern:     Text or regex to search for (case-insensitive).
        repo_name:   Limit search to one repo by name (checked in DEV_DIR first).
                     Leave empty to search ALL repos under DEV_DIR.
        file_glob:   Glob pattern to filter file types (e.g. "*.groovy", "*.ts", "*.ps1").
                     Default "*" searches all files.
        max_results: Maximum number of matching lines to return (default 50).

    Returns:
        Matching lines with file paths and line numbers, or "No matches found".
    """
    if repo_name:
        p = Path(repo_name)
        if p.is_absolute():
            search_root = p
        else:
            primary = DEV_DIR / repo_name
            search_root = primary if primary.exists() else WORKSPACE_DIR / repo_name
        if not search_root.exists():
            return f"Repo not found: {search_root}"
    else:
        search_root = DEV_DIR
        if not search_root.exists():
            return f"DEV_DIR not found: {search_root}"

    if _rg_available():
        return _search_with_rg(pattern, search_root, file_glob, max_results)
    return _search_python_fallback(pattern, search_root, file_glob, max_results)