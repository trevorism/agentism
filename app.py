"""Application orchestration for the Agentism REPL."""
import asyncio
import inspect
import time
import warnings

from langchain_ollama import ChatOllama
from langgraph.prebuilt import ToolNode, create_react_agent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_mcp_adapters.client import MultiServerMCPClient
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

import config
from commands import ReplCommands, clear_thread
from prompts import build_system_prompt, issue_ref_to_prompt, pr_ref_to_prompt
from state import AgentState, TokenUsage
from streaming import probe_tool_calling, run_agent_turn
from tools import LOCAL_TOOLS

console = Console()
_DANGLING_TOOL_CALL = "do not have a corresponding ToolMessage"


def print_welcome() -> None:
    dry_tag = "  [bold red][DRY-RUN][/bold red]" if config.DRY_RUN else ""
    console.print(Panel(
        f"[bold cyan]Agentism[/bold cyan]  🤖{dry_tag}\n"
        f"Model : [green]{config.OLLAMA_MODEL}[/green] @ {config.OLLAMA_BASE_URL}\n"
        f"Memory: [green]{config.MEMORY_DB}[/green] (SQLite)\n"
        f"GitHub: MCP  |  Workspace: [green]{config.WORKSPACE_DIR}[/green]\n\n"
        "Type your task and press Enter. Type [bold]!help[/bold] for commands.",
        title="Platform Dev Agent",
        border_style="cyan",
    ))


async def _safe_close_async(resource) -> None:
    """Close a resource if it exposes async or sync close hooks."""
    if resource is None:
        return

    close_fn = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if not callable(close_fn):
        return

    result = close_fn()
    if inspect.isawaitable(result):
        await result


async def _load_github_mcp_tools() -> tuple[list, object]:
    """Create the GitHub MCP client and fetch its tools."""
    mcp_client = MultiServerMCPClient({
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": config.GITHUB_TOKEN},
            "transport": "stdio",
        }
    })
    tools = await mcp_client.get_tools()
    return tools, mcp_client


async def main_async(
    initial_prompt: str = "",
    initial_thread: str = "main",
    batch_issues: list | None = None,
    debug: bool = False,
    chunk_timeout: float = 1200.0,
) -> None:
    print_welcome()
    mcp_client = None

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
            mcp_tools, mcp_client = await _load_github_mcp_tools()
            console.print(f"[green]✓[/green] GitHub MCP: {len(mcp_tools)} tools loaded.")
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow]  GitHub MCP unavailable: {e}")
    else:
        console.print("[yellow]⚠[/yellow]  GITHUB_TOKEN not set - MCP GitHub tools disabled.")

    try:
        all_tools = LOCAL_TOOLS + mcp_tools
        for t in all_tools:
            t.handle_tool_error = True

        async with AsyncSqliteSaver.from_conn_string(config.MEMORY_DB) as checkpointer:

            def build_agent(model_name: str):
                llm = ChatOllama(model=model_name, base_url=config.OLLAMA_BASE_URL, temperature=0)
                tool_node = ToolNode(all_tools, handle_tool_errors=True)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    return create_react_agent(
                        llm,
                        tools=tool_node,
                        prompt=build_system_prompt(all_tools),
                        checkpointer=checkpointer,
                    )

            state = AgentState(
                thread_id=initial_thread,
                model=config.OLLAMA_MODEL,
                agent=build_agent(config.OLLAMA_MODEL),
            )

            commands = ReplCommands(state=state, all_tools=all_tools, build_agent_fn=build_agent)

            console.print(f"[green]✓[/green] {len(all_tools)} tools active.\n")

            async def run_turn(user_input: str) -> str:
                start = time.monotonic()

                async def heartbeat():
                    while True:
                        await asyncio.sleep(30)
                        elapsed = time.monotonic() - start
                        console.print(f"  [dim]⏱ still working... {elapsed:.0f}s[/dim]")

                try:
                    console.print("[cyan]Agent working...[/cyan]")
                    hb = asyncio.create_task(heartbeat())
                    try:
                        response, tokens = await run_agent_turn(
                            state.agent,
                            user_input,
                            state.thread_id,
                            debug=debug,
                            chunk_timeout=chunk_timeout,
                        )
                    except Exception as e:
                        err_str = str(e)
                        if _DANGLING_TOOL_CALL in err_str:
                            console.print(
                                f"[yellow]⚠ Thread '{state.thread_id}' has a corrupted checkpoint "
                                f"(dangling tool call). Auto-clearing and retrying...[/yellow]"
                            )
                            await clear_thread(state.thread_id)
                            state.session_history.clear()
                            try:
                                response, tokens = await run_agent_turn(
                                    state.agent,
                                    user_input,
                                    state.thread_id,
                                    debug=debug,
                                    chunk_timeout=chunk_timeout,
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
                    finally:
                        hb.cancel()
                        try:
                            await hb
                        except asyncio.CancelledError:
                            pass
                        elapsed = time.monotonic() - start
                        if elapsed > 5:
                            console.print(f"  [dim]✓ completed in {elapsed:.1f}s[/dim]")
                except Exception:
                    raise

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

            if batch_issues:
                console.print(f"[cyan]Batch mode:[/cyan] {len(batch_issues)} prompt(s)\n")
                for prompt in batch_issues:
                    console.rule(f"[cyan]{prompt}[/cyan]")
                    state.thread_id = prompt.replace("/", "-").replace("#", "-issue-")
                    state.session_history.clear()
                    await run_turn(prompt)
                console.print("[green]✓[/green] Batch complete.")

            elif initial_prompt:
                console.print(f"[dim]Auto-prompt:[/dim] {initial_prompt}\n")
                await run_turn(initial_prompt)

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
                    result = await commands.dispatch(user_input, issue_ref_to_prompt, pr_ref_to_prompt)
                    if result == "exit":
                        break
                    if isinstance(result, Panel):
                        console.print()
                        console.print(result)
                        console.print()
                    elif isinstance(result, str):
                        console.print()
                        await run_turn(result)
                    continue
                await run_turn(user_input)
    finally:
        await _safe_close_async(mcp_client)
