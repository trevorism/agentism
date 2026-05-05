"""REPL bang-commands (!help, !clear, !model, etc.)."""
from __future__ import annotations

import asyncio
import textwrap
from typing import Any, Callable

import aiosqlite
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import config
from state import AgentState
from tool_metadata import render_tool_table_rows

console = Console()

_CANDIDATE_TABLES = ["checkpoints", "writes", "checkpoint_writes", "checkpoint_blobs"]


# ---------------------------------------------------------------------------
# Thread helpers
# ---------------------------------------------------------------------------

async def clear_thread(tid: str) -> None:
    """Delete all checkpoint rows for a thread, tolerating LangGraph schema differences."""
    async with aiosqlite.connect(config.MEMORY_DB) as db:
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            existing = {row[0] for row in await cur.fetchall()}
        for table in _CANDIDATE_TABLES:
            if table in existing:
                await db.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
        await db.commit()


# ---------------------------------------------------------------------------
# Command registry: declarative list of (name, method, is_async, description)
# ---------------------------------------------------------------------------

_COMMANDS: list[tuple[str, str, bool, str]] = [
    ("help",    "cmd_help",    False, "Show this command list"),
    ("tools",   "cmd_tools",   False, "List all active tools"),
    ("history", "cmd_history", False, "Show last N turns (default 10)"),
    ("thread",  "cmd_thread",  False, "Switch conversation thread"),
    ("threads", "cmd_threads", True,  "List all saved threads"),
    ("clear",   "cmd_clear",   True,  "Delete history for current thread"),
    ("model",   "cmd_model",   False, "Hot-swap the Ollama model"),
    ("cost",    "cmd_cost",    False, "Show token usage this session"),
    ("retry",   "cmd_retry",   False, "Re-run the last message"),
    ("issue",   "cmd_issue",   False, "Load a GitHub issue mid-session"),
    ("review",  "cmd_review",  False, "Review a pull request diff"),
    ("exit",    "cmd_exit",    False, "Exit the agent"),
    ("quit",    "cmd_exit",    False, "Exit the agent"),
    ("q",       "cmd_exit",    False, "Exit the agent"),
]


# ---------------------------------------------------------------------------
# ReplCommands: orchestrates command dispatch
# ---------------------------------------------------------------------------

class ReplCommands:
    """Orchestrates command dispatch via a declarative command registry."""

    def __init__(self, state: AgentState, all_tools: list, build_agent_fn: Callable):
        self.state = state
        self.all_tools = all_tools
        self._build_agent = build_agent_fn

    # -- command implementations -------------------------------------------

    def cmd_help(self) -> None:
        table = Table(title="REPL Commands", border_style="cyan")
        table.add_column("Command", style="bold cyan", no_wrap=True)
        table.add_column("Description")
        for cmd_name, _, _, desc in _COMMANDS:
            table.add_row(f"!{cmd_name}", desc)
        console.print(table)

    def cmd_tools(self) -> None:
        table = Table(title=f"Active Tools ({len(self.all_tools)})", border_style="blue")
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="bold cyan", no_wrap=True)
        table.add_column("Description")
        for row in render_tool_table_rows(self.all_tools):
            table.add_row(*row)
        console.print(table)

    def cmd_history(self, args: list) -> None:
        n = int(args[0]) if args and args[0].isdigit() else 10
        history = self.state.session_history[-n:]
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

    def cmd_thread(self, args: list) -> None:
        if not args:
            console.print(f"[yellow]Current thread:[/yellow] {self.state.thread_id}  Usage: !thread <name>")
            return
        self.state.thread_id = args[0].strip()
        self.state.session_history.clear()
        console.print(f"[green]✓[/green] Switched to thread [bold cyan]{self.state.thread_id}[/bold cyan].")

    async def cmd_threads(self) -> None:
        try:
            async with aiosqlite.connect(config.MEMORY_DB) as db:
                async with db.execute(
                    "SELECT DISTINCT thread_id, MAX(checkpoint_id) FROM checkpoints "
                    "GROUP BY thread_id ORDER BY 2 DESC"
                ) as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                console.print("[dim]No saved threads.[/dim]")
                return
            table = Table(title="Saved Threads", border_style="cyan")
            table.add_column("Thread ID", style="bold cyan")
            table.add_column("Latest Checkpoint")
            for tid, latest in rows:
                marker = " < current" if tid == self.state.thread_id else ""
                table.add_row(tid + marker, latest or "-")
            console.print(table)
        except Exception as e:
            console.print(f"[red]Could not read threads:[/red] {e}")

    async def cmd_clear(self) -> None:
        tid = self.state.thread_id
        try:
            await clear_thread(tid)
            self.state.session_history.clear()
            console.print(f"[green]✓[/green] Cleared thread [bold cyan]{tid}[/bold cyan].")
        except Exception as e:
            console.print(f"[red]Could not clear thread:[/red] {e}")

    def cmd_model(self, args: list) -> None:
        if not args:
            console.print(f"[yellow]Current model:[/yellow] {self.state.model}  Usage: !model <name>")
            return
        new_model = args[0].strip()
        try:
            self.state.agent = self._build_agent(new_model)
            self.state.model = new_model
            console.print(f"[green]✓[/green] Model switched to [bold]{new_model}[/bold].")
        except Exception as e:
            console.print(f"[red]Model switch failed:[/red] {e}")

    def cmd_cost(self) -> None:
        t = self.state.session_tokens
        table = Table(title="Session Token Usage", border_style="magenta")
        table.add_column("Metric", style="bold")
        table.add_column("Count", style="green", justify="right")
        table.add_row("Input tokens",  f"{t.input_tokens:,}")
        table.add_row("Output tokens", f"{t.output_tokens:,}")
        table.add_row("Total tokens",  f"{t.total:,}")
        table.add_row("Turns",         str(len(self.state.session_history)))
        console.print(table)

    def cmd_retry(self) -> str | None:
        if self.state.last_user_input:
            return self.state.last_user_input
        console.print("[dim]Nothing to retry.[/dim]")
        return None

    def cmd_issue(self, args: list, issue_fn: Callable) -> str | None:
        if args:
            return issue_fn(" ".join(args))
        console.print("Usage: !issue owner/repo#N  or  !issue <full URL>")
        return None

    def cmd_review(self, args: list, pr_fn: Callable) -> str | None:
        if args:
            return pr_fn(" ".join(args))
        console.print("Usage: !review <PR URL or owner/repo#N>")
        return None

    def cmd_exit(self) -> str:
        console.print("[dim]Goodbye.[/dim]")
        return "exit"

    # -- dispatch ----------------------------------------------------------

    async def dispatch(self, raw: str, issue_fn: Callable, pr_fn: Callable) -> str | bool:
        """Route a !command. Returns 'exit', a prompt string, or True (handled)."""
        parts = raw.lstrip("!").split()
        if not parts:
            return True
        cmd = parts[0].lower()

        # Find the command definition
        cmd_def = next((c for c in _COMMANDS if c[0] == cmd), None)
        if cmd_def is None:
            console.print(f"[yellow]Unknown command:[/yellow] !{cmd}  (type !help)")
            return True

        # Unpack: (name, method_name, is_async, description)
        _, method_name, is_async, _ = cmd_def

        handler = getattr(self, method_name)

        # Build arguments: always pass args list; inject issue_fn/pr_fn where needed
        kwargs: dict[str, Any] = {"args": parts[1:]}
        if method_name == "cmd_issue":
            kwargs["issue_fn"] = issue_fn
        if method_name == "cmd_review":
            kwargs["pr_fn"] = pr_fn

        result = handler(**kwargs)
        if is_async and asyncio.iscoroutine(result):
            result = await result

        return result
