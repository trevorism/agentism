"""REPL bang-commands (!help, !clear, !model, etc.)."""
import textwrap

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


async def clear_thread(tid: str) -> None:
    """Delete all checkpoint rows for a thread, tolerating LangGraph schema differences."""
    async with aiosqlite.connect(config.MEMORY_DB) as db:
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            existing = {row[0] for row in await cur.fetchall()}
        for table in _CANDIDATE_TABLES:
            if table in existing:
                await db.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
        await db.commit()


class ReplCommands:
    def __init__(self, state: AgentState, all_tools: list, build_agent_fn):
        self.state = state
        self.all_tools = all_tools
        self._build_agent = build_agent_fn

    def cmd_help(self):
        table = Table(title="REPL Commands", border_style="cyan")
        table.add_column("Command", style="bold cyan", no_wrap=True)
        table.add_column("Description")
        for cmd, desc in [
            ("!help",          "Show this command list"),
            ("!tools",         "List all active tools"),
            ("!history [N]",   "Show last N turns (default 10)"),
            ("!thread <name>", "Switch conversation thread"),
            ("!threads",       "List all saved threads"),
            ("!clear",         "Delete history for current thread"),
            ("!model <name>",  "Hot-swap the Ollama model"),
            ("!issue <ref>",   "Load a GitHub issue mid-session"),
            ("!review <ref>",  "Review a pull request diff"),
            ("!cost",          "Show token usage this session"),
            ("!retry",         "Re-run the last message"),
            ("!exit / !quit",  "Exit the agent"),
        ]:
            table.add_row(cmd, desc)
        console.print(table)

    def cmd_tools(self):
        table = Table(title=f"Active Tools ({len(self.all_tools)})", border_style="blue")
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="bold cyan", no_wrap=True)
        table.add_column("Description")
        for row in render_tool_table_rows(self.all_tools):
            table.add_row(*row)
        console.print(table)

    def cmd_history(self, args: list):
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

    def cmd_thread(self, args: list):
        if not args:
            console.print(f"[yellow]Current thread:[/yellow] {self.state.thread_id}  Usage: !thread <name>")
            return
        self.state.thread_id = args[0].strip()
        self.state.session_history.clear()
        console.print(f"[green]✓[/green] Switched to thread [bold cyan]{self.state.thread_id}[/bold cyan].")

    async def cmd_threads(self):
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

    async def cmd_clear(self):
        tid = self.state.thread_id
        try:
            await clear_thread(tid)
            self.state.session_history.clear()
            console.print(f"[green]✓[/green] Cleared thread [bold cyan]{tid}[/bold cyan].")
        except Exception as e:
            console.print(f"[red]Could not clear thread:[/red] {e}")

    def cmd_model(self, args: list):
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

    def cmd_cost(self):
        t = self.state.session_tokens
        table = Table(title="Session Token Usage", border_style="magenta")
        table.add_column("Metric", style="bold")
        table.add_column("Count", style="green", justify="right")
        table.add_row("Input tokens",  f"{t.input_tokens:,}")
        table.add_row("Output tokens", f"{t.output_tokens:,}")
        table.add_row("Total tokens",  f"{t.total:,}")
        table.add_row("Turns",         str(len(self.state.session_history)))
        console.print(table)

    async def dispatch(self, raw: str, issue_fn, pr_fn):
        """Route a !command. Returns 'exit', a prompt string, or True (handled)."""
        parts = raw.lstrip("!").split()
        if not parts:
            return True
        cmd, args = parts[0].lower(), parts[1:]

        if cmd in {"exit", "quit", "q"}:
            console.print("[dim]Goodbye.[/dim]")
            return "exit"
        elif cmd == "help":    self.cmd_help()
        elif cmd == "tools":   self.cmd_tools()
        elif cmd == "history": self.cmd_history(args)
        elif cmd == "thread":  self.cmd_thread(args)
        elif cmd == "threads": await self.cmd_threads()
        elif cmd == "clear":   await self.cmd_clear()
        elif cmd == "model":   self.cmd_model(args)
        elif cmd == "cost":    self.cmd_cost()
        elif cmd == "retry":
            if self.state.last_user_input:
                return self.state.last_user_input
            console.print("[dim]Nothing to retry.[/dim]")
        elif cmd == "issue":
            if args:
                return issue_fn(" ".join(args))
            console.print("Usage: !issue owner/repo#N  or  !issue <full URL>")
        elif cmd == "review":
            if args:
                return pr_fn(" ".join(args))
            console.print("Usage: !review <PR URL or owner/repo#N>")
        else:
            console.print(f"[yellow]Unknown command:[/yellow] !{cmd}  (type !help)")
        return True

