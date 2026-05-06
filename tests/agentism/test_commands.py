from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from rich.console import Console
from rich.panel import Panel

from agentism import commands
from agentism.commands import ReplCommands
from agentism.state import AgentState


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


# -- New tests for !pr and !merge --

def test_cmd_pr_requires_args():
    repl = ReplCommands(
        state=_state(),
        all_tools=[],
        build_agent_fn=lambda model_name: object(),
    )
    result = repl.cmd_pr([])
    assert result is None


def test_cmd_pr_with_minimal_args():
    repl = ReplCommands(
        state=_state(),
        all_tools=[],
        build_agent_fn=lambda model_name: object(),
    )
    result = repl.cmd_pr(["owner/repo", "feat: add feature"])
    assert result is not None
    assert "owner/repo" in result
    assert "feat: add feature" in result
    assert "create a pull request" in result.lower()
    assert "master" in result


def test_cmd_pr_with_body():
    repl = ReplCommands(
        state=_state(),
        all_tools=[],
        build_agent_fn=lambda model_name: object(),
    )
    result = repl.cmd_pr(["owner/repo", "feat: add feature", "This is the body"])
    assert "This is the body" in result


def test_cmd_merge_requires_args():
    repl = ReplCommands(
        state=_state(),
        all_tools=[],
        build_agent_fn=lambda model_name: object(),
    )
    result = repl.cmd_merge([])
    assert result is None


def test_cmd_merge_with_ref():
    repl = ReplCommands(
        state=_state(),
        all_tools=[],
        build_agent_fn=lambda model_name: object(),
    )
    result = repl.cmd_merge(["owner/repo#42"])
    assert result is not None
    assert "owner/repo#42" in result
    assert "merge" in result.lower()


def test_cmd_pr_in_command_list():
    cmd_names = [c[0] for c in commands._COMMANDS]
    assert "pr" in cmd_names


def test_cmd_merge_in_command_list():
    cmd_names = [c[0] for c in commands._COMMANDS]
    assert "merge" in cmd_names


@pytest.mark.asyncio
async def test_cmd_health_uses_active_state_model(monkeypatch):
    state = _state()
    state.model = "qwen3.6"
    repl = ReplCommands(
        state=state,
        all_tools=[],
        build_agent_fn=lambda model_name: object(),
    )

    mock_run = AsyncMock(return_value=[])
    mock_render = lambda checks: Panel("ok")

    monkeypatch.setattr("tools.health.run_health_checks", mock_run)
    monkeypatch.setattr("tools.health.render_health_report", mock_render)

    result = await repl.cmd_health()

    assert isinstance(result, Panel)
    mock_run.assert_awaited_once_with(active_model="qwen3.6")

