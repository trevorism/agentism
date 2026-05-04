"""Local code search tool – fast text/regex search across repos using ripgrep or Python fallback."""
import subprocess
import re
from pathlib import Path
from langchain_core.tools import tool
from config import DEV_DIR


def _rg_available() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


def _search_with_rg(pattern: str, search_root: Path, file_glob: str, max_results: int) -> str:
    args = [
        "rg",
        "--heading",
        "--line-number",
        "--color=never",
        f"--max-count={max_results}",
        "--glob", file_glob,
        pattern,
        str(search_root),
    ]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    output = proc.stdout.strip()
    if not output and proc.stderr.strip():
        return f"ripgrep error: {proc.stderr.strip()}"
    return output or f"No matches for '{pattern}' in {search_root}"


def _search_python_fallback(pattern: str, search_root: Path, file_glob: str, max_results: int) -> str:
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex pattern: {e}"

    matches = []
    for filepath in sorted(search_root.rglob(file_glob)):
        if not filepath.is_file():
            continue
        # Skip common noise directories
        parts = set(filepath.parts)
        if parts & {".git", "node_modules", ".gradle", "build", "__pycache__", ".venv"}:
            continue
        try:
            for lineno, line in enumerate(filepath.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if compiled.search(line):
                    rel = filepath.relative_to(search_root)
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
        from config import WORKSPACE_DIR
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

