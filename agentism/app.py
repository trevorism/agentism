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
from agentism.memory_store import SqliteVecMemoryStore, format_memory_block
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
_AUTO_MODE_MAX_CONTINUATIONS = 3
_AUTO_MODE_PLAN_MARKERS = (
    "execution plan",
    "implementation plan",
    "baseline assessment",
    "design phase",
    "plan summarization",
    "testing strategy",
    "expected outcome",
    "will execute",
    "high-level approach",
)
_AUTO_MODE_CONFIRMATION_MARKERS = (
    "wait for confirmation",
    "await confirmation",
    "please confirm",
    "once you confirm",
    "once confirmed",
    "after you confirm",
    "let me know if you want me to proceed",
    "let me know if you'd like me to proceed",
    "would you like me to proceed",
    "tell me to continue",
)
_AUTO_MODE_BLOCKER_MARKERS = (
    "blocked by",
    "i'm blocked",
    "i am blocked",
    "cannot proceed",
    "can't proceed",
    "missing credentials",
    "missing permission",
    "missing permissions",
    "permission denied",
    "access denied",
    "authentication failed",
    "not found",
    "resource not found",
    "repo does not exist",
    "repository does not exist",
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


def _is_blocked_response(response: str) -> bool:
    lowered = (response or "").lower()
    return any(marker in lowered for marker in _AUTO_MODE_BLOCKER_MARKERS)


def _looks_like_auto_mode_interim_response(user_input: str, response: str) -> bool:
    """Return True when auto mode should continue instead of surfacing the response."""
    text = (response or "").strip()
    if not text:
        return False

    lowered = text.lower()
    if _is_blocked_response(text):
        return False
    if any(marker in lowered for marker in _AUTO_MODE_CONFIRMATION_MARKERS):
        return True
    if any(marker in lowered for marker in _AUTO_MODE_PLAN_MARKERS) and _missing_verification_evidence(text):
        return True

    plan_like_start = re.match(r"^\s*(i will|i'll|here(?: is|'s) (?:the )?(?:plan|approach)|my plan)\b", lowered)
    if plan_like_start and (_is_implementation_request(user_input) or _is_review_or_analysis_request(user_input)):
        return _missing_verification_evidence(text)

    return False


def _build_auto_mode_continue_prompt(user_input: str) -> str:
    return (
        "Auto mode is enabled. Your previous message was an interim plan or status update. "
        "Do not ask for confirmation, do not restate the plan, and do not stop early. "
        "Continue executing the original request right now using the available tools. "
        "Only respond when you have a concrete result or when you are truly blocked by missing "
        "credentials, permissions, or an inaccessible/nonexistent resource.\n\n"
        "Original request:\n"
        f"{user_input}"
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
    if config.OLLAMA_NUM_CTX:
        kwargs["num_ctx"] = config.OLLAMA_NUM_CTX
    return kwargs


def _build_prompt_callable(system_prompt_str: str, max_turns: int):
    """Return a prompt callable for create_react_agent.

    Replaces the old messages_modifier pattern (removed in LangGraph ≥ 0.2.60).
    The callable receives the full agent state and returns the exact message list
    sent to the LLM: a single fresh SystemMessage followed by trimmed history.
    Trimming is non-destructive — the checkpoint is not mutated.

    Trimming strategy: only prior-turn messages are eligible for trimming.
    The current turn (everything after the last HumanMessage) is always kept
    intact so mid-turn tool results are never silently dropped.
    """
    from langchain_core.messages import SystemMessage, ToolMessage, HumanMessage

    sys_msg = SystemMessage(content=system_prompt_str)

    def _prompt(state) -> list:
        messages = state.get("messages", [])
        # Drop any existing system messages — we inject one fresh copy
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        if max_turns and non_system:
            # Split at the last HumanMessage so we never trim the current turn.
            last_human = max(
                (i for i, m in enumerate(non_system) if isinstance(m, HumanMessage)),
                default=0,
            )
            prior = non_system[:last_human]
            current_turn = non_system[last_human:]

            cap = max_turns * 4  # generous: each turn can span multiple tool round-trips
            if len(prior) > cap:
                trimmed_prior = prior[-cap:]
                # Never start with an orphaned ToolMessage
                while trimmed_prior and isinstance(trimmed_prior[0], ToolMessage):
                    trimmed_prior = trimmed_prior[1:]
                non_system = trimmed_prior + current_turn

        return [sys_msg] + non_system

    return _prompt


def print_welcome() -> None:
    ctx_info = f"num_ctx={config.OLLAMA_NUM_CTX}" if config.OLLAMA_NUM_CTX else "num_ctx=model default"
    history_info = f"max_history={config.AGENT_MAX_HISTORY_TURNS} turns" if config.AGENT_MAX_HISTORY_TURNS else "max_history=unlimited"
    console.print(Panel(
        f"[bold cyan]Agentism[/bold cyan]  🤖\n"
        f"Model : [green]{config.OLLAMA_MODEL}[/green] @ {config.OLLAMA_BASE_URL}\n"
        f"LLM opts: temperature={config.OLLAMA_TEMPERATURE}, top_p={config.OLLAMA_TOP_P}, {ctx_info}\n"
        f"Context : {history_info}  (set OLLAMA_NUM_CTX / AGENT_MAX_HISTORY_TURNS in .env)\n"
        f"Memory: [green]{config.MEMORY_DB}[/green] (SQLite + embeddings: {config.OLLAMA_EMBED_MODEL})\n"
        f"GitHub: MCP  |  Workspace: [green]{config.WORKSPACE_DIR}[/green]\n\n"
        "Type your task and press Enter. Type [bold]!help[/bold] for commands.",
        title="Platform Dev Agent",
        border_style="cyan",
    ))


def _augment_user_input_with_memory(user_input: str, memory_block: str) -> str:
    """Attach retrieved thread memory to the turn while keeping the user ask explicit."""
    if not memory_block:
        return user_input
    return (
        "Thread memory context (strictly from this thread):\n"
        f"{memory_block}\n\n"
        "Current user request:\n"
        f"{user_input}"
    )


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

        memory_store = SqliteVecMemoryStore(
            config.MEMORY_DB,
            embed_model=config.OLLAMA_EMBED_MODEL,
            chunk_chars=config.MEMORY_CHUNK_CHARS,
            chunk_overlap=config.MEMORY_CHUNK_OVERLAP,
            prefer_vec=True,
        )
        try:
            await memory_store.initialize()
            console.print(f"[green]✓[/green] Semantic memory backend: {memory_store.backend_label()}.")
        except Exception as mem_init_err:
            console.print(f"[yellow]⚠[/yellow] Semantic memory unavailable: {mem_init_err}")

        async with AsyncSqliteSaver.from_conn_string(config.MEMORY_DB) as checkpointer:

            def build_agent(model_name: str, auto_mode: bool = False):
                llm = ChatOllama(**_ollama_client_kwargs(model_name))
                tool_node = ToolNode(all_tools, handle_tool_errors=True)
                prompt_callable = _build_prompt_callable(
                    build_system_prompt(all_tools, auto_mode=auto_mode),
                    config.AGENT_MAX_HISTORY_TURNS,
                )
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    return create_react_agent(
                        llm,
                        tools=tool_node,
                        prompt=prompt_callable,
                        checkpointer=checkpointer,
                    )

            state = AgentState(
                thread_id=initial_thread,
                model=models["executor"],
                agent=build_agent(models["executor"], auto_mode=False),
            )

            commands = ReplCommands(state=state, all_tools=all_tools, build_agent_fn=build_agent)

            console.print(f"[green]✓[/green] {len(all_tools)} tools active.\n")
            
            auto_status = "[green]enabled[/green]" if state.auto_mode else "[yellow]disabled[/yellow]"
            console.print(f"[cyan]Auto mode:[/cyan] {auto_status} (use [bold]!auto[/bold] to toggle)\n")

            async def run_turn(user_input: str) -> str:
                start = time.monotonic()
                chosen_model = _select_turn_model(user_input, state.model, models)
                active_agent = state.agent if chosen_model == state.model else build_agent(chosen_model, auto_mode=state.auto_mode)
                async def execute_turn(turn_prompt: str, memory_query: str | None = None) -> tuple[str, TokenUsage]:
                    turn_input = turn_prompt

                    if memory_query:
                        try:
                            snippets = await memory_store.retrieve_context(
                                state.thread_id,
                                memory_query,
                                max_items=config.MEMORY_RETRIEVAL_LIMIT,
                                max_chars=config.MEMORY_CONTEXT_CHAR_BUDGET,
                            )
                            memory_block = format_memory_block(snippets)
                            turn_input = _augment_user_input_with_memory(turn_prompt, memory_block)
                        except RuntimeError as mem_read_err:
                            err_msg = str(mem_read_err)
                            if "not found" in err_msg.lower() or "cannot connect" in err_msg.lower():
                                console.print(
                                    f"[yellow]⚠[/yellow] Semantic memory unavailable. Run [bold]!health[/bold] to diagnose."
                                )
                            else:
                                console.print(f"[yellow]⚠[/yellow] Memory retrieval skipped: {err_msg[:80]}")

                    async def heartbeat():
                        while True:
                            await asyncio.sleep(30)
                            elapsed = time.monotonic() - start
                            console.print(f"  [dim]⏱ still working... {elapsed:.0f}s[/dim]")

                    console.print("[cyan]Agent working...[/cyan]")
                    hb = asyncio.create_task(heartbeat())
                    try:
                        response, tokens = await run_agent_turn(
                            active_agent,
                            turn_input,
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
                                    turn_prompt,
                                    state.thread_id,
                                    debug=debug,
                                    chunk_timeout=chunk_timeout,
                                )
                            except Exception as retry_e:
                                console.print(f"[red]Retry also failed:[/red] {retry_e}")
                                response = f"Both attempts failed.\n\nOriginal error: `{err_str}`\nRetry error: `{retry_e}`"
                                tokens = TokenUsage()
                        elif isinstance(e, asyncio.TimeoutError):
                            console.print(
                                f"[yellow]⚠ Context timeout ({chunk_timeout:.0f}s). "
                                f"Auto-compacting thread '{state.thread_id}' and retrying...[/yellow]"
                            )
                            await clear_thread(state.thread_id)
                            state.session_history.clear()
                            try:
                                response, tokens = await run_agent_turn(
                                    active_agent,
                                    turn_prompt,
                                    state.thread_id,
                                    debug=debug,
                                    chunk_timeout=chunk_timeout,
                                )
                            except Exception as retry_e:
                                console.print(f"[red]Retry after compact also failed:[/red] {retry_e}")
                                response = (
                                    f"Thread compacted after {chunk_timeout:.0f}s timeout, "
                                    f"but retry also failed.\n\nError: `{retry_e}`\n\n"
                                    "The task may require a larger context window. "
                                    "Try increasing `OLLAMA_NUM_CTX` in `.env` or switching "
                                    "to a faster model with `!model`."
                                )
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

                    return response, tokens

                try:
                    response, tokens = await execute_turn(user_input, memory_query=user_input)
                    if state.auto_mode:
                        for attempt in range(_AUTO_MODE_MAX_CONTINUATIONS):
                            if not _looks_like_auto_mode_interim_response(user_input, response):
                                break
                            console.print(
                                f"[cyan]Auto mode:[/cyan] interim plan detected; continuing execution "
                                f"({attempt + 1}/{_AUTO_MODE_MAX_CONTINUATIONS})..."
                            )
                            followup_response, followup_tokens = await execute_turn(
                                _build_auto_mode_continue_prompt(user_input)
                            )
                            tokens.add(followup_tokens)
                            response = followup_response
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
                try:
                    await memory_store.add_turn(state.thread_id, user_input, response)
                except Exception as mem_write_err:
                    err_msg = str(mem_write_err)
                    if "404" in err_msg or "not found" in err_msg.lower():
                        pass  # Silently skip; already warned at retrieval time
                    else:
                        console.print(f"[yellow]⚠[/yellow] Memory write skipped: {mem_write_err}")
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

