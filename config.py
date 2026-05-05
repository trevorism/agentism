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


def _path(name: str, default: str) -> Path:
    """Return a Path from the env var, or the default if not set."""
    value = os.getenv(name, default)
    return Path(value)


# -- Ollama (required) --
OLLAMA_BASE_URL: str = _optional("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = _required("OLLAMA_MODEL")

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
WORKSPACE_DIR: Path = _path("WORKSPACE_DIR", "./repos")
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# -- Dry run --
DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() == "true"
