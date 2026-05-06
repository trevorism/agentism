from types import SimpleNamespace

from agentism.prompts import BASE_SYSTEM_PROMPT, build_system_prompt


def _tool(name: str, description: str = ""):
    return SimpleNamespace(name=name, description=description)


def test_build_system_prompt_includes_base_rules():
    prompt = build_system_prompt([])
    assert BASE_SYSTEM_PROMPT in prompt
    assert "## Available tools" not in prompt


def test_build_system_prompt_lists_tools_deterministically():
    tools = [
        _tool("zeta_tool", "Zeta description."),
        _tool("alpha_tool", "Alpha description.\nExtra line ignored."),
    ]
    prompt = build_system_prompt(tools)
    alpha_index = prompt.index("- alpha_tool: Alpha description.")
    zeta_index = prompt.index("- zeta_tool: Zeta description.")
    assert alpha_index < zeta_index


def test_build_system_prompt_deduplicates_tool_names():
    prompt = build_system_prompt([
        _tool("alpha_tool", "First description."),
        _tool("alpha_tool", "Second description should not appear."),
    ])
    assert prompt.count("- alpha_tool:") == 1
    assert "Second description should not appear." not in prompt


def test_build_system_prompt_includes_only_present_github_hints():
    prompt = build_system_prompt([
        _tool("search_repositories", "Search repos."),
        _tool("get_issue", "Read an issue."),
        _tool("local_tool", "Local tool."),
    ])
    assert "- search_repositories → `query`" in prompt
    assert "- get_issue → `owner`, `repo`, `issue_number`" in prompt
    assert "- create_pull_request → `owner`, `repo`, `title`, `head`, `base`, `body`" not in prompt


def test_build_system_prompt_groups_github_tools_compactly():
    prompt = build_system_prompt([
        _tool("search_repositories", "Search repos."),
        _tool("github_extra_tool", "Extra GH tool."),
    ])
    assert "GitHub MCP tools available:" in prompt
    assert "search_repositories" in prompt
    assert "github_extra_tool" in prompt

