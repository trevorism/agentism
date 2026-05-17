"""Central configuration loaded from .env."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    """Return the env var value, or exit with a clear error message."""
    value = os.getenv(name, "")
    if not value:
        print(
            f"Error: Required environment variable '{name}' is not set.\n"
            f"  Copy .env.example to .env and fill in your values:\n"
            f"    cp .env.example .env\n"
            f"  Then edit .env and set {name}.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def _optional(name: str, default: str = "") -> str:
    """Return the env var value, or the default if not set."""
    return os.getenv(name, default)


def _optional_float(name: str, default: float | None = None) -> float | None:
    """Return an optional float env var; empty values resolve to default."""
    raw = os.getenv(name, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        if default is not None:
            return default
        raise


def _optional_int(name: str, default: int) -> int:
    """Return an integer env var, or the default when missing/invalid."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _path(name: str, default: str) -> Path:
    """Return a Path from the env var, or the default if not set."""
    value = os.getenv(name, default)
    return Path(value)


# -- Ollama (required) --
OLLAMA_BASE_URL: str = _optional("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = _required("OLLAMA_MODEL")
_DEFAULT_TEMPERATURE = 0.7
_DEFAULT_TOP_P = 0.95

OLLAMA_TEMPERATURE: float = _optional_float("OLLAMA_TEMPERATURE", _DEFAULT_TEMPERATURE) or _DEFAULT_TEMPERATURE
OLLAMA_TOP_P: float | None = _optional_float("OLLAMA_TOP_P", _DEFAULT_TOP_P)

# -- GitHub (required for MCP tools) --
GITHUB_TOKEN: str = _required("GITHUB_TOKEN")
GITHUB_DEFAULT_OWNER: str = _optional("GITHUB_DEFAULT_OWNER", "")

# -- Platform (optional) --
PLATFORM_BASE_URL: str = _optional("PLATFORM_BASE_URL", "")
TREVORISM_TENANT_GUID: str = _optional("TREVORISM_TENANT_GUID", "")
TREVORISM_USERNAME: str = _optional("TREVORISM_USERNAME", "")
TREVORISM_PASSWORD: str = _optional("TREVORISM_PASSWORD", "")

# -- Machine-specific paths (required) --
PS_MODULE_PATH: str = _required("PS_MODULE_PATH")
DEV_DIR: Path = _path("DEV_DIR", "")

MEMORY_DB: str = _optional("MEMORY_DB", "memory.db")
OLLAMA_EMBED_MODEL: str = _optional("OLLAMA_EMBED_MODEL", "nomic-embed-text")
MEMORY_RETRIEVAL_LIMIT: int = _optional_int("MEMORY_RETRIEVAL_LIMIT", 8)
MEMORY_CONTEXT_CHAR_BUDGET: int = _optional_int("MEMORY_CONTEXT_CHAR_BUDGET", 2400)
MEMORY_CHUNK_CHARS: int = _optional_int("MEMORY_CHUNK_CHARS", 600)
MEMORY_CHUNK_OVERLAP: int = _optional_int("MEMORY_CHUNK_OVERLAP", 120)
WORKSPACE_DIR: Path = _path("WORKSPACE_DIR", "./repos")
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


