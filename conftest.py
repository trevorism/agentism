"""Global pytest bootstrap to make unit tests independent from local .env."""

from __future__ import annotations

import os


def _ensure_non_empty(name: str, default: str) -> None:
    if not os.getenv(name):
        os.environ[name] = default


# Set harmless defaults before any test module imports config.py.
_ensure_non_empty("OLLAMA_MODEL", "test-model")
_ensure_non_empty("GITHUB_TOKEN", "test-token")
_ensure_non_empty("PS_MODULE_PATH", ".")
_ensure_non_empty("DEV_DIR", ".")

