"""Pytest bootstrap for CI-safe defaults and test isolation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _ensure_non_empty(name: str, default: str) -> None:
    if not os.getenv(name):
        os.environ[name] = default


_TEST_ROOT = Path(__file__).resolve().parent.parent / ".test_sandbox"
_HOME_DIR = _TEST_ROOT / "home"
_TMP_DIR = _TEST_ROOT / "tmp"
_WORKSPACE_DIR = _TEST_ROOT / "repos"
_PYTEST_TMP = Path(__file__).resolve().parent.parent / ".pytest_tmp"


def _set_test_path_env() -> None:
    _HOME_DIR.mkdir(parents=True, exist_ok=True)
    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # Keep all writes during tests inside the repository sandbox.
    os.environ["HOME"] = str(_HOME_DIR)
    os.environ["USERPROFILE"] = str(_HOME_DIR)
    os.environ["APPDATA"] = str(_HOME_DIR / "AppData")
    os.environ["LOCALAPPDATA"] = str(_HOME_DIR / "LocalAppData")
    os.environ["TMP"] = str(_TMP_DIR)
    os.environ["TEMP"] = str(_TMP_DIR)
    os.environ["TMPDIR"] = str(_TMP_DIR)
    os.environ["DEV_DIR"] = str(_TEST_ROOT)
    os.environ["WORKSPACE_DIR"] = str(_WORKSPACE_DIR)
    os.environ["MEMORY_DB"] = str(_TEST_ROOT / "memory.db")


# Establish sandbox paths before any app modules import config.py.
_set_test_path_env()

# Provide harmless defaults so importing config.py never exits in CI.
# Real integration tests can still override these via local .env.
_ensure_non_empty("OLLAMA_MODEL", "test-model")
_ensure_non_empty("GITHUB_TOKEN", "test-token")
_ensure_non_empty("PS_MODULE_PATH", ".")


def pytest_sessionfinish(session, exitstatus):
    """Remove test sandbox artifacts so each run is self-contained."""
    if _TEST_ROOT.exists():
        shutil.rmtree(_TEST_ROOT, ignore_errors=True)
    if _PYTEST_TMP.exists():
        shutil.rmtree(_PYTEST_TMP, ignore_errors=True)
