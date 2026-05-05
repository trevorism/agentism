from types import SimpleNamespace

import pytest
from rich.console import Console

import commands
from commands import ReplCommands
from state import AgentState


def _tool(name: str, description: str = ""):
    return SimpleNamespace(name=name, description=description)


def _state() -> AgentState:
    return AgentState(thread_id="main", model="test-model", agent=object())


def test_cmd_tools_renders_active_tools_table(monkeypatch):
    recording_console = Console(record=True, width=120)
    monkeypatch.setattr(commands, "console", recording_console)

    repl = ReplCommands(
        state=_state(),
        all_tools=[
            _tool("zeta_tool", "Zeta description."),
            _tool("alpha_tool", "Alpha description."),
        ],
        build_agent_fn=lambda model_name: object(),
    )

    repl.cmd_tools()
    output = recording_console.export_text()

    assert "Active Tools (2)" in output
    assert "zeta_tool" in output
    assert "Zeta description." in output
    assert "alpha_tool" in output
    assert "Alpha description." in output


def test_cmd_tools_uses_shared_truncation(monkeypatch):
    recording_console = Console(record=True, width=140)
    monkeypatch.setattr(commands, "console", recording_console)

    long_description = "x" * 150
    repl = ReplCommands(
        state=_state(),
        all_tools=[_tool("long_tool", long_description)],
        build_agent_fn=lambda model_name: object(),
    )

    repl.cmd_tools()
    output = recording_console.export_text()

    assert "long_tool" in output
    assert "x" * 100 in output
    assert "x" * 101 not in output


@pytest.mark.asyncio
async def test_dispatch_help_does_not_pass_unexpected_args(monkeypatch):
    recording_console = Console(record=True, width=120)
    monkeypatch.setattr(commands, "console", recording_console)

    repl = ReplCommands(
        state=_state(),
        all_tools=[],
        build_agent_fn=lambda model_name: object(),
    )

    result = await repl.dispatch("!help", issue_fn=lambda s: s, pr_fn=lambda s: s)

    assert result is None
    output = recording_console.export_text()
    assert "REPL Commands" in output


@pytest.mark.asyncio
async def test_dispatch_thread_passes_args_and_updates_state():
    state = _state()
    repl = ReplCommands(
        state=state,
        all_tools=[],
        build_agent_fn=lambda model_name: object(),
    )

    result = await repl.dispatch("!thread feature-x", issue_fn=lambda s: s, pr_fn=lambda s: s)

    assert result is None
    assert state.thread_id == "feature-x"


