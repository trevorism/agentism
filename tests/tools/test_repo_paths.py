from __future__ import annotations

from pathlib import Path

from tools import repo_paths


def test_find_repo_supports_nested_directories(tmp_path: Path, monkeypatch):
    nested_repo = tmp_path / "org" / "team" / "deep-repo"
    nested_repo.mkdir(parents=True)

    monkeypatch.setattr(repo_paths, "DEV_DIR", tmp_path)

    found = repo_paths.find_repo("deep-repo")

    assert found == nested_repo


def test_repo_path_falls_back_to_workspace_when_not_found(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)

    monkeypatch.setattr(repo_paths, "DEV_DIR", tmp_path / "dev")
    monkeypatch.setattr(repo_paths, "WORKSPACE_DIR", workspace)

    resolved = repo_paths.repo_path("missing-repo")

    assert resolved == workspace / "missing-repo"

