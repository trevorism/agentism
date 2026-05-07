"""Shared filters for repo discovery and code search."""
from __future__ import annotations

from pathlib import Path

# Directories that are usually irrelevant for source discovery.
IGNORED_DIR_NAMES = {
    ".git",
    ".idea",
    "__pycache__",
    ".venv",
    "node_modules",
    ".gradle",
    "build",
    "dist",
    "target",
    ".pytest_cache",
    ".mypy_cache",
}

# Lock and generated metadata files that add noise.
IGNORED_FILE_NAMES = {
    "uv.lock",
    "package-lock.json",
}

_IGNORED_DIR_NAMES_LOWER = {name.lower() for name in IGNORED_DIR_NAMES}
_IGNORED_FILE_NAMES_LOWER = {name.lower() for name in IGNORED_FILE_NAMES}

# Language-focused keep-list (in priority order): groovy, gradle, node, c#, python.
ALLOWED_EXTENSIONS = {
    # Groovy/Gradle
    ".groovy",
    ".gradle",
    ".java",
    # Node/TypeScript
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    # C#
    ".cs",
    ".csproj",
    ".sln",
    ".props",
    ".targets",
    # Python
    ".py",
    ".pyi",
    # Shared config/docs for build and discovery context
    ".toml",
    ".yaml",
    ".yml",
    ".xml",
    ".properties",
    ".md",
}

_ALLOWED_EXTENSIONS_LOWER = {ext.lower() for ext in ALLOWED_EXTENSIONS}

# Generated bundles and sourcemaps are typically too noisy for discovery.
IGNORED_FILE_SUFFIXES = {
    ".min.js",
    ".min.css",
    ".map",
}

# Binary/non-source artifacts.
IGNORED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".jar",
    ".class",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
}

def should_ignore_relative_path(relative_path: Path) -> bool:
    """Return True when a repo-relative path should be excluded from discovery/search."""
    name = relative_path.name
    lower_name = name.lower()
    lower_path = Path(*[p.lower() for p in relative_path.parts])

    if any(part in _IGNORED_DIR_NAMES_LOWER for part in lower_path.parts[:-1]):
        return True

    if lower_name in _IGNORED_FILE_NAMES_LOWER:
        return True

    if any(lower_name.endswith(suffix) for suffix in IGNORED_FILE_SUFFIXES):
        return True

    if Path(lower_name).suffix in IGNORED_EXTENSIONS:
        return True

    # Keep only files relevant to supported languages and config extensions.
    if Path(lower_name).suffix in _ALLOWED_EXTENSIONS_LOWER:
        return False

    return True

def rg_exclude_globs() -> list[str]:
    """Build ripgrep glob exclusions matching the shared ignore policy."""
    globs: list[str] = []

    for dirname in sorted(IGNORED_DIR_NAMES):
        globs.append(f"!{dirname}/**")

    for filename in sorted(IGNORED_FILE_NAMES):
        globs.append(f"!**/{filename}")

    for suffix in sorted(IGNORED_FILE_SUFFIXES):
        globs.append(f"!**/*{suffix}")

    for ext in sorted(IGNORED_EXTENSIONS):
        globs.append(f"!**/*{ext}")

    return globs


def rg_allow_globs() -> list[str]:
    """Build ripgrep include globs for supported source/config files."""
    globs: list[str] = []
    for ext in sorted(ALLOWED_EXTENSIONS):
        globs.append(f"**/*{ext}")
    return globs


