"""Local code search tool – ripgrep-backed with Python fallback."""
from __future__ import annotations

import subprocess
from pathlib import Path
from langchain_core.tools import tool
from tools.discovery_filters import rg_allow_globs, rg_exclude_globs, should_ignore_relative_path
from tools.repo_paths import repo_path

_MAX_RESULTS = 50


def _rg_available() -> bool:
    """Check if ripgrep is installed and usable."""
    try:
        subprocess.run(
            ["rg", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _rg_search(pattern: str, search_dir: Path, file_glob: str, max_results: int) -> str:
    """Execute ripgrep search with proper include/exclude globs."""
    args = [
        "rg",
        "--glob", file_glob,
        "--no-heading",
        "--color", "never",
        "--max-count", str(max_results),
    ]
    # Add exclude globs for directories and files to skip
    for glob in rg_exclude_globs():
        args.extend(["--glob", glob])
    # Add include globs for allowed file types
    for glob in rg_allow_globs():
        args.extend(["--glob", glob])
    args.extend([pattern, str(search_dir)])

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return result.stdout or "No matches found"
    except subprocess.TimeoutExpired:
        return "Search timed out after 30 seconds"
    except subprocess.CalledProcessError as e:
        # Exit code 1 means no matches found in ripgrep
        if e.returncode == 1:
            return "No matches found"
        return f"Search failed: {e.stderr}"
    except FileNotFoundError:
        return "ripgrep (rg) not found. Install from https://github.com/BurntSushi/ripgrep"


def _python_search(pattern: str, search_dir: Path, file_glob: str, max_results: int) -> str:
    """Fallback pure-Python search when ripgrep is unavailable."""
    import re

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(pattern), re.IGNORECASE)

    matches = []
    # Use rglob with the file_glob pattern to limit file types
    for filepath in search_dir.rglob(file_glob):
        if not filepath.is_file():
            continue
        rel = filepath.relative_to(search_dir)
        if should_ignore_relative_path(rel):
            continue
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{rel}:{line_no}:{line.strip()}")
                    if len(matches) >= max_results:
                        return "\n".join(matches)
        except Exception:
            continue

    return "\n".join(matches) if matches else "No matches found"


@tool
def search_local_code(
    pattern: str,
    repo_name: str,
    file_glob: str = "**/*",
    max_results: int = _MAX_RESULTS,
) -> str:
    """
    Search for text patterns across local source files in a repository.

    Automatically detects whether ripgrep (rg) is available and falls back
    to a pure-Python search if not. The file_glob parameter limits the
    search to matching file patterns (default: all files).

    Args:
        pattern:     Regex or plain-text pattern to search for.
        repo_name:   Short repo name (checked in DEV_DIR first) or absolute path.
        file_glob:   Glob pattern for file types to search (default: "**/*").
        max_results: Maximum number of matching lines to return.

    Returns:
        Matching lines in `file:line_number:content` format, or an error message.
    """
    search_dir = repo_path(repo_name)
    if not search_dir.exists():
        return f"Repo not found: {search_dir}. Use git_clone first."

    if _rg_available():
        return _rg_search(pattern, search_dir, file_glob, max_results)
    else:
        return _python_search(pattern, search_dir, file_glob, max_results)