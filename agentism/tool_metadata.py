"""Shared tool metadata helpers used by prompts and REPL rendering."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

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


def tool_name(tool) -> str:
    return getattr(tool, "name", tool.__class__.__name__)


def tool_description(tool) -> str:
    raw = (getattr(tool, "description", "") or "").strip()
    if not raw:
        return "No description provided."
    return raw.splitlines()[0][:120]


def is_github_tool_name(name: str) -> bool:
    return name in GITHUB_PARAMETER_HINTS or name.startswith("github_")


def _extract_param_hints(tool) -> list[str]:
    """Extract parameter names from a tool's signature or schema."""
    # Try args_schema first (LangChain structured tools)
    schema = getattr(tool, "args_schema", None)
    if schema is not None:
        try:
            props = schema.schema().get("properties", {})
            return list(props.keys())
        except Exception:
            pass

    # Fall back to inspecting the underlying function
    func = getattr(tool, "func", None)
    if func is None:
        func = getattr(tool, "_tool", None)
    if func is None:
        func = getattr(tool, "bound_method", None)
    if func is None:
        func = getattr(tool, "func", None)

    if func is not None:
        try:
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            # Remove 'self' if present
            if params and params[0] == "self":
                params = params[1:]
            return params
        except (ValueError, TypeError):
            pass

    return []


def iter_tool_metadata(all_tools: list) -> list[ToolMetadata]:
    """Return tool metadata preserving original order and duplicates."""
    return [
        ToolMetadata(
            name=tool_name(tool),
            description=tool_description(tool),
            is_github=is_github_tool_name(tool_name(tool)),
        )
        for tool in all_tools
    ]


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
            extracted = _extract_param_hints(tool)
            if extracted:
                hints[name] = extracted
            else:
                # Fall back to static hints
                hints[name] = GITHUB_PARAMETER_HINTS.get(name, [])
    return hints

