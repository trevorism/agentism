from __future__ import annotations

import sys
from types import SimpleNamespace

from tools.git_tool import git_clone, git_create_branch, git_sync_master


def test_git_clone_uses_existing_workspace(monkeypatch, tmp_path):
    workspace_repo = tmp_path / "demo"
    workspace_repo.mkdir(parents=True)

    monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr("tools.git_tool.find_repo", lambda name: None)

    result = git_clone.func("https://github.com/acme/demo.git")

    assert "Found existing checkout" in result
    assert "demo" in result


def test_git_create_branch_rejects_protected_name_without_git_calls(monkeypatch):
    fake_git = SimpleNamespace(Repo=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("should not be called")))
    monkeypatch.setitem(__import__("sys").modules, "git", fake_git)

    result = git_create_branch.func("repo", "master")

    assert "protected branch name" in result


def test_git_sync_master_success(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    class FakeGit:
        def checkout(self, branch: str):
            calls.append(("checkout", branch))

    class FakeOrigin:
        def pull(self):
            calls.append(("pull", None))

    fake_repo = SimpleNamespace(git=FakeGit(), remotes=SimpleNamespace(origin=FakeOrigin()))
    fake_git = SimpleNamespace(Repo=lambda *_args, **_kwargs: fake_repo)

    monkeypatch.setitem(sys.modules, "git", fake_git)
    monkeypatch.setattr("tools.git_tool._repo_path", lambda repo_name: repo_name)

    result = git_sync_master.func("repo")

    assert "Checked out 'master'" in result
    assert calls == [("checkout", "master"), ("pull", None)]
