import argparse

from agentism.cli import startup_plan


def test_startup_plan_batch_issues_requires_autonomous_repo_inspection():
    args = argparse.Namespace(
        issues="owner/repo",
        label="agent-ready",
        issue=None,
        session="main",
        dry_run=False,
        debug=False,
        chunk_timeout=1200.0,
    )

    initial_prompt, batch_issues = startup_plan(args, issue_prompt_fn=lambda ref: f"ISSUE:{ref}")

    assert initial_prompt == ""
    assert batch_issues is not None
    assert len(batch_issues) == 1
    assert "read_repo_overview" in batch_issues[0]
    assert "read_file_in_repo" in batch_issues[0]
    assert "without asking the user first" in batch_issues[0]


def test_startup_plan_issue_uses_issue_prompt_function():
    args = argparse.Namespace(
        issues=None,
        label="agent-ready",
        issue="owner/repo#7",
        session="main",
        dry_run=False,
        debug=False,
        chunk_timeout=1200.0,
    )

    initial_prompt, batch_issues = startup_plan(args, issue_prompt_fn=lambda ref: f"ISSUE:{ref}")

    assert initial_prompt == "ISSUE:owner/repo#7"
    assert batch_issues is None

