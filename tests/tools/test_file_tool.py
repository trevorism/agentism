from __future__ import annotations

from pathlib import Path

from tools.file_tool import create_file, read_file_in_repo, write_file_in_repo


def test_create_file_creates_new_file(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    result = create_file.func(str(repo_dir), "src/new_file.py", "print('ok')\n")

    assert "Created:" in result
    assert (repo_dir / "src" / "new_file.py").read_text(encoding="utf-8") == "print('ok')\n"


def test_create_file_rejects_existing_file(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    existing = repo_dir / "src" / "exists.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("old\n", encoding="utf-8")

    result = create_file.func(str(repo_dir), "src/exists.py", "new\n")

    assert "Error: file already exists" in result
    assert existing.read_text(encoding="utf-8") == "old\n"


def test_create_file_respects_dry_run(tmp_path: Path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    monkeypatch.setattr("tools.file_tool.config.DRY_RUN", True)
    try:
        result = create_file.func(str(repo_dir), "dry/file.py", "print('dry')\n")
    finally:
        monkeypatch.setattr("tools.file_tool.config.DRY_RUN", False)

    assert "[DRY-RUN] Would create file" in result
    assert not (repo_dir / "dry" / "file.py").exists()


def test_read_file_in_repo_returns_contents(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    file_path = repo_dir / "src" / "main.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("print('read')\n", encoding="utf-8")

    result = read_file_in_repo.func(str(repo_dir), "src/main.py")

    assert result == "print('read')\n"


def test_write_file_in_repo_overwrites_contents(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    target = repo_dir / "src" / "data.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"old": true}', encoding="utf-8")

    result = write_file_in_repo.func(str(repo_dir), "src/data.json", '{"new": true}')

    assert "Written:" in result
    assert target.read_text(encoding="utf-8") == '{"new": true}'



