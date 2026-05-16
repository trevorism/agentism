"""Application orchestration for the Agentism REPL."""
import asyncio
import inspect
import os
import re
import time
import warnings

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import ToolNode, create_react_agent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_mcp_adapters.client import MultiServerMCPClient
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from agentism import config
from agentism.commands import ReplCommands, clear_thread
from agentism.prompts import build_system_prompt, issue_ref_to_prompt, pr_ref_to_prompt
from agentism.state import AgentState, TokenUsage
from agentism.streaming import probe_tool_calling, run_agent_turn
from tools import LOCAL_TOOLS

console = Console()
_DANGLING_TOOL_CALL = "do not have a corresponding ToolMessage"
_IMPLEMENTATION_HINTS = (
    "implement", "fix", "refactor", "add", "create", "update", "write code", "patch", "bug",
)
_REVIEW_HINTS = (
    "review", "analyze", "analysis", "summary", "audit", "pr", "pull request",
)
_VERIFICATION_SIGNALS = (
    "run_tests", "pytest", "test result", "passed", "failed", "verification", "validated",
)


def _routing_models(default_model: str) -> dict[str, str]:
    """Resolve optional per-phase model routing from environment variables."""
    executor = os.getenv("OLLAMA_MODEL_EXECUTOR", "").strip() or default_model
    planner = os.getenv("OLLAMA_MODEL_PLANNER", "").strip() or default_model
    critic = os.getenv("OLLAMA_MODEL_CRITIC", "").strip() or executor
    return {
        "default": default_model,
        "executor": executor,
        "planner": planner,
        "critic": critic,
    }


def _is_implementation_request(user_input: str) -> bool:
    text = (user_input or "").lower()
    return any(token in text for token in _IMPLEMENTATION_HINTS)


def _is_review_or_analysis_request(user_input: str) -> bool:
    text = (user_input or "").lower()
    return any(token in text for token in _REVIEW_HINTS)


def _select_turn_model(user_input: str, state_default_model: str, models: dict[str, str]) -> str:
    """Choose planner/executor/default model for the current prompt."""
    if _is_review_or_analysis_request(user_input):
        return models.get("planner", state_default_model)
    if _is_implementation_request(user_input):
        return models.get("executor", state_default_model)
    return state_default_model


def _missing_verification_evidence(response: str) -> bool:
    if not response.strip():
        return True
    lowered = response.lower()
    return not any(signal in lowered for signal in _VERIFICATION_SIGNALS)


def _should_run_critic_pass(user_input: str, response: str) -> bool:
    if not response.strip():
        return False
    return _is_review_or_analysis_request(user_input) or (
        _is_implementation_request(user_input) and _missing_verification_evidence(response)
    )


async def _run_critic_pass(model_name: str, user_input: str, draft_response: str) -> str:
    """Run a lightweight local critique pass and return an improved final response."""
    llm = ChatOllama(**_ollama_client_kwargs(model_name))
    prompt = (
        "You are a strict reviewer for agent output. Improve the draft response for correctness, clarity, "
        "and actionable verification steps. Preserve factual claims and do not invent tool outputs. "
        "If verification evidence is missing for implementation tasks, add explicit verification steps. "
        "Return only the final revised response markdown.\n\n"
        f"User request:\n{user_input}\n\n"
        f"Draft response:\n{draft_response}"
    )
    try:
        revised = await llm.ainvoke([HumanMessage(content=prompt)])
        content = getattr(revised, "content", "")
        text = str(content).strip()
        if not text:
            return draft_response
        # Strip optional fenced wrappers added by the critic model.
        text = re.sub(r"^```(?:markdown)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return text.strip() or draft_response
    finally:
        await _safe_close_async(llm)


def _ollama_client_kwargs(model_name: str) -> dict:
    """Build ChatOllama kwargs from runtime config."""
    kwargs: dict = {
        "model": model_name,
        "base_url": config.OLLAMA_BASE_URL,
        "temperature": config.OLLAMA_TEMPERATURE,
    }
    if config.OLLAMA_TOP_P is not None:
        kwargs["top_p"] = config.OLLAMA_TOP_P
    return kwargs


def print_welcome() -> None:
    console.print(Panel(
        f"[bold cyan]Agentism[/bold cyan]  🤖\n"
        f"Model : [green]{config.OLLAMA_MODEL}[/green] @ {config.OLLAMA_BASE_URL}\n"
        f"LLM opts: temperature={config.OLLAMA_TEMPERATURE}, top_p={config.OLLAMA_TOP_P}\n"
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
        models = _routing_models(config.OLLAMA_MODEL)
        all_tools = LOCAL_TOOLS + mcp_tools
        for t in all_tools:
            t.handle_tool_error = True

        async with AsyncSqliteSaver.from_conn_string(config.MEMORY_DB) as checkpointer:

            def build_agent(model_name: str):
                llm = ChatOllama(**_ollama_client_kwargs(model_name))
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
                model=models["executor"],
                agent=build_agent(models["executor"]),
            )

            commands = ReplCommands(state=state, all_tools=all_tools, build_agent_fn=build_agent)

            console.print(f"[green]✓[/green] {len(all_tools)} tools active.\n")

            async def run_turn(user_input: str) -> str:
                start = time.monotonic()
                chosen_model = _select_turn_model(user_input, state.model, models)
                active_agent = state.agent if chosen_model == state.model else build_agent(chosen_model)

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
                            active_agent,
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
                                    active_agent,
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
                    if _should_run_critic_pass(user_input, response):
                        critic_model = models.get("critic", state.model)
                        try:
                            response = await _run_critic_pass(critic_model, user_input, response)
                        except Exception as critic_err:
                            console.print(f"[yellow]⚠ Critic pass skipped:[/yellow] {critic_err}")
                except Exception:
                    raise

                state.session_history.append((user_input, response))
                state.session_tokens.add(tokens)
                state.last_user_input = user_input
                console.print(Panel(
                    Markdown(response) if response else "[dim](no response)[/dim]",
                    title=f"[bold green]Agent[/bold green] [dim](thread: {state.thread_id})[/dim]",
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

