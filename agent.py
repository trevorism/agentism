"""
Agentism – local LangChain/LangGraph ReAct agent
Model  : llama3.2 via Ollama  (configurable via OLLAMA_MODEL)
Memory : SQLite file-backed checkpointer  (memory.db)
GitHub : GitHub MCP server  (requires Node.js + GITHUB_TOKEN)
Tools  : PowerShell · Git · HTTP · GitHub MCP
"""
import argparse
import asyncio
from contextlib import AsyncExitStack

from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_mcp_adapters.client import MultiServerMCPClient
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

import config
from tools import LOCAL_TOOLS

console = Console()

SYSTEM_PROMPT = """You are a senior software engineer agent working on a platform that has:
- Groovy-based micronaut backend services
- A PowerShell client for interacting with the platform
- A Vue frontend
- Groovy unit tests
- vitest js tests
- Cucumber acceptance tests
- Code hosted on GitHub under your organisation

You have the following capabilities:
1. run_powershell        – execute pwsh scripts/commands locally (custom modules auto-available)
2. list_available_modules – discover importable PowerShell modules
3. fetch_url             – HTTP GET any URL (docs, APIs, changelogs)
4. post_platform_api     – POST JSON to the Groovy platform REST API
5. git_clone             – ensure a repo is available locally (checks DEV_DIR first)
6. git_create_branch     – create and checkout a feature branch
7. write_file_in_repo    – write source files into a local repo
8. git_status            – inspect staged/unstaged/untracked changes
9. git_commit_and_push   – commit and push to the current feature branch
10. GitHub MCP tools     – read issues, search code, manage PRs, read/write repo files

## Anti-hallucination rules (CRITICAL – follow these absolutely)
- NEVER state facts about the codebase, repos, files, APIs, or platform state from memory.
  Always use a tool to look it up first.
- NEVER invent file contents, function names, endpoint paths, module names, or repo names.
  If you don't know, say "I need to check" and use the appropriate tool.
- NEVER assume a repository structure. Use git_clone + run_powershell or GitHub MCP to
  read actual directory listings and file contents before writing code.
- If a tool call returns an error or unexpected result, report it honestly.
  Do NOT retry silently with invented data.
- If you cannot complete a task with the tools available, say so clearly.
  Do not make up a plausible-sounding answer.

## Mandatory workflow for code changes
1. Identify the target repo, if it is not on the machine use git clone, otherwise reference it.
2. Call git_create_branch with a descriptive name (e.g. "feature/issue-42-add-reports").
3. Write or edit files with write_file_in_repo.
4. Call git_status to verify changes, then git_commit_and_push.
5. Use the GitHub MCP create_pull_request tool to open a PR against main/master.
   Include a clear PR description referencing the issue number if one exists.

NEVER push directly to main, or master. Always use a feature branch and PR.

## Issue-driven workflow
When given a GitHub issue URL or "owner/repo#N" reference:
1. Use the GitHub MCP get_issue tool to read the full issue body and comments.
2. Summarise your understanding of the problem before acting.
3. Follow the code-change workflow above to implement a fix or feature.
4. Reference the issue number in both the commit message and the PR description.

## General guidelines
- Reason step-by-step before calling tools.
- When writing code, output the complete file – never truncate.
- Prefer Groovy idioms for backend code; follow PowerShell best practices for scripts.
- If a tool call fails, diagnose the error and retry with a corrected approach.
- When in doubt, do less and confirm with the user rather than proceeding on assumptions.
"""


def build_llm() -> ChatOllama:
    return ChatOllama(
        model=config.OLLAMA_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=0,
    )


def print_welcome() -> None:
    console.print(Panel(
        f"[bold cyan]Agentism[/bold cyan]  🤖\n"
        f"Model : [green]{config.OLLAMA_MODEL}[/green] @ {config.OLLAMA_BASE_URL}\n"
        f"Memory: [green]{config.MEMORY_DB}[/green] (SQLite)\n"
        f"GitHub: MCP  |  Workspace: [green]{config.WORKSPACE_DIR}[/green]\n\n"
        f"Type your task and press Enter. Type [bold]exit[/bold] or [bold]quit[/bold] to stop.",
        title="Platform Dev Agent",
        border_style="cyan",
    ))


async def run_agent_turn(agent, user_input: str, thread_id: str) -> str:
    """
    Run one turn of the agent, streaming and printing every tool call and
    result live so the user can watch the chain of reasoning in real time.
    Returns the final text response.
    """
    config_dict = {"configurable": {"thread_id": thread_id}}
    messages = {"messages": [{"role": "user", "content": user_input}]}

    final_text = ""
    async for chunk in agent.astream(messages, config=config_dict):

        # ── Tool calls the model decided to make ──────────────────────────
        if "agent" in chunk:
            for msg in chunk["agent"].get("messages", []):
                # Intermediate tool-call decisions
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        args_preview = str(tc.get("args", {}))
                        if len(args_preview) > 200:
                            args_preview = args_preview[:200] + "…"
                        console.print(
                            f"  [bold blue]⚙ Tool call:[/bold blue] "
                            f"[cyan]{tc['name']}[/cyan]  {args_preview}"
                        )
                # Final text response
                if hasattr(msg, "content") and msg.content:
                    final_text = msg.content

        # ── Tool results coming back ──────────────────────────────────────
        if "tools" in chunk:
            for msg in chunk["tools"].get("messages", []):
                if hasattr(msg, "content") and msg.content:
                    result_preview = str(msg.content)
                    if len(result_preview) > 300:
                        result_preview = result_preview[:300] + "…"
                    console.print(
                        f"  [bold yellow]↩ Result:[/bold yellow] "
                        f"[dim]{result_preview}[/dim]"
                    )

    return final_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agentism – platform dev agent")
    parser.add_argument(
        "--issue",
        metavar="REF",
        help=(
            "Kick off the agent with a GitHub issue. "
            "Accepts a full URL (https://github.com/owner/repo/issues/42) "
            "or short form owner/repo#42."
        ),
    )
    return parser.parse_args()


def _issue_prompt(ref: str) -> str:
    """Turn a --issue argument into an opening user message."""
    ref = ref.strip()
    if ref.startswith("http"):
        # https://github.com/owner/repo/issues/42  →  owner/repo#42
        parts = ref.rstrip("/").split("/")
        try:
            idx = parts.index("issues")
            short = f"{parts[idx-2]}/{parts[idx-1]}#{parts[idx+1]}"
        except (ValueError, IndexError):
            short = ref
    else:
        short = ref  # already short form or unknown – pass through
    return (
        f"Please read GitHub issue {short} using the get_issue MCP tool, "
        "understand the problem fully, then implement a fix following the "
        "mandatory branch-and-PR workflow."
    )


async def main_async(initial_prompt: str = "") -> None:
    print_welcome()

    stack = AsyncExitStack()

    # ── MCP GitHub client ──────────────────────────────────────────────────────
    mcp_tools = []
    if config.GITHUB_TOKEN:
        try:
            mcp_client = await stack.enter_async_context(
                MultiServerMCPClient({
                    "github": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": config.GITHUB_TOKEN},
                        "transport": "stdio",
                    }
                })
            )
            mcp_tools = mcp_client.get_tools()
            console.print(f"[green]✓[/green] GitHub MCP: {len(mcp_tools)} tools loaded.")
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow]  GitHub MCP unavailable (is Node.js installed?): {e}")
    else:
        console.print("[yellow]⚠[/yellow]  GITHUB_TOKEN not set – MCP GitHub tools disabled.")

    all_tools = LOCAL_TOOLS + mcp_tools

    # ── SQLite file-backed memory ─────────────────────────────────────────────
    async with AsyncSqliteSaver.from_conn_string(config.MEMORY_DB) as checkpointer:
        llm = build_llm()

        agent = create_react_agent(
            llm,
            tools=all_tools,
            prompt=SYSTEM_PROMPT,
            checkpointer=checkpointer,
        )

        console.print(f"[green]✓[/green] {len(all_tools)} tools active.\n")

        # ── REPL ──────────────────────────────────────────────────────────────
        thread_id = "main"  # single persistent conversation thread

        # If launched with --issue, inject the first message automatically
        if initial_prompt:
            console.print(f"[dim]Auto-prompt:[/dim] {initial_prompt}\n")
            console.print("[cyan]Agent working…[/cyan]")
            try:
                response = await run_agent_turn(agent, initial_prompt, thread_id)
            except Exception as e:
                response = f"[Agent error] {e}"
            console.print(Panel(
                Markdown(response) if response else "[dim](no response)[/dim]",
                title="[bold green]Agent[/bold green]",
                border_style="green",
            ))
            console.print()

        while True:
            try:
                user_input = Prompt.ask("[bold cyan]You[/bold cyan]").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]")
                break

            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", "q"}:
                console.print("[dim]Goodbye.[/dim]")
                break

            console.print()
            console.print("[cyan]Agent working…[/cyan]")
            try:
                response = await run_agent_turn(agent, user_input, thread_id)
            except Exception as e:
                response = f"[Agent error] {e}"

            console.print(Panel(
                Markdown(response) if response else "[dim](no response)[/dim]",
                title="[bold green]Agent[/bold green]",
                border_style="green",
            ))
            console.print()

    await stack.aclose()


def main() -> None:
    args = parse_args()
    initial = _issue_prompt(args.issue) if args.issue else ""
    asyncio.run(main_async(initial))


if __name__ == "__main__":
    main()

