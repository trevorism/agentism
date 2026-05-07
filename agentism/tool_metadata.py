"""Shared tool metadata helpers used by prompts and REPL rendering."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Callable, cast

GITHUB_PARAMETER_HINTS = {
    "search_repositories": ["query"],
    "search_code": ["query"],
    "search_issues": ["query"],
    "list_repositories": ["org", "username"],
    "get_file_contents": ["owner", "repo", "path"],
    "create_pull_request": ["owner", "repo", "title", "head", "base", "body"],
    "get_issue": ["owner", "repo", "issue_number"],
}


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str
    is_github: bool
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()


def tool_name(tool) -> str:
    return cast(str, getattr(tool, "name", tool.__class__.__name__))


def tool_description(tool) -> str:
    raw = (getattr(tool, "description", "") or "").strip()
    if not raw:
        return "No description provided."
    return raw.splitlines()[0][:120]


def is_github_tool_name(name: str) -> bool:
    return name in GITHUB_PARAMETER_HINTS or name.startswith("github_")


def _extract_param_contract(tool) -> tuple[list[str], list[str]]:
    """Extract required and optional parameter names from a tool's callable signature."""
    func = getattr(tool, "func", None)
    if func is None:
        func = getattr(tool, "_tool", None)
    if func is None:
        func = getattr(tool, "bound_method", None)

    if func is not None:
        try:
            if not callable(func):
                return [], []
            sig = inspect.signature(cast(Callable, func))
            required_params: list[str] = []
            optional_params: list[str] = []
            for name, param in sig.parameters.items():
                if name == "self":
                    continue
                if param.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
                    continue
                if param.default is inspect._empty:
                    required_params.append(name)
                else:
                    optional_params.append(name)
            return required_params, optional_params
        except (ValueError, TypeError):
            pass

    return [], []


def iter_tool_metadata(all_tools: list) -> list[ToolMetadata]:
    """Return tool metadata preserving original order and duplicates."""
    items: list[ToolMetadata] = []
    for tool in all_tools:
        name = tool_name(tool)
        required_params, optional_params = _extract_param_contract(tool)
        items.append(ToolMetadata(
            name=name,
            description=tool_description(tool),
            is_github=is_github_tool_name(name),
            required_params=tuple(required_params),
            optional_params=tuple(optional_params),
        ))
    return items


def render_tool_table_rows(all_tools: list) -> list[tuple[str, str, str]]:
    """Render numbered table rows for the `!tools` command.

    Preserves the original runtime tool order and duplicate entries while applying
    the same name/description normalization used elsewhere in the application.
    """
    return [
        (str(i), tool.name, tool.description[:100])
        for i, tool in enumerate(iter_tool_metadata(all_tools), 1)
    ]


def unique_sorted_tool_metadata(all_tools: list) -> list[ToolMetadata]:
    """Return deduplicated tool metadata sorted by name for prompt rendering."""
    seen: dict[str, ToolMetadata] = {}
    for item in iter_tool_metadata(all_tools):
        if item.name not in seen:
            seen[item.name] = item
    return [seen[name] for name in sorted(seen)]


def get_param_hints_for_tools(all_tools: list) -> dict[str, list[str]]:
    """Dynamically extract parameter hints from the actual tool definitions.

    Returns a dict mapping tool names to their parameter names, falling back to
    the static GITHUB_PARAMETER_HINTS for any tool where extraction fails.
    """
    hints: dict[str, list[str]] = {}
    for tool in all_tools:
        name = tool_name(tool)
        if name not in hints:
            required_params, optional_params = _extract_param_contract(tool)
            extracted = required_params + optional_params
            if extracted:
                hints[name] = extracted
            else:
                # Fall back to static hints
                hints[name] = GITHUB_PARAMETER_HINTS.get(name, [])
    return hints

