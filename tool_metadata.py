"""Shared tool metadata helpers used by prompts and REPL rendering."""

from __future__ import annotations

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

