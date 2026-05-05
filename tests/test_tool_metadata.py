from types import SimpleNamespace

from tool_metadata import (
    GITHUB_PARAMETER_HINTS,
    is_github_tool_name,
    iter_tool_metadata,
    render_tool_table_rows,
    unique_sorted_tool_metadata,
)


def _tool(name: str, description: str = ""):
    return SimpleNamespace(name=name, description=description)


def test_iter_tool_metadata_preserves_order_and_duplicates():
    items = iter_tool_metadata([
        _tool("zeta_tool", "Zeta description."),
        _tool("alpha_tool", "Alpha description."),
        _tool("alpha_tool", "Duplicate alpha description."),
    ])
    assert [item.name for item in items] == ["zeta_tool", "alpha_tool", "alpha_tool"]


def test_render_tool_table_rows_preserves_order_and_numbers_rows():
    rows = render_tool_table_rows([
        _tool("zeta_tool", "Zeta description."),
        _tool("alpha_tool", "Alpha description."),
    ])
    assert rows == [
        ("1", "zeta_tool", "Zeta description."),
        ("2", "alpha_tool", "Alpha description."),
    ]


def test_render_tool_table_rows_truncates_description_to_100_chars():
    long_description = "x" * 150
    rows = render_tool_table_rows([_tool("long_tool", long_description)])
    assert rows == [("1", "long_tool", "x" * 100)]


def test_unique_sorted_tool_metadata_deduplicates_and_sorts():
    items = unique_sorted_tool_metadata([
        _tool("zeta_tool", "Zeta description."),
        _tool("alpha_tool", "Alpha description."),
        _tool("alpha_tool", "Duplicate alpha description."),
    ])
    assert [item.name for item in items] == ["alpha_tool", "zeta_tool"]
    assert items[0].description == "Alpha description."


def test_is_github_tool_name_uses_curated_hints_and_prefix():
    assert is_github_tool_name("search_repositories") is True
    assert is_github_tool_name("github_extra_tool") is True
    assert is_github_tool_name("local_tool") is False


def test_curated_github_hints_are_available_for_prompt_builder():
    assert GITHUB_PARAMETER_HINTS["get_issue"] == ["owner", "repo", "issue_number"]

