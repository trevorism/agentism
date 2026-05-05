"""Pytest bootstrap for CI-safe defaults and test selection."""

from __future__ import annotations

import os


def _ensure_non_empty(name: str, default: str) -> None:
    if not os.getenv(name):
        os.environ[name] = default


# Provide harmless defaults so importing config.py never exits in CI.
# Real integration tests can still override these via local .env.
_ensure_non_empty("OLLAMA_MODEL", "test-model")
_ensure_non_empty("GITHUB_TOKEN", "test-token")
_ensure_non_empty("PS_MODULE_PATH", ".")
_ensure_non_empty("DEV_DIR", ".")
