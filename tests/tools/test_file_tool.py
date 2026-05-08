from __future__ import annotations

from pathlib import Path

from tools.file_tool import create_file, list_repo_files, read_file_in_repo, write_file_in_repo


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


def test_list_repo_files_recurses_by_default(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    (repo_dir / "src" / "nested").mkdir(parents=True)
    (repo_dir / "src" / "nested" / "main.py").write_text("print('ok')\n", encoding="utf-8")

    output = list_repo_files.func(str(repo_dir))

    assert "src/nested/main.py" in output.replace("\\", "/")


def test_list_repo_files_can_disable_recursion(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    (repo_dir / "src" / "nested").mkdir(parents=True)
    (repo_dir / "src" / "nested" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (repo_dir / "top.py").write_text("print('top')\n", encoding="utf-8")

    output = list_repo_files.func(str(repo_dir), recursive=False)

    normalized = output.replace("\\", "/")
    assert "top.py" in normalized
    assert "src/nested/main.py" not in normalized


def test_list_repo_files_truncates_large_results(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    (repo_dir / "src").mkdir(parents=True)
    for idx in range(3):
        (repo_dir / "src" / f"f{idx}.py").write_text("pass\n", encoding="utf-8")

    output = list_repo_files.func(str(repo_dir), max_results=2)

    lines = output.splitlines()
    assert len(lines) == 3
    assert lines[-1].startswith("... truncated at 2 files")


def test_list_repo_files_does_not_mark_truncated_when_exact_limit(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    (repo_dir / "src").mkdir(parents=True)
    for idx in range(2):
        (repo_dir / "src" / f"f{idx}.py").write_text("pass\n", encoding="utf-8")

    output = list_repo_files.func(str(repo_dir), max_results=2)

    assert "truncated at" not in output


