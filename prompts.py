"""System prompt and prompt builders for issue/PR workflows."""

from __future__ import annotations

from tool_metadata import GITHUB_PARAMETER_HINTS, unique_sorted_tool_metadata

BASE_SYSTEM_PROMPT = """You are a senior software engineer agent on a platform with: Groovy/Micronaut backend, PowerShell client, Vue frontend, Groovy/Vitest/Cucumber tests, and GitHub-hosted code.

## Repo layout
Repos are located under the configured DEV_DIR path from environment variables.
Some repos may be nested one level below DEV_DIR. Always reference repos by folder
name only (e.g. "my-repo"), never "." or relative paths.

## CRITICAL rules
- NEVER state facts from memory — always use a tool first.
- NEVER invent file contents, function names, endpoint paths, or repo names.
- NEVER assume repo structure — list files before reading/writing.
- Before calling any platform REST endpoint, verify with get_platform_api_spec.
- Report tool errors honestly; never retry silently with invented data.
- Write self-documenting code; no inline comments.

## Code change workflow
1. Identify target repo (git_clone if needed).
2. list_repo_files + read_file_in_repo to understand structure.
3. git_create_branch with descriptive name (e.g. "feature/issue-42-add-reports").
4. write_file_in_repo for changes.
5. run_tests to verify — fix failures before proceeding.
6. git_status to review, then git_commit_and_push.
7. Create PR via GitHub MCP create_pull_request against main/master with clear description referencing the issue.

NEVER push directly to main/master — always use a feature branch and PR.

## Issue-driven workflow
Given a GitHub issue URL or "owner/repo#N": use get_issue to read it, summarise the problem, then follow the code change workflow. Reference the issue number in commit message and PR description.

## PR review workflow
Given a PR: use MCP tools to read the diff, then provide (1) summary of changes, (2) feedback on correctness/best practices/missing tests/security, (3) recommendation (approve / request changes).

## General
- Reason step-by-step before calling tools.
- Output complete files — never truncate.
- Prefer Groovy idioms for backend; PowerShell best practices for scripts.
- If a tool call fails, diagnose and retry with a corrected approach.
- When in doubt, do less and confirm with the user.
"""

def build_system_prompt(all_tools: list) -> str:
    """Build a compact system prompt from static policy plus active tool metadata."""
    local_lines = []
    github_names = []

    unique_tools = unique_sorted_tool_metadata(all_tools)

    for tool in unique_tools:
        if tool.is_github:
            github_names.append(tool.name)
        else:
            local_lines.append(f"- {tool.name}: {tool.description}")

    prompt_parts = [BASE_SYSTEM_PROMPT]

    if local_lines or github_names:
        prompt_parts.append("## Available tools")
        if local_lines:
            prompt_parts.extend(local_lines)
        if github_names:
            prompt_parts.append(
                "- GitHub MCP tools available: " + ", ".join(github_names[:30])
            )
            if len(github_names) > 30:
                prompt_parts.append(
                    f"- ... plus {len(github_names) - 30} more GitHub tools."
                )

    present_github_hints = [
        f"- {name} → `{'`, `'.join(GITHUB_PARAMETER_HINTS[name])}`"
        for name in [tool.name for tool in unique_tools]
        if name in GITHUB_PARAMETER_HINTS
    ]
    if present_github_hints:
        prompt_parts.append("## GitHub MCP parameter names (exact — do not substitute)")
        prompt_parts.extend(present_github_hints)

    return "\n\n".join(part for part in prompt_parts if part)


def issue_ref_to_prompt(ref: str) -> str:
    ref = ref.strip()
    if ref.startswith("http"):
        parts = ref.rstrip("/").split("/")
        try:
            idx = parts.index("issues")
            ref = f"{parts[idx-2]}/{parts[idx-1]}#{parts[idx+1]}"
        except (ValueError, IndexError):
            pass
    return (
        f"Please read GitHub issue {ref} using the MCP get_issue tool, "
        "understand the problem fully, then implement a fix following the "
        "mandatory branch-and-PR workflow."
    )


def pr_ref_to_prompt(ref: str) -> str:
    ref = ref.strip()
    if ref.startswith("http"):
        parts = ref.rstrip("/").split("/")
        try:
            idx = parts.index("pull")
            ref = f"{parts[idx-2]}/{parts[idx-1]}#{parts[idx+1]}"
        except (ValueError, IndexError):
            pass
    return (
        f"Please review pull request {ref} using the MCP tools to read its diff. "
        "Provide: (1) a summary of changes, (2) specific feedback on correctness, "
        "best practices, and missing tests, (3) overall recommendation (approve / request changes)."
    )
