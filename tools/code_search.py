"""Local code search tool – ripgrep-backed with Python fallback."""
from __future__ import annotations

import subprocess
import re
from pathlib import Path
from langchain_core.tools import tool
from tools.discovery_filters import rg_allow_globs, rg_exclude_globs, should_ignore_relative_path
from tools.repo_paths import repo_path

_MAX_RESULTS = 50


def _keyword_from_pattern(pattern: str) -> str:
    """Extract a stable keyword from a regex/plain pattern for relevance scoring."""
    tokens = re.findall(r"[A-Za-z0-9_]{3,}", pattern)
    if not tokens:
        return pattern.strip().lower()
    return max(tokens, key=len).lower()


def _match_score(line: str, keyword: str) -> int:
    """Score `path:line:content` matches so high-signal files are ranked first."""
    try:
        path_part, _, content = line.split(":", 2)
    except ValueError:
        return 0

    path_lower = path_part.lower()
    name_lower = Path(path_part).name.lower()
    content_lower = content.lower()

    score = 0
    if keyword:
        if keyword in name_lower:
            score += 60
        if keyword in path_lower:
            score += 35
        if keyword in content_lower:
            score += 20
        if re.search(rf"\b{re.escape(keyword)}\b", content_lower):
            score += 20

    if path_lower.startswith("agentism/"):
        score += 35
    if path_lower.startswith("tools/"):
        score += 30
    if path_lower.startswith("src/"):
        score += 25
    if path_lower.startswith("tests/"):
        score += 15

    if name_lower in {"readme.md", "pyproject.toml", "package.json"}:
        score += 18

    # Prefer shallower files for initial exploration.
    score += max(0, 10 - path_lower.count("/"))
    return score


def _rerank_output(raw_output: str, pattern: str, max_results: int) -> str:
    """Rerank search output lines by relevance and cap to max_results."""
    stripped = raw_output.strip()
    if not stripped or stripped in {"No matches found", "Search timed out after 30 seconds"}:
        return raw_output

    lines = [line for line in stripped.splitlines() if line.strip()]
    keyword = _keyword_from_pattern(pattern)
    ranked = sorted(lines, key=lambda line: (-_match_score(line, keyword), line))
    return "\n".join(ranked[:max_results])


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
        output = result.stdout or "No matches found"
        return _rerank_output(output, pattern, max_results)
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
                    if len(matches) >= max_results * 2:
                        ranked = _rerank_output("\n".join(matches), pattern, max_results)
                        return ranked
        except Exception:
            continue

    if not matches:
        return "No matches found"
    return _rerank_output("\n".join(matches), pattern, max_results)


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