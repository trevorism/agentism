from __future__ import annotations

from pathlib import Path

from tools.code_search import search_local_code
from tools.discovery_filters import should_ignore_relative_path
from tools.file_tool import list_repo_files


def test_should_ignore_relative_path_common_noise_files():
    assert should_ignore_relative_path(Path(".git/config"))
    assert should_ignore_relative_path(Path("uv.lock"))
    assert should_ignore_relative_path(Path("web/app.min.js"))
    assert should_ignore_relative_path(Path("assets/logo.png"))

    assert not should_ignore_relative_path(Path("src/main.py"))
    assert not should_ignore_relative_path(Path("src/Feature.groovy"))
    assert not should_ignore_relative_path(Path("web/index.ts"))
    assert not should_ignore_relative_path(Path("app/Service.cs"))
    assert not should_ignore_relative_path(Path("pyproject.toml"))
    assert should_ignore_relative_path(Path("notes/todo.txt"))


def test_list_repo_files_excludes_noise_files(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("lockdata", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "bundle.min.js").write_text("var x=1;", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "logo.png").write_bytes(b"png")

    output = list_repo_files.invoke({
        "repo_name": str(tmp_path),
        "pattern": "**/*",
    })
    normalized = output.replace("\\", "/")

    assert "src/main.py" in normalized
    assert "uv.lock" not in normalized
    assert "bundle.min.js" not in normalized
    assert "logo.png" not in normalized


def test_search_local_code_fallback_excludes_lock_files(tmp_path: Path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# TODO: keep\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("TODO: ignore\n", encoding="utf-8")

    monkeypatch.setattr("tools.code_search._rg_available", lambda: False)

    output = search_local_code.invoke(
        {
            "pattern": "TODO",
            "repo_name": str(tmp_path),
            "file_glob": "**/*",
            "max_results": 20,
        }
    )
    normalized = output.replace("\\", "/")

    assert "src/main.py" in normalized
    assert "uv.lock" not in normalized



