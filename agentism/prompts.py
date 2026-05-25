"""System prompt and prompt builders for issue/PR workflows."""

from __future__ import annotations

import os
from pathlib import Path

from agentism.tool_metadata import GITHUB_PARAMETER_HINTS, unique_sorted_tool_metadata

# Knowledge files injected into the system prompt at startup.
_KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def load_knowledge(include_files: set[str] | None = None) -> str:
    """Load markdown files from agentism/knowledge/ sorted alphabetically.

    Returns the combined content as a single string with section headers,
    or an empty string if the directory does not exist or is empty.
    """
    if not _KNOWLEDGE_DIR.is_dir():
        return ""

    include_lookup = {name.lower() for name in include_files} if include_files else None

    files = sorted(_KNOWLEDGE_DIR.glob("*.md"))
    sections: list[str] = []
    for f in files:
        if include_lookup is not None:
            stem = f.stem.lower()
            name = f.name.lower()
            if stem not in include_lookup and name not in include_lookup:
                continue
        try:
            content = f.read_text(encoding="utf-8").strip()
            if content:
                sections.append(content)
        except OSError:
            pass
    return "\n\n---\n\n".join(sections)


def _knowledge_files_from_env() -> set[str] | None:
    """Return optional knowledge file allowlist from AGENT_KNOWLEDGE_FILES.

    Accepts comma-separated file stems or names, for example:
    - platform-overview,pr-conventions
    - platform-overview.md,pr-conventions.md
    """
    raw = os.getenv("AGENT_KNOWLEDGE_FILES", "").strip()
    if not raw:
        return None
    items = {part.strip() for part in raw.split(",") if part.strip()}
    return items or None

BASE_SYSTEM_PROMPT = """You are a senior software engineer agent. Rules in the Platform knowledge section are binding.

## Repo layout
Repos are located under the configured DEV_DIR path from environment variables.
Some repos may be nested one level below DEV_DIR. Always reference repos by folder
name only (e.g. "my-repo"), never "." or relative paths.

## Intent handling
- Classify each request before acting.
- If the user asks for explanation, summary, analysis, review, or discovery only: run in read-only mode and answer directly from tool output.
- In read-only mode, NEVER call mutating tools (`create_file`, `write_file_in_repo`, `git_create_branch`, `git_commit_and_push`, `create_pull_request`, merge tools, or platform mutation endpoints).
- Only enter implementation mode when the user explicitly asks to change code, create commits, open PRs, or implement/fix something.

## CRITICAL rules
- NEVER state facts from memory — always use a tool first.
- NEVER invent file contents, function names, endpoint paths, or repo names.
- NEVER invent tool names or parameters; use exact names from the Available tools section (for example, `list_repo_files`, not `list_files_in_repo`).
- For every local tool call, supply every required parameter exactly as listed; do not guess missing kwargs or rename fields.
- Do not mix GitHub MCP parameter names with local tool parameter names. Example: `list_repo_files` uses `repo_name` (not `repo` or `path`). `read_file_in_repo` uses `repo_name` and `relative_path` (not `owner`/`repo`/`path`). `search_local_code` requires `repo_name`.
- **GitHub MCP tools ALWAYS require `owner` and `repo` (or equivalent)** — do not call `create_pull_request`, `merge_pull_request`, or similar without specifying the GitHub owner and repository.
- NEVER assume repo structure — use read_repo_overview before reading/writing files.
- NEVER narrate intended repo reads or tool use as a question or status update; call the next tool immediately.
- Prefer `run_in_terminal` over `run_powershell` for consistency (they are aliases).
- For platform CRUD operations, follow the Platform knowledge decision rules: prefer PowerShell CLI cmdlets when available; otherwise use platform web/API tools with the documented auth/spec flow.
- Report tool errors honestly; never retry silently with invented data.
- Write self-documenting code; no inline comments.

## Code change workflow
Apply this workflow only in implementation mode.
1. Identify target repo (git_clone if needed).
2. Immediately call read_repo_overview — do NOT list all files recursively first, do NOT ask the user for permission, do NOT announce intent without acting.
3. Identify relevant files, then immediately chain read_file_in_repo calls.
4. Implement and verify: git_create_branch, write_file_in_repo, run_tests, git_status, git_commit_and_push, create_pull_request (follow Platform knowledge conventions).
5. If tests fail, iterate: inspect failure output, patch only relevant files, and rerun the narrowest failing suite before broad suites.
6. Before final response, run a self-critique pass: check correctness, missing tests, branch safety, and whether verification evidence is explicit.

In implementation mode, NEVER push directly to master — always use a feature branch and PR.
NEVER prompt the user before exploring the repo — use read_repo_overview then read relevant files autonomously.
Immediately call read_repo_overview and immediately chain read_file_in_repo calls; do NOT ask the user for permission.
NEVER stop after saying "I will inspect/read/look at ..." — perform the repo read or tool call in the same turn.

## Issue-driven workflow
Given a GitHub issue URL or "owner/repo#N": use get_issue to read it, summarise the problem, immediately inspect the target repo with read_repo_overview, then read the relevant implementation and test files with read_file_in_repo without asking the user first. Reference the issue number in commit message and PR description.

## PR review workflow
Given a PR: use MCP tools to read the diff, then provide (1) summary of changes, (2) feedback on correctness, idiom compliance, missing tests, and security, (3) recommendation (approve / request changes).

## General
- Reason step-by-step before calling tools.
- Use model routing when available: planner model for review/analysis, executor model for implementation, critic model for final quality pass.
- Output complete files — never truncate.
- If a tool call fails, diagnose and retry with a corrected approach.
- If a tool call fails with `ToolInvocationError` due to missing/invalid kwargs, immediately retry the same tool with the exact required parameter names from the local/GitHub parameter sections.
- If a tool call fails with "not a valid tool", choose the closest exact tool name from the Available tools list and continue without asking the user.
- If a GitHub MCP tool returns "Not Found" or "Resource not found": the issue/PR/repo does not exist or is inaccessible. Do NOT retry the same call. Instead: (1) report clearly to the user which resource was not found, (2) suggest they verify the owner/repo/number is correct, (3) offer to search using search_repositories or search_issues if the ref might be wrong.
- NEVER respond to a Not Found error with "Please fix your mistakes" — that is unhelpful. Always diagnose and report specifically what was not found.
- When in doubt about repo exploration or tool chaining, continue autonomously; only ask the user if blocked by missing credentials, missing permissions, or contradictory requirements.
"""

PLANNING_PAUSE_INSTRUCTIONS = """## Plan confirmation workflow (implementation tasks only)
When the user requests implementation/code changes (using keywords like "implement", "fix", "refactor", "add", "create", "update", "write", "patch", "bug"):

1. **Design Phase**: Understand the requirement. Immediately inspect the target repo with read_repo_overview and read relevant files autonomously without asking permission.

2. **Plan Summarization**: After inspection, output a clear, structured plan including:
   - Summary of the problem/requirement
   - High-level approach (architecture/algorithm)
   - Files that will be created/modified
   - Testing strategy
   - Expected outcome

3. **WAIT FOR CONFIRMATION**: After outputting the plan, STOP and wait for the user to confirm, ask clarifying questions, or request changes. Do NOT proceed to implementation until you receive explicit approval or feedback.

4. **Clarifying Questions (Optional)**: If anything is ambiguous, ask the user:
   - Are there edge cases I should handle?
   - Any preference on implementation style or libraries?
   - Testing coverage expectations?
   - Performance or security constraints?

5. **Implementation Phase (after user confirms)**: Only after receiving confirmation, proceed with:
   - git_create_branch, write_file_in_repo, run_tests, git_commit_and_push, create_pull_request
   - Follow the Code change workflow section above exactly.

This ensures the user has visibility and control over engineering decisions before code is written."""

AUTO_MODE_INSTRUCTIONS = """## Autonomous execution mode
Auto mode is enabled for this conversation.

- Do NOT stop after a plan, outline, checklist, or "Execution Plan" section.
- Do NOT ask the user to confirm, approve, or tell you to continue.
- After planning, immediately continue with tool calls and execution in the same turn.
- Only return a user-facing response when you have a concrete result: completed analysis, implemented changes, verification evidence, created PR/branch details, or a real blocking issue.
- If you are blocked, state the exact blocker (for example: missing credentials, missing permissions, inaccessible repo, or nonexistent resource) and stop.
- If you catch yourself writing "I will..." or listing future steps, continue working instead of sending that interim update.
"""

def build_system_prompt(all_tools: list, knowledge_files: set[str] | None = None, auto_mode: bool = False) -> str:
    """Build a compact system prompt from static policy plus active tool metadata.

    If auto_mode=False (default), includes plan confirmation workflow instructions.
    If auto_mode=True, skips confirmation prompts for full autonomous execution.
    """
    local_lines = []
    github_names = []

    unique_tools = unique_sorted_tool_metadata(all_tools)

    # High-risk tools requiring explicit parameter hints (to reduce parameter errors).
    HIGH_RISK_TOOLS = {
        "create_file", "write_file_in_repo", "read_file_in_repo", "list_repo_files",
        "run_in_terminal", "git_create_branch", "git_commit_and_push", "search_local_code",
    }

    for tool in unique_tools:
        if tool.is_github:
            github_names.append(tool.name)
        else:
            local_lines.append(f"- {tool.name}: {tool.description}")

    prompt_parts = [BASE_SYSTEM_PROMPT]

    # Include plan confirmation workflow only when not in auto mode
    if not auto_mode:
        prompt_parts.append(PLANNING_PAUSE_INSTRUCTIONS)
    else:
        prompt_parts.append(AUTO_MODE_INSTRUCTIONS)

    selected_knowledge = knowledge_files or _knowledge_files_from_env()
    knowledge = load_knowledge(selected_knowledge)
    if knowledge:
        prompt_parts.append("## Platform knowledge\n\n" + knowledge)

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

    local_param_hints = [
        f"- {tool.name} → required: `{'`, `'.join(tool.required_params)}`"
        + (
            f"; optional: `{'`, `'.join(tool.optional_params)}`"
            if tool.optional_params else ""
        )
        for tool in unique_tools
        if not tool.is_github and tool.name in HIGH_RISK_TOOLS and tool.required_params
    ]
    if local_param_hints:
        prompt_parts.append("## Local tool parameter names (exact — include all required kwargs)")
        prompt_parts.extend(local_param_hints)

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
        "understand the problem fully, then immediately inspect the repo with "
        "read_repo_overview and chain any necessary read_file_in_repo calls "
        "(and use exact tool names from the Available tools list, e.g. list_repo_files) "
        "without asking for permission before implementing a fix following the "
        "mandatory branch-and-PR workflow. "
        "If get_issue returns Not Found, report which resource was not found and "
        "use search_issues or search_repositories to find the correct ref before stopping."
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
        f"Please review GitHub PR {ref} using the MCP tools, "
        "provide a structured review, and recommend approve or request changes."
    )
