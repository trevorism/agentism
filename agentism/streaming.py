"""Async streaming helpers for the ReAct agent turn."""
import asyncio
import inspect

from langchain_ollama import ChatOllama
from rich.console import Console

from agentism import config
from agentism.state import TokenUsage, clean_response

console = Console()


async def _safe_close_llm(llm) -> None:
    """Close an LLM if it exposes close hooks across sync/async variants."""
    close_fn = getattr(llm, "aclose", None) or getattr(llm, "close", None)
    if not callable(close_fn):
        return

    result = close_fn()
    if inspect.isawaitable(result):
        await result


async def _astream_with_chunk_timeout(aiter, timeout_secs: float):
    """Yield items from an async iterator; raise TimeoutError if a chunk is too slow."""
    while True:
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=timeout_secs)
            yield chunk
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(
                f"No response from model for {timeout_secs:.0f}s. "
                "The model may be processing a very large context. "
                "Try: (1) '!compact' to reset the thread context, "
                "(2) set OLLAMA_NUM_CTX=16384 in .env to increase Ollama's context window, "
                "(3) set AGENT_MAX_HISTORY_TURNS=10 in .env to cap history, "
                "or (4) switch to a faster model with '!model'."
            )


async def run_agent_turn(
    agent,
    user_input: str,
    thread_id: str,
    debug: bool = False,
    chunk_timeout: float = 1200.0,
) -> tuple[str, TokenUsage]:
    """Stream one ReAct turn. Prints tool calls and results live; returns (text, tokens)."""
    cfg = {"configurable": {"thread_id": thread_id}}
    messages = {"messages": [{"role": "user", "content": user_input}]}
    final_text = ""
    turn_tokens = TokenUsage()

    async for chunk in _astream_with_chunk_timeout(
        agent.astream(messages, config=cfg).__aiter__(), chunk_timeout
    ):
        try:
            if debug:
                console.print(f"  [dim magenta][DEBUG] keys: {list(chunk.keys())}[/dim magenta]")

            if "agent" in chunk:
                for msg in chunk["agent"].get("messages", []):
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            preview = str(tc.get("args", {}))
                            if len(preview) > 200:
                                preview = preview[:200] + "..."
                            console.print(
                                f"  [bold blue]Tool call:[/bold blue] "
                                f"[cyan]{tc['name']}[/cyan]  {preview}"
                            )
                    if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                        turn_tokens.input_tokens += msg.usage_metadata.get("input_tokens", 0)
                        turn_tokens.output_tokens += msg.usage_metadata.get("output_tokens", 0)
                    if hasattr(msg, "content") and msg.content:
                        cleaned = clean_response(str(msg.content))
                        if cleaned:
                            final_text = cleaned

            if "tools" in chunk:
                for msg in chunk["tools"].get("messages", []):
                    if hasattr(msg, "content") and msg.content:
                        preview = str(msg.content)
                        is_error = getattr(msg, "status", None) == "error" or preview.startswith("Error")
                        colour = "red" if is_error else "dim"
                        if len(preview) > 300:
                            preview = preview[:300] + "..."
                        console.print(f"  [bold yellow]Result:[/bold yellow] [{colour}]{preview}[/{colour}]")

        except Exception as chunk_err:
            console.print(f"  [yellow]Stream chunk error:[/yellow] {chunk_err}")

    return final_text, turn_tokens


async def probe_tool_calling(model: str) -> bool:
    """Return True if the model supports native structured tool calling via Ollama."""
    from langchain_core.tools import tool as lc_tool
    from langchain_core.messages import HumanMessage

    @lc_tool
    def _ping() -> str:
        """Probe tool."""
        return "pong"

    llm = ChatOllama(model=model, base_url=config.OLLAMA_BASE_URL, temperature=0)
    try:
        bound = llm.bind_tools([_ping])
        resp = await bound.ainvoke([HumanMessage(content="Call _ping.")])
        return bool(getattr(resp, "tool_calls", None))
    except Exception:
        return False
    finally:
        await _safe_close_llm(llm)

