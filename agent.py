"""
Agentism – local LangChain/LangGraph ReAct agent
Model  : configurable via OLLAMA_MODEL env var
Memory : SQLite file-backed checkpointer  (memory.db)
GitHub : GitHub MCP server  (requires Node.js + GITHUB_TOKEN)
Tools  : PowerShell · Git · HTTP · GitHub MCP

CLI flags:
  --session <name>        start in / resume a named conversation thread
  --issue <ref>           auto-kick off with a GitHub issue (owner/repo#N or URL)
  --issues <owner/repo>   batch-process all open issues matching --label
  --label <label>         issue label filter for --issues  (default: agent-ready)
  --dry-run               preview writes/commits without making real changes

REPL commands (prefix with !):
  !help                   show this command list
  !tools                  list all active tools with descriptions
  !history [N]            print last N turns this session (default 10)
  !thread <name>          switch to a named conversation thread
  !threads                list all saved conversation threads
  !clear                  delete history for the current thread
  !model <name>           hot-swap the Ollama model without restarting
  !issue <ref>            load a GitHub issue mid-session
  !review <PR-URL>        review a pull request diff and post feedback
  !cost                   show token usage for this session
  !retry                  re-run the last user message
  !exit / !quit           exit the agent
"""
import argparse
import asyncio
import re
import textwrap
import warnings
from dataclasses import dataclass, field

import aiosqlite
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent, ToolNode
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_mcp_adapters.client import MultiServerMCPClient
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

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
1.  run_powershell         - execute pwsh scripts/commands locally (custom modules auto-available)
2.  list_available_modules - discover importable PowerShell modules
3.  fetch_url              - HTTP GET any URL (docs, APIs, changelogs)
4.  post_platform_api      - POST JSON to the Groovy platform REST API
5.  get_platform_api_spec  - fetch and cache the OpenAPI spec for any platform service
6.  git_clone              - ensure a repo is available locally (checks DEV_DIR first)
7.  git_create_branch      - create and checkout a feature branch
8.  list_repo_files        - list files in a repo directory (use before writing to understand structure)
9.  read_file_in_repo      - read the contents of an existing file in a local repo
10. write_file_in_repo     - write source files into a local repo
11. git_status             - inspect staged/unstaged/untracked changes
12. git_commit_and_push    - commit and push to the current feature branch
13. run_tests              - run Groovy/Gradle, Vitest, or Cucumber tests in a repo
14. search_local_code      - fast regex/text search across all local repos
15. GitHub MCP tools       - read issues, search code, manage PRs, read/write repo files

Of course, you can also helpfully and concisely answer questions in addition to developing software.

## Repository layout
All repositories are checked out under C:/dev:
- Most repos live at C:/dev/<repo-name>   (e.g. C:/dev/platform-api)
- This agent's own repo lives at C:/dev/ai/agentism

When referencing a repo, always use the repository folder name only (e.g. "agentism",
"platform-api") — never use "." or a relative path. The tools will locate it automatically.

## CRITICAL - follow these absolutely when developing software
- NEVER state facts about the codebase, repos, files, APIs, or platform state from memory.
  Always use a tool to look it up first.
- NEVER invent file contents, function names, endpoint paths, module names, or repo names.
  If you don't know, say "I need to check" and use the appropriate tool.
- NEVER assume a repository structure. Use list_repo_files and read_file_in_repo first.
- Before calling any platform REST endpoint, call get_platform_api_spec to verify the
  exact path, method, and parameters. Never guess endpoint signatures.
- If a tool call returns an error or unexpected result, report it honestly.
  Do NOT retry silently with invented data.
- If you cannot complete a task with the tools available, say so clearly.
- This software developer writes self-documenting code instead of inline comments.

## Mandatory workflow for code changes
1. Identify the target repo - if not on the machine use git_clone, otherwise reference it.
2. Use list_repo_files and read_file_in_repo to understand existing structure before writing anything.
3. Call git_create_branch with a descriptive name (e.g. "feature/issue-42-add-reports").
4. Write or edit files with write_file_in_repo.
5. Run run_tests to verify correctness. Fix failures before proceeding.
6. Call git_status to review changes, then git_commit_and_push.
7. Use the GitHub MCP create_pull_request tool to open a PR against main/master.
   Include a clear PR description referencing the issue number if one exists.

NEVER push directly to main, or master. Always use a feature branch and PR.

## Issue-driven workflow
When given a GitHub issue URL or "owner/repo#N" reference:
1. Use the GitHub MCP get_issue tool to read the full issue body and comments.
2. Summarise your understanding of the problem before acting.
3. Follow the code-change workflow above to implement a fix or feature.
4. Reference the issue number in both the commit message and the PR description.

## PR review workflow
When asked to review a pull request:
1. Use the GitHub MCP tools to read the PR diff and file changes.
2. Analyse the changes for: correctness, Groovy/PS best practices, missing tests, security issues.
3. Provide structured feedback: summary, specific file/line comments, overall recommendation.

## GitHub MCP tool parameter reference
The MCP GitHub tools use these EXACT parameter names - do not substitute REST API names:
- search_repositories   → `query`  (NOT q, NOT search)
- search_code           → `query`  (NOT q)
- search_issues         → `query`  (NOT q)
- list_repositories     → `org` for organisation repos, `username` for user repos
- get_file_contents     → `owner`, `repo`, `path`
- create_pull_request   → `owner`, `repo`, `title`, `head`, `base`, `body`
- get_issue             → `owner`, `repo`, `issue_number`

## General guidelines
- Reason step-by-step before calling tools.
- When writing code, output the complete file - never truncate.
- Prefer Groovy idioms for backend code; follow PowerShell best practices for scripts.
- If a tool call fails, diagnose the error and retry with a corrected approach.
- When in doubt, do less and confirm with the user rather than proceeding on assumptions.
"""


# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: "TokenUsage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


# ---------------------------------------------------------------------------
# Mutable agent state (shared across REPL commands)
# ---------------------------------------------------------------------------

@dataclass
class AgentState:
    thread_id: str
    model: str
    agent: object
    session_history: list = field(default_factory=list)
    session_tokens: TokenUsage = field(default_factory=TokenUsage)
    last_user_input: str = ""


# ---------------------------------------------------------------------------
# Core streaming turn
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _clean(text: str) -> str:
    """Strip Qwen3-style <think>...</think> blocks and normalise whitespace."""
    return _THINK_RE.sub("", text).strip()


async def run_agent_turn(
    agent, user_input: str, thread_id: str, debug: bool = False
) -> tuple[str, TokenUsage]:
    """Stream one agent turn. Prints tool calls and results live."""
    cfg = {"configurable": {"thread_id": thread_id}}
    messages = {"messages": [{"role": "user", "content": user_input}]}
    final_text = ""
    turn_tokens = TokenUsage()

    async for chunk in agent.astream(messages, config=cfg):
        try:
            if debug:
                console.print(f"  [dim magenta][DEBUG] chunk keys: {list(chunk.keys())}[/dim magenta]")

            # langgraph.prebuilt.create_react_agent uses "agent" for the LLM node
            if "agent" in chunk:
                for msg in chunk["agent"].get("messages", []):
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            args_preview = str(tc.get("args", {}))
                            if len(args_preview) > 200:
                                args_preview = args_preview[:200] + "..."
                            console.print(
                                f"  [bold blue]Tool call:[/bold blue] "
                                f"[cyan]{tc['name']}[/cyan]  {args_preview}"
                            )
                    if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                        turn_tokens.input_tokens += msg.usage_metadata.get("input_tokens", 0)
                        turn_tokens.output_tokens += msg.usage_metadata.get("output_tokens", 0)
                    if hasattr(msg, "content") and msg.content:
                        cleaned = _clean(str(msg.content))
                        if cleaned:
                            final_text = cleaned

            if "tools" in chunk:
                for msg in chunk["tools"].get("messages", []):
                    if hasattr(msg, "content") and msg.content:
                        preview = str(msg.content)
                        is_error = getattr(msg, "status", None) == "error" or (
                            isinstance(preview, str) and preview.startswith("Error")
                        )
                        colour = "red" if is_error else "dim"
                        if len(preview) > 300:
                            preview = preview[:300] + "..."
                        console.print(
                            f"  [bold yellow]Result:[/bold yellow] [{colour}]{preview}[/{colour}]"
                        )
        except Exception as chunk_err:
            console.print(f"  [yellow]Stream chunk error (continuing):[/yellow] {chunk_err}")

    return final_text, turn_tokens


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agentism - platform dev agent")
    parser.add_argument("--session", metavar="NAME", default="main",
                        help="Named conversation thread to start in / resume (default: main)")
    parser.add_argument("--issue", metavar="REF",
                        help="Kick off with a GitHub issue (owner/repo#N or full URL)")
    parser.add_argument("--issues", metavar="OWNER/REPO",
                        help="Batch-process all open issues in a repo matching --label")
    parser.add_argument("--label", metavar="LABEL", default="agent-ready",
                        help="Issue label filter for --issues (default: agent-ready)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview writes/commits without making real changes")
    parser.add_argument("--debug", action="store_true",
                        help="Print raw LangGraph chunk keys each turn for debugging")
    return parser.parse_args()


def _issue_ref_to_prompt(ref: str) -> str:
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


def _pr_ref_to_prompt(ref: str) -> str:
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


async def probe_tool_calling(model: str) -> bool:
    """Return True if the model supports native structured tool calling."""
    from langchain_core.tools import tool as lc_tool
    from langchain_core.messages import HumanMessage

    @lc_tool
    def _ping() -> str:
        """Probe tool."""
        return "pong"

    try:
        llm = ChatOllama(model=model, base_url=config.OLLAMA_BASE_URL, temperature=0)
        bound = llm.bind_tools([_ping])
        resp = await bound.ainvoke([HumanMessage(content="Call _ping.")])
        return bool(getattr(resp, "tool_calls", None))
    except Exception:
        return False
    dry_tag = "  [bold red][DRY-RUN][/bold red]" if dry_run else ""
    console.print(Panel(
        f"[bold cyan]Agentism[/bold cyan]  {dry_tag}\n"
        f"Model : [green]{config.OLLAMA_MODEL}[/green] @ {config.OLLAMA_BASE_URL}\n"
        f"Memory: [green]{config.MEMORY_DB}[/green] (SQLite)\n"
        f"GitHub: MCP  |  Workspace: [green]{config.WORKSPACE_DIR}[/green]\n\n"
        "Type your task and press Enter.  Type [bold]!help[/bold] for commands.",
        title="Platform Dev Agent",
        border_style="cyan",
    ))


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------

async def main_async(
    initial_prompt: str = "",
    initial_thread: str = "main",
    batch_issues: list | None = None,
    debug: bool = False,
) -> None:

    # ── Tool-calling capability probe ─────────────────────────────────────────
    with console.status("[cyan]Probing model tool-calling support...[/cyan]"):
        capable = await probe_tool_calling(config.OLLAMA_MODEL)
    if capable:
        console.print(f"[green]✓[/green] {config.OLLAMA_MODEL} supports native tool calling.")
    else:
        console.print(
            f"[bold red]✗ {config.OLLAMA_MODEL} does not support native tool calling.[/bold red]\n"
            "  Tools will NOT be executed. Switch to a capable model with:\n"
            "    ollama pull qwen2.5-coder:7b\n"
            "  Then set OLLAMA_MODEL=qwen2.5-coder:7b in .env\n"
            "  Known-working models on your machine: [cyan]qwen3.6, llama3.2[/cyan]"
        )

    mcp_tools = []
    if config.GITHUB_TOKEN:
        try:
            mcp_client = MultiServerMCPClient({
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": config.GITHUB_TOKEN},
                    "transport": "stdio",
                }
            })
            mcp_tools = await mcp_client.get_tools()
            console.print(f"[green]✓[/green] GitHub MCP: {len(mcp_tools)} tools loaded.")
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow]  GitHub MCP unavailable: {e}")
    else:
        console.print("[yellow]⚠[/yellow]  GITHUB_TOKEN not set - MCP GitHub tools disabled.")

    all_tools = LOCAL_TOOLS + mcp_tools
    # Return tool errors as messages to the model so it can self-correct,
    # instead of raising exceptions that crash the stream.
    for t in all_tools:
        t.handle_tool_error = True

    async with AsyncSqliteSaver.from_conn_string(config.MEMORY_DB) as checkpointer:

        def _build_agent(model_name: str):
            llm = ChatOllama(model=model_name, base_url=config.OLLAMA_BASE_URL, temperature=0)
            # ToolNode catches ALL tool-execution errors (including MCP schema validation)
            # and writes a proper ToolMessage back to state before the checkpoint saves.
            # This prevents the "dangling tool_call with no ToolMessage" state corruption.
            tool_node = ToolNode(all_tools, handle_tool_errors=True)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return create_react_agent(
                    llm,
                    tools=tool_node,
                    prompt=SYSTEM_PROMPT,
                    checkpointer=checkpointer,
                )

        state = AgentState(
            thread_id=initial_thread,
            model=config.OLLAMA_MODEL,
            agent=_build_agent(config.OLLAMA_MODEL),
        )

        console.print(f"[green]✓[/green] {len(all_tools)} tools active.\n")

        _DANGLING_TOOL_CALL = "do not have a corresponding ToolMessage"

        async def _clear_thread(tid: str) -> None:
            """Delete all checkpoint data for a thread, tolerating schema differences across LangGraph versions."""
            # LangGraph has used different table names across versions:
            #   - checkpoints + writes         (current)
            #   - checkpoints + checkpoint_writes  (older)
            # We query the actual schema and only delete from tables that exist.
            candidate_tables = ["checkpoints", "writes", "checkpoint_writes", "checkpoint_blobs"]
            async with aiosqlite.connect(config.MEMORY_DB) as db:
                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ) as cur:
                    existing = {row[0] for row in await cur.fetchall()}
                for table in candidate_tables:
                    if table in existing:
                        await db.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
                await db.commit()

        async def run_turn(user_input: str) -> str:
            console.print("[cyan]Agent working...[/cyan]")
            try:
                response, tokens = await run_agent_turn(
                    state.agent, user_input, state.thread_id, debug=debug
                )
            except Exception as e:
                err_str = str(e)
                if _DANGLING_TOOL_CALL in err_str:
                    # The SQLite checkpoint has a tool_call with no matching ToolMessage.
                    # Auto-clear the thread and retry once — the new ToolNode fix will
                    # prevent this from recurring going forward.
                    console.print(
                        f"[yellow]⚠ Thread '{state.thread_id}' has a corrupted checkpoint "
                        f"(dangling tool call). Auto-clearing and retrying...[/yellow]"
                    )
                    await _clear_thread(state.thread_id)
                    state.session_history.clear()
                    try:
                        response, tokens = await run_agent_turn(
                            state.agent, user_input, state.thread_id, debug=debug
                        )
                    except Exception as retry_e:
                        console.print(f"[red]Retry also failed:[/red] {retry_e}")
                        response = f"Both attempts failed.\n\nOriginal error: `{err_str}`\nRetry error: `{retry_e}`"
                        tokens = TokenUsage()
                else:
                    console.print(f"[yellow]⚠ Stream error:[/yellow] {err_str}")
                    response = (
                        f"I encountered an error while calling a tool:\n\n`{err_str}`\n\n"
                        "Please rephrase the request or check the tool parameter names."
                    )
                    tokens = TokenUsage()
            state.session_history.append((user_input, response))
            state.session_tokens.add(tokens)
            state.last_user_input = user_input
            dry_tag = " [dim red](DRY-RUN)[/dim red]" if config.DRY_RUN else ""
            console.print(Panel(
                Markdown(response) if response else "[dim](no response)[/dim]",
                title=f"[bold green]Agent[/bold green] [dim](thread: {state.thread_id})[/dim]{dry_tag}",
                border_style="green",
            ))
            console.print()
            return response

        # -- Command handlers -------------------------------------------------

        def cmd_help():
            table = Table(title="REPL Commands", border_style="cyan", show_header=True)
            table.add_column("Command", style="bold cyan", no_wrap=True)
            table.add_column("Description")
            for cmd, desc in [
                ("!help",            "Show this command list"),
                ("!tools",           "List all active tools with descriptions"),
                ("!history [N]",     "Show last N turns this session (default 10)"),
                ("!thread <name>",   "Switch to a named conversation thread"),
                ("!threads",         "List all saved conversation threads"),
                ("!clear",           "Delete saved history for the current thread"),
                ("!model <name>",    "Hot-swap the Ollama model (e.g. !model qwen2.5-coder:14b)"),
                ("!issue <ref>",     "Load a GitHub issue (owner/repo#N or full URL)"),
                ("!review <ref>",    "Review a pull request diff (PR URL or owner/repo#N)"),
                ("!cost",            "Show token usage for this session"),
                ("!retry",           "Re-run the last user message"),
                ("!exit / !quit",    "Exit the agent"),
            ]:
                table.add_row(cmd, desc)
            console.print(table)

        def cmd_tools():
            table = Table(title=f"Active Tools ({len(all_tools)})", border_style="blue")
            table.add_column("#", style="dim", width=3)
            table.add_column("Name", style="bold cyan", no_wrap=True)
            table.add_column("Description")
            for i, t in enumerate(all_tools, 1):
                desc = (t.description or "").split("\n")[0][:100]
                table.add_row(str(i), t.name, desc)
            console.print(table)

        def cmd_history(args: list):
            n = int(args[0]) if args and args[0].isdigit() else 10
            history = state.session_history[-n:]
            if not history:
                console.print("[dim]No history this session.[/dim]")
                return
            for i, (u, a) in enumerate(history, 1):
                console.print(Panel(Text(textwrap.shorten(u, 300), style="white"),
                                    title=f"[cyan]You ({i}/{len(history)})[/cyan]",
                                    border_style="cyan"))
                console.print(Panel(
                    Markdown(textwrap.shorten(a, 600)) if a else "[dim](no response)[/dim]",
                    title="[green]Agent[/green]", border_style="green"))

        def cmd_thread(args: list):
            if not args:
                console.print(f"[yellow]Current thread:[/yellow] [bold]{state.thread_id}[/bold]  "
                               "Usage: !thread <name>")
                return
            state.thread_id = args[0].strip()
            state.session_history.clear()
            console.print(f"[green]✓[/green] Switched to thread [bold cyan]{state.thread_id}[/bold cyan].")

        async def cmd_threads():
            try:
                async with aiosqlite.connect(config.MEMORY_DB) as db:
                    async with db.execute(
                        "SELECT DISTINCT thread_id, MAX(checkpoint_id) as latest "
                        "FROM checkpoints GROUP BY thread_id ORDER BY latest DESC"
                    ) as cursor:
                        rows = await cursor.fetchall()
                if not rows:
                    console.print("[dim]No saved threads found.[/dim]")
                    return
                table = Table(title="Saved Threads", border_style="cyan")
                table.add_column("Thread ID", style="bold cyan")
                table.add_column("Latest Checkpoint")
                for tid, latest in rows:
                    marker = " < current" if tid == state.thread_id else ""
                    table.add_row(tid + marker, latest or "-")
                console.print(table)
            except Exception as e:
                console.print(f"[red]Could not read threads:[/red] {e}")

        async def cmd_clear():
            tid = state.thread_id
            try:
                await _clear_thread(tid)
                state.session_history.clear()
                console.print(f"[green]✓[/green] Cleared history for thread [bold cyan]{tid}[/bold cyan].")
            except Exception as e:
                console.print(f"[red]Could not clear thread:[/red] {e}")

        def cmd_model(args: list):
            if not args:
                console.print(f"[yellow]Current model:[/yellow] [bold]{state.model}[/bold]  "
                               "Usage: !model <name>")
                return
            new_model = args[0].strip()
            console.print(f"[cyan]Switching model to[/cyan] [bold]{new_model}[/bold]...")
            try:
                state.agent = _build_agent(new_model)
                state.model = new_model
                console.print(f"[green]✓[/green] Model switched to [bold]{new_model}[/bold].")
            except Exception as e:
                console.print(f"[red]Model switch failed:[/red] {e}")

        def cmd_cost():
            t = state.session_tokens
            table = Table(title="Session Token Usage", border_style="magenta")
            table.add_column("Metric", style="bold")
            table.add_column("Count", style="green", justify="right")
            table.add_row("Input tokens",  f"{t.input_tokens:,}")
            table.add_row("Output tokens", f"{t.output_tokens:,}")
            table.add_row("Total tokens",  f"{t.total:,}")
            table.add_row("Turns",         str(len(state.session_history)))
            console.print(table)

        async def dispatch(raw: str):
            parts = raw.lstrip("!").split()
            if not parts:
                return True
            cmd, args = parts[0].lower(), parts[1:]

            if cmd in {"exit", "quit", "q"}:
                console.print("[dim]Goodbye.[/dim]")
                return "exit"
            elif cmd == "help":       cmd_help()
            elif cmd == "tools":      cmd_tools()
            elif cmd == "history":    cmd_history(args)
            elif cmd == "thread":     cmd_thread(args)
            elif cmd == "threads":    await cmd_threads()
            elif cmd == "clear":      await cmd_clear()
            elif cmd == "model":      cmd_model(args)
            elif cmd == "cost":       cmd_cost()
            elif cmd == "retry":
                if state.last_user_input:
                    return state.last_user_input
                console.print("[dim]Nothing to retry.[/dim]")
            elif cmd == "issue":
                if not args:
                    console.print("Usage: !issue owner/repo#N  or  !issue <full URL>")
                else:
                    return _issue_ref_to_prompt(" ".join(args))
            elif cmd == "review":
                if not args:
                    console.print("Usage: !review <PR URL or owner/repo#N>")
                else:
                    return _pr_ref_to_prompt(" ".join(args))
            else:
                console.print(f"[yellow]Unknown command:[/yellow] !{cmd}  (type !help for a list)")
            return True

        # -- Batch issue processing -------------------------------------------
        if batch_issues:
            console.print(f"[cyan]Batch mode:[/cyan] {len(batch_issues)} prompt(s)\n")
            for ref in batch_issues:
                console.rule(f"[cyan]{ref}[/cyan]")
                state.thread_id = ref.replace("/", "-").replace("#", "-issue-")
                state.session_history.clear()
                await run_turn(ref)
            console.print("[green]✓[/green] Batch complete.")

        elif initial_prompt:
            console.print(f"[dim]Auto-prompt:[/dim] {initial_prompt}\n")
            await run_turn(initial_prompt)

        # -- REPL -------------------------------------------------------------
        while True:
            try:
                user_input = Prompt.ask(
                    f"[bold cyan]You[/bold cyan] [dim](thread: {state.thread_id})[/dim]"
                ).strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]")
                break

            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", "q"}:
                console.print("[dim]Goodbye.[/dim]")
                break

            if user_input.startswith("!"):
                result = await dispatch(user_input)
                if result == "exit":
                    break
                if isinstance(result, str):
                    console.print()
                    await run_turn(result)
                continue

            console.print()
            await run_turn(user_input)


def main() -> None:
    args = parse_args()

    if args.dry_run:
        config.DRY_RUN = True

    initial_prompt = ""
    batch_issues = None

    if args.issues:
        batch_issues = [
            f"Fetch all open issues in {args.issues} with label '{args.label}' "
            "using the MCP list_issues tool, then process each one following the "
            "issue-driven workflow."
        ]
    elif args.issue:
        initial_prompt = _issue_ref_to_prompt(args.issue)

    asyncio.run(main_async(
        initial_prompt=initial_prompt,
        initial_thread=args.session,
        batch_issues=batch_issues,
        debug=args.debug,
    ))


if __name__ == "__main__":
    main()

