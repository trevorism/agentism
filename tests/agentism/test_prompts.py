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


def test_build_system_prompt_includes_local_tool_parameter_contracts():
    def create_file_tool(repo_name, relative_path, content):
        return "ok"

    tool = SimpleNamespace(name="create_file", description="Create file.", func=create_file_tool)

    prompt = build_system_prompt([tool])

    assert "## Local tool parameter names (exact — include all required kwargs)" in prompt
    assert "- create_file → required: `repo_name`, `relative_path`, `content`" in prompt


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


def test_base_system_prompt_references_platform_crud_decision_rules():
    # Keep BASE concise and delegate detailed CLI-vs-API flow to knowledge.
    assert "platform CRUD operations" in BASE_SYSTEM_PROMPT
    assert "prefer PowerShell CLI cmdlets" in BASE_SYSTEM_PROMPT


def test_base_system_prompt_requires_exact_tool_names():
    assert "NEVER invent tool names or parameters" in BASE_SYSTEM_PROMPT
    assert "supply every required parameter exactly as listed" in BASE_SYSTEM_PROMPT
    assert "Do not mix GitHub MCP parameter names with local tool parameter names" in BASE_SYSTEM_PROMPT
    assert "`list_repo_files` uses `repo_name`" in BASE_SYSTEM_PROMPT
    assert "`search_local_code` requires `repo_name`" in BASE_SYSTEM_PROMPT
    assert "list_repo_files" in BASE_SYSTEM_PROMPT
    assert "list_files_in_repo" in BASE_SYSTEM_PROMPT


def test_base_system_prompt_workflow_references_knowledge_for_conventions():
    # Workflow steps should delegate naming/format details to knowledge files, not re-specify them.
    assert "Platform knowledge" in BASE_SYSTEM_PROMPT


def test_base_system_prompt_has_read_only_intent_mode():
    assert "Intent handling" in BASE_SYSTEM_PROMPT
    assert "read-only mode" in BASE_SYSTEM_PROMPT
    assert "Only enter implementation mode" in BASE_SYSTEM_PROMPT


def test_base_system_prompt_blocks_mutating_tools_in_read_only_mode():
    assert "NEVER call mutating tools" in BASE_SYSTEM_PROMPT
    assert "`create_file`" in BASE_SYSTEM_PROMPT
    assert "`write_file_in_repo`" in BASE_SYSTEM_PROMPT
    assert "`git_create_branch`" in BASE_SYSTEM_PROMPT
    assert "`git_commit_and_push`" in BASE_SYSTEM_PROMPT
    assert "`create_pull_request`" in BASE_SYSTEM_PROMPT


def test_code_change_workflow_is_scoped_to_implementation_mode():
    assert "Apply this workflow only in implementation mode" in BASE_SYSTEM_PROMPT
    assert "In implementation mode, NEVER push directly to master" in BASE_SYSTEM_PROMPT


def test_issue_ref_to_prompt_requires_repo_overview_without_permission_prompt():
    prompt = issue_ref_to_prompt("owner/repo#42")

    assert "get_issue" in prompt
    assert "read_repo_overview" in prompt
    assert "read_file_in_repo" in prompt
    assert "exact tool names" in prompt
    assert "list_repo_files" in prompt
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


def test_load_knowledge_can_filter_by_allowlist(tmp_path):
    (tmp_path / "alpha.md").write_text("# Alpha\n\nAlpha content.", encoding="utf-8")
    (tmp_path / "beta.md").write_text("# Beta\n\nBeta content.", encoding="utf-8")

    import agentism.prompts as prompts_mod
    with patch.object(prompts_mod, "_KNOWLEDGE_DIR", tmp_path):
        result = load_knowledge({"alpha"})

    assert "Alpha content." in result
    assert "Beta content." not in result


def test_build_system_prompt_injects_knowledge(tmp_path):
    (tmp_path / "custom.md").write_text("# Custom rules\n\nAlways use frobnicate().", encoding="utf-8")

    import agentism.prompts as prompts_mod
    with patch.object(prompts_mod, "_KNOWLEDGE_DIR", tmp_path):
        prompt = build_system_prompt([])

    assert "## Platform knowledge" in prompt
    assert "Always use frobnicate()." in prompt


def test_build_system_prompt_honors_env_knowledge_filter(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("# A\n\nA rule.", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\nB rule.", encoding="utf-8")

    import agentism.prompts as prompts_mod
    monkeypatch.setenv("AGENT_KNOWLEDGE_FILES", "b")
    with patch.object(prompts_mod, "_KNOWLEDGE_DIR", tmp_path):
        prompt = build_system_prompt([])

    assert "B rule." in prompt
    assert "A rule." not in prompt


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
    assert "CLI preference" in content or "cli preference" in content
    assert "platform-overview" in content.lower() or "Technology stack" in content


def test_build_system_prompt_restricts_param_hints_to_high_risk_tools():
    """Only high-risk tools should show required parameter hints."""
    def create_file_tool(repo_name, relative_path, content):
        return "ok"

    def list_repo_files_tool(repo_name, recursive=True):
        return "files"

    def custom_tool(some_param):
        return "custom"

    def search_local_code_tool(pattern, repo_name, file_glob="**/*", max_results=50):
        return "match"

    tools = [
        SimpleNamespace(name="create_file", description="Create file.", func=create_file_tool),
        SimpleNamespace(name="list_repo_files", description="List files.", func=list_repo_files_tool),
        SimpleNamespace(name="search_local_code", description="Search local code.", func=search_local_code_tool),
        SimpleNamespace(name="custom_non_critical_tool", description="Custom tool.", func=custom_tool),
    ]

    prompt = build_system_prompt(tools)

    # High-risk tools should have parameter hints
    assert "- create_file → required: `repo_name`, `relative_path`, `content`" in prompt
    assert "- list_repo_files → required: `repo_name`" in prompt
    assert "- search_local_code → required: `pattern`, `repo_name`" in prompt

    # Non-high-risk tools should NOT have parameter hints shown
    assert "custom_non_critical_tool" not in prompt.split("## Local tool parameter names")[1] if "## Local tool parameter names" in prompt else True


def test_base_system_prompt_prefers_run_in_terminal_over_run_powershell():
    """Prompt should guide model towards run_in_terminal for consistency."""
    assert "Prefer `run_in_terminal` over `run_powershell`" in BASE_SYSTEM_PROMPT
    assert "they are aliases" in BASE_SYSTEM_PROMPT


def test_base_system_prompt_handles_not_found_errors_explicitly():
    """Prompt should provide specific recovery guidance for Not Found errors."""
    assert "Not Found" in BASE_SYSTEM_PROMPT
    assert "report clearly to the user which resource was not found" in BASE_SYSTEM_PROMPT
    assert "NEVER respond to a Not Found error with" in BASE_SYSTEM_PROMPT
    assert "search_repositories or search_issues" in BASE_SYSTEM_PROMPT


def test_base_system_prompt_handles_tool_invocation_kwarg_errors_with_retry():
    assert "ToolInvocationError" in BASE_SYSTEM_PROMPT
    assert "missing/invalid kwargs" in BASE_SYSTEM_PROMPT
    assert "immediately retry the same tool" in BASE_SYSTEM_PROMPT


def test_issue_ref_to_prompt_includes_not_found_fallback():
    """Issue prompt should instruct agent to search if resource is not found."""
    prompt = issue_ref_to_prompt("owner/repo#42")
    assert "Not Found" in prompt
    assert "search_issues" in prompt
    assert "search_repositories" in prompt

