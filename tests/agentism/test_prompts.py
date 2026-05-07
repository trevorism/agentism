from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentism.prompts import BASE_SYSTEM_PROMPT, build_system_prompt, issue_ref_to_prompt, load_knowledge


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


def test_base_system_prompt_requires_autonomous_repo_reads_and_tool_chaining():
    assert "NEVER narrate intended repo reads or tool use as a question or status update" in BASE_SYSTEM_PROMPT
    assert "Immediately call read_repo_overview" in BASE_SYSTEM_PROMPT
    assert "immediately chain read_file_in_repo calls" in BASE_SYSTEM_PROMPT
    assert "do NOT ask the user for permission" in BASE_SYSTEM_PROMPT
    assert 'NEVER stop after saying "I will inspect/read/look at ..."' in BASE_SYSTEM_PROMPT


def test_base_system_prompt_defers_domain_knowledge_to_knowledge_section():
    # Domain content should NOT be hardcoded in BASE; it belongs in knowledge files.
    assert "Groovy/Micronaut backend" not in BASE_SYSTEM_PROMPT
    assert "Prefer Groovy idioms" not in BASE_SYSTEM_PROMPT
    # BASE should reference the Platform knowledge section instead.
    assert "Platform knowledge" in BASE_SYSTEM_PROMPT


def test_base_system_prompt_platform_api_tool_chain_is_a_critical_rule():
    # Calling platform APIs is a behavioral constraint, not just a convention.
    assert "get_platform_api_spec" in BASE_SYSTEM_PROMPT
    assert "get_platform_token" in BASE_SYSTEM_PROMPT


def test_base_system_prompt_workflow_references_knowledge_for_conventions():
    # Workflow steps should delegate naming/format details to knowledge files, not re-specify them.
    assert "Platform knowledge" in BASE_SYSTEM_PROMPT


def test_issue_ref_to_prompt_requires_repo_overview_without_permission_prompt():
    prompt = issue_ref_to_prompt("owner/repo#42")

    assert "get_issue" in prompt
    assert "read_repo_overview" in prompt
    assert "read_file_in_repo" in prompt
    assert "without asking for permission" in prompt


def test_load_knowledge_returns_empty_when_no_directory(tmp_path):
    import agentism.prompts as prompts_mod
    with patch.object(prompts_mod, "_KNOWLEDGE_DIR", tmp_path / "missing"):
        result = load_knowledge()
    assert result == ""


def test_load_knowledge_reads_and_joins_markdown_files(tmp_path):
    (tmp_path / "aaa.md").write_text("# Alpha\n\nAlpha content.", encoding="utf-8")
    (tmp_path / "zzz.md").write_text("# Zeta\n\nZeta content.", encoding="utf-8")

    import agentism.prompts as prompts_mod
    with patch.object(prompts_mod, "_KNOWLEDGE_DIR", tmp_path):
        result = load_knowledge()

    assert "Alpha content." in result
    assert "Zeta content." in result
    # Alpha file sorts before Zeta
    assert result.index("Alpha content.") < result.index("Zeta content.")


def test_load_knowledge_skips_empty_files(tmp_path):
    (tmp_path / "empty.md").write_text("   \n", encoding="utf-8")
    (tmp_path / "real.md").write_text("# Real\n\nReal content.", encoding="utf-8")

    import agentism.prompts as prompts_mod
    with patch.object(prompts_mod, "_KNOWLEDGE_DIR", tmp_path):
        result = load_knowledge()

    assert "Real content." in result
    assert "---" not in result  # no separator when only one non-empty file


def test_build_system_prompt_injects_knowledge(tmp_path):
    (tmp_path / "custom.md").write_text("# Custom rules\n\nAlways use frobnicate().", encoding="utf-8")

    import agentism.prompts as prompts_mod
    with patch.object(prompts_mod, "_KNOWLEDGE_DIR", tmp_path):
        prompt = build_system_prompt([])

    assert "## Platform knowledge" in prompt
    assert "Always use frobnicate()." in prompt


def test_build_system_prompt_skips_knowledge_section_when_empty(tmp_path):
    import agentism.prompts as prompts_mod
    with patch.object(prompts_mod, "_KNOWLEDGE_DIR", tmp_path / "nonexistent"):
        prompt = build_system_prompt([])

    assert "## Platform knowledge" not in prompt


def test_real_knowledge_files_are_loaded():
    """Verify the shipped knowledge files are present and non-empty."""
    content = load_knowledge()
    assert "Groovy" in content
    assert "API" in content or "api" in content
    assert "platform-overview" in content.lower() or "Technology stack" in content


