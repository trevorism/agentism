"""Tools package – all custom LangChain tools live here."""
from __future__ import annotations

import importlib
from typing import Any

from rich.console import Console

console = Console()

_LOADED_TOOLS: list[Any] = []


def _load_tool_module(module_name: str, attr_name: str) -> Any:
    """Import a single tool attribute with a helpful error message on failure."""
    try:
        mod = importlib.import_module(f"tools.{module_name}")
        return getattr(mod, attr_name)
    except Exception as e:
        console.print(
            f"[red]✗ Failed to load tool from tools/{module_name}.py:[/red] {e}\n"
            f"  Check that the file has valid syntax and exports '{attr_name}'."
        )
        raise


# Load each tool module individually so failures are isolated and reported clearly.
try:
    _LOADED_TOOLS.extend([
        _load_tool_module("shell", "run_powershell"),
        _load_tool_module("shell", "run_in_terminal"),
        _load_tool_module("shell", "list_available_modules"),
        _load_tool_module("web_tool", "get_platform_token"),
        _load_tool_module("web_tool", "fetch_url"),
        _load_tool_module("web_tool", "post_platform_api"),
        _load_tool_module("web_tool", "get_platform_api_spec"),
        _load_tool_module("file_tool", "read_repo_overview"),
        _load_tool_module("file_tool", "read_file_in_repo"),
        _load_tool_module("file_tool", "list_repo_files"),
        _load_tool_module("file_tool", "create_file"),
        _load_tool_module("file_tool", "write_file_in_repo"),
        _load_tool_module("git_tool", "git_clone"),
        _load_tool_module("git_tool", "git_create_branch"),
        _load_tool_module("git_tool", "git_status"),
        _load_tool_module("git_tool", "git_commit_and_push"),
        _load_tool_module("git_tool", "git_sync_master"),
        _load_tool_module("test_runner", "run_tests"),
        _load_tool_module("code_search", "search_local_code"),
    ])
except Exception as e:
    console.print(f"[red]Fatal: Could not load tools.[/red] {e}")
    raise RuntimeError("Could not load tools") from e

LOCAL_TOOLS: list[Any] = _LOADED_TOOLS

__all__ = ["LOCAL_TOOLS"]
