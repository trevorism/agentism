"""Legacy reference tests kept for migration context; excluded from default pytest discovery."""
from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# config.py
# ──────────────────────────────────────────────────────────────────────────────

class TestConfig:
    """Tests for config.py helpers."""

    def test_required_returns_value_when_set(self, monkeypatch):
        from config import _required
        monkeypatch.setenv("TEST_REQ_VAR", "hello")
        assert _required("TEST_REQ_VAR") == "hello"

    def test_required_exits_when_missing(self, monkeypatch):
        from config import _required
        monkeypatch.delenv("TEST_REQ_MISSING", raising=False)
        with pytest.raises(SystemExit):
            _required("TEST_REQ_MISSING")

    def test_optional_returns_default_when_missing(self, monkeypatch):
        from config import _optional
        monkeypatch.delenv("TEST_OPT_VAR", raising=False)
        assert _optional("TEST_OPT_VAR", "default") == "default"

    def test_optional_returns_value_when_set(self, monkeypatch):
        from config import _optional
        monkeypatch.setenv("TEST_OPT_VAR", "value")
        assert _optional("TEST_OPT_VAR", "default") == "value"

    def test_path_returns_path_object(self, monkeypatch, tmp_path):
        from config import _path
        monkeypatch.setenv("TEST_PATH_VAR", str(tmp_path))
        result = _path("TEST_PATH_VAR", "./default")
        assert isinstance(result, Path)
        assert result == tmp_path

    def test_path_returns_default_when_missing(self, monkeypatch, tmp_path):
        from config import _path
        monkeypatch.delenv("TEST_PATH_DEFAULT", raising=False)
        result = _path("TEST_PATH_DEFAULT", str(tmp_path / "default"))
        assert result == tmp_path / "default"


# ──────────────────────────────────────────────────────────────────────────────
# state.py
# ──────────────────────────────────────────────────────────────────────────────

class TestState:
    """Tests for state.py helpers."""

    def test_clean_response_removes_think_blocks(self):
        from state import clean_response
        text = "Hello <think>thinking</think> world"
        assert clean_response(text) == "Hello  world"

    def test_clean_response_removes_multiline_think_blocks(self):
        from state import clean_response
        text = "Hello <think>\nline1\nline2\n</think> world"
        assert clean_response(text) == "Hello  world"

    def test_clean_response_normalises_whitespace(self):
        from state import clean_response
        text = "  Hello   world  "
        assert clean_response(text) == "Hello   world"

    def test_token_usage_total(self):
        from state import TokenUsage
        tu = TokenUsage(input_tokens=10, output_tokens=20)
        assert tu.total == 30

    def test_token_usage_add(self):
        from state import TokenUsage
        tu1 = TokenUsage(input_tokens=10, output_tokens=20)
        tu2 = TokenUsage(input_tokens=30, output_tokens=40)
        tu1.add(tu2)
        assert tu1.input_tokens == 40
        assert tu1.output_tokens == 60

    def test_agent_state_defaults(self):
        from state import AgentState
        state = AgentState(thread_id="t1", model="qwen3", agent=MagicMock())
        assert state.session_history == []
        assert state.session_tokens.input_tokens == 0
        assert state.session_tokens.output_tokens == 0
        assert state.last_user_input == ""


# ──────────────────────────────────────────────────────────────────────────────
# tools/git_tool.py
# ──────────────────────────────────────────────────────────────────────────────

class TestGitTool:
    """Tests for tools/git_tool.py."""

    def test_find_repo_returns_none_when_dev_dir_missing(self, monkeypatch):
        from tools.git_tool import _find_repo
        monkeypatch.setattr("tools.git_tool.DEV_DIR", Path("/nonexistent"))
        assert _find_repo("my-repo") is None

    def test_find_repo_finds_at_level_1(self, monkeypatch, tmp_path):
        from tools.git_tool import _find_repo
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        (dev_dir / "my-repo").mkdir()
        monkeypatch.setattr("tools.git_tool.DEV_DIR", dev_dir)
        result = _find_repo("my-repo")
        assert result == dev_dir / "my-repo"

    def test_find_repo_finds_at_level_2(self, monkeypatch, tmp_path):
        from tools.git_tool import _find_repo
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        subdir = dev_dir / "sub"
        subdir.mkdir()
        (subdir / "my-repo").mkdir()
        monkeypatch.setattr("tools.git_tool.DEV_DIR", dev_dir)
        result = _find_repo("my-repo")
        assert result == subdir / "my-repo"

    def test_repo_path_uses_absolute_path_as_is(self):
        from tools.git_tool import _repo_path
        result = _repo_path("/absolute/path")
        assert result == Path("/absolute/path")

    def test_repo_path_raises_for_dot(self):
        from tools.git_tool import _repo_path
        with pytest.raises(ValueError, match="repo_name must be"):
            _repo_path(".")

    def test_repo_path_raises_for_empty(self):
        from tools.git_tool import _repo_path
        with pytest.raises(ValueError, match="repo_name must be"):
            _repo_path("")

    def test_repo_path_falls_back_to_workspace(self, monkeypatch, tmp_path):
        from tools.git_tool import _repo_path, WORKSPACE_DIR
        monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
        monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", tmp_path / "ws")
        result = _repo_path("my-repo")
        assert result == tmp_path / "ws" / "my-repo"

    def test_git_clone_skips_when_found(self, monkeypatch, tmp_path):
        from tools.git_tool import git_clone
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        (dev_dir / "my-repo").mkdir()
        monkeypatch.setattr("tools.git_tool.DEV_DIR", dev_dir)
        monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", tmp_path / "ws")
        result = git_clone.func("https://github.com/x/y.git", "my-repo")
        assert "Found existing checkout" in result

    def test_git_clone_clones_when_not_found(self, monkeypatch, tmp_path):
        from tools.git_tool import git_clone
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        monkeypatch.setattr("tools.git_tool.DEV_DIR", dev_dir)
        monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", tmp_path / "ws")
        mock_repo = MagicMock()
        mock_repo.clone_from = MagicMock()
        with patch("tools.git_tool.git.Repo", return_value=mock_repo):
            result = git_clone.func("https://github.com/x/y.git", "my-repo")
            assert "Cloned to" in result

    def test_read_file_in_repo_returns_file_contents(self, monkeypatch, tmp_path):
        from tools.git_tool import read_file_in_repo
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        file_path = repo_dir / "test.txt"
        file_path.write_text("hello")
        monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
        monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
        result = read_file_in_repo.func("repo", "test.txt")
        assert result == "hello"

    def test_read_file_in_repo_returns_error_when_missing(self, monkeypatch, tmp_path):
        from tools.git_tool import read_file_in_repo
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
        monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
        result = read_file_in_repo.func("repo", "missing.txt")
        assert "File not found" in result

    def test_list_repo_files_returns_files(self, monkeypatch, tmp_path):
        from tools.git_tool import list_repo_files
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "a.txt").touch()
        (repo_dir / "b.txt").touch()
        monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
        monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
        result = list_repo_files.func("repo")
        assert "a.txt" in result
        assert "b.txt" in result

    def test_list_repo_files_excludes_git(self, monkeypatch, tmp_path):
        from tools.git_tool import list_repo_files
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()
        (repo_dir / ".git" / "config").touch()
        (repo_dir / "a.txt").touch()
        monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
        monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
        result = list_repo_files.func("repo")
        assert ".git" not in result

    def test_write_file_in_repo_writes_file(self, monkeypatch, tmp_path):
        from tools.git_tool import write_file_in_repo
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
        monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
        result = write_file_in_repo.func("repo", "test.txt", "content")
        assert "Written:" in result
        assert (repo_dir / "test.txt").read_text() == "content"


    def test_git_status_returns_status(self, monkeypatch, tmp_path):
        from tools.git_tool import git_status
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        mock_repo = MagicMock()
        mock_repo.active_branch.name = "master"
        mock_repo.index.diff = MagicMock(return_value=[])
        mock_repo.untracked_files = []
        mock_repo.head.is_valid = MagicMock(return_value=True)
        with patch("tools.git_tool.git.Repo", return_value=mock_repo):
            monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
            monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
            result = git_status.func("repo")
            assert "Branch:" in result

    def test_git_create_branch_creates_branch(self, monkeypatch, tmp_path):
        from tools.git_tool import git_create_branch
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        mock_repo = MagicMock()
        mock_repo.create_head = MagicMock()
        mock_repo.remotes.origin.pull = MagicMock()
        with patch("tools.git_tool.git.Repo", return_value=mock_repo):
            monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
            monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
            result = git_create_branch.func("repo", "feature/test")
            assert "Created and checked out" in result

    def test_git_create_branch_rejects_protected_branch(self, monkeypatch, tmp_path):
        from tools.git_tool import git_create_branch
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
        monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
        result = git_create_branch.func("repo", "master")
        assert "protected branch" in result

    def test_git_commit_and_push_commits(self, monkeypatch, tmp_path):
        from tools.git_tool import git_commit_and_push
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        mock_repo = MagicMock()
        mock_repo.active_branch.name = "feature/test"
        mock_repo.index.diff = MagicMock(return_value=MagicMock())
        mock_repo.untracked_files = []
        mock_repo.index.commit = MagicMock(return_value=MagicMock(hexsha="abc123"))
        mock_origin = MagicMock()
        mock_repo.remote = MagicMock(return_value=mock_origin)
        with patch("tools.git_tool.git.Repo", return_value=mock_repo):
            monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
            monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
            result = git_commit_and_push.func("repo", "test commit")
            assert "Committed" in result

    def test_git_commit_and_push_rejects_protected_branch(self, monkeypatch, tmp_path):
        from tools.git_tool import git_commit_and_push
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        mock_repo = MagicMock()
        mock_repo.active_branch.name = "master"
        with patch("tools.git_tool.git.Repo", return_value=mock_repo):
            monkeypatch.setattr("tools.git_tool.DEV_DIR", tmp_path / "dev")
            monkeypatch.setattr("tools.git_tool.WORKSPACE_DIR", repo_dir)
            result = git_commit_and_push.func("repo", "test commit")
            assert "protected branch" in result


# ──────────────────────────────────────────────────────────────────────────────
# tools/web_tool.py
# ──────────────────────────────────────────────────────────────────────────────

class TestWebTool:
    """Tests for tools/web_tool.py."""

    def test_acquire_token_calls_pwsh(self, monkeypatch):
        from tools.web_tool import _acquire_token
        mock_run = MagicMock(return_value=MagicMock(stdout="token123", returncode=0, stderr=""))
        monkeypatch.setattr("tools.web_tool.subprocess.run", mock_run)
        result = _acquire_token()
        assert result == "token123"

    def test_acquire_token_raises_on_failure(self, monkeypatch):
        from tools.web_tool import _acquire_token
        mock_run = MagicMock(return_value=MagicMock(stdout="", returncode=1, stderr="error"))
        monkeypatch.setattr("tools.web_tool.subprocess.run", mock_run)
        with pytest.raises(RuntimeError):
            _acquire_token()

    def test_get_token_returns_cached_token(self, monkeypatch):
        from tools.web_tool import _get_token, _TOKEN_CACHE
        _TOKEN_CACHE["token"] = "cached"
        _TOKEN_CACHE["expires_at"] = 9999999999.0
        result = _get_token()
        assert result == "cached"

    def test_get_token_refreshes_when_expired(self, monkeypatch):
        from tools.web_tool import _get_token, _TOKEN_CACHE
        _TOKEN_CACHE["token"] = "old"
        _TOKEN_CACHE["expires_at"] = 0.0
        mock_acquire = MagicMock(return_value="new")
        monkeypatch.setattr("tools.web_tool", "_acquire_token", mock_acquire)
        result = _get_token()
        assert result == "new"
        mock_acquire.assert_called_once()

    def test_auth_headers_includes_token(self, monkeypatch):
        from tools.web_tool import _auth_headers, _get_token
        mock_get_token = MagicMock(return_value="token123")
        monkeypatch.setattr("tools.web_tool", "_get_token", mock_get_token)
        headers = _auth_headers()
        assert headers["Authorization"] == "Bearer token123"

    def test_get_platform_token_returns_token(self, monkeypatch):
        from tools.web_tool import get_platform_token
        mock_get_token = MagicMock(return_value="token123")
        monkeypatch.setattr("tools.web_tool", "_get_token", mock_get_token)
        result = get_platform_token.func()
        assert result == "token123"

    def test_get_platform_token_returns_error_on_failure(self, monkeypatch):
        from tools.web_tool import get_platform_token
        mock_get_token = MagicMock(side_effect=RuntimeError("fail"))
        monkeypatch.setattr("tools.web_tool", "_get_token", mock_get_token)
        result = get_platform_token.func()
        assert "Token error" in result

    def test_fetch_url_fetches_url(self, monkeypatch):
        from tools.web_tool import fetch_url
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "body"
        mock_resp.raise_for_status = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=mock_resp)
        with patch("tools.web_tool.httpx.Client", return_value=mock_client):
            result = fetch_url.func("https://example.com")
            assert result == "body"

    def test_fetch_url_returns_error_on_http_error(self, monkeypatch):
        from tools.web_tool import fetch_url
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "not found"
        http_error = MagicMock()
        http_error.response = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(side_effect=http_error)
        with patch("tools.web_tool.httpx.Client", return_value=mock_client):
            result = fetch_url.func("https://example.com")
            assert "HTTP 404" in result

    def test_post_platform_api_posts_json(self, monkeypatch):
        from tools.web_tool import post_platform_api
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "response"
        mock_resp.raise_for_status = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=mock_resp)
        with patch("tools.web_tool.httpx.Client", return_value=mock_client):
            result = post_platform_api.func("/api/test", '{"key":"value"}')
            assert result == "response"

    def test_post_platform_api_returns_error_on_invalid_json(self, monkeypatch):
        from tools.web_tool import post_platform_api
        result = post_platform_api.func("/api/test", "invalid json")
        assert "Invalid JSON" in result

    def test_get_platform_api_spec_returns_cached_spec(self, monkeypatch):
        from tools.web_tool import get_platform_api_spec, _SPEC_CACHE
        _SPEC_CACHE["https://example.com"] = "cached spec"
        result = get_platform_api.func("https://example.com")
        assert "[cached]" in result

    def test_get_platform_api_spec_fetches_spec(self, monkeypatch):
        from tools.web_tool import get_platform_api_spec
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "spec"
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=mock_resp)
        with patch("tools.web_tool.httpx.Client", return_value=mock_client):
            result = get_platform_api.func("https://example.com")
            assert "# Spec from" in result


# ──────────────────────────────────────────────────────────────────────────────
# tools/health.py
# ──────────────────────────────────────────────────────────────────────────────

class TestHealth:
    """Tests for tools/health.py."""

    def test_health_check_dataclass(self):
        from tools.health import HealthCheck
        hc = HealthCheck(name="Test", status="OK", details="details")
        assert hc.name == "Test"
        assert hc.status == "OK"
        assert hc.details == "details"
        assert hc.remediation == ""

    def test_normalize_model_name(self):
        from tools.health import _normalize_model_name
        assert _normalize_model_name("foo:latest") == "foo"
        assert _normalize_model_name("foo") == "foo"
        assert _normalize_model_name("") == ""

    def test_check_ollama_returns_ok_when_model_found(self, monkeypatch):
        from tools.health import check_ollama
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"models": [{"name": "qwen3:latest"}]})
        mock_client = MagicMock()
        mock_client.__aenter__ = MagicMock(return_value=mock_client)
        mock_client.__aexit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr("tools.health.httpx.AsyncClient", return_value=mock_client)
        result = asyncio.get_event_loop().run_until_complete(check_ollama("qwen3"))
        assert result.status == "OK"

    def test_check_ollama_returns_warning_when_model_not_found(self, monkeypatch):
        from tools.health import check_ollama
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"models": [{"name": "other-model"}]})
        mock_client = MagicMock()
        mock_client.__aenter__ = MagicMock(return_value=mock_client)
        mock_client.__aexit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr("tools.health.httpx.AsyncClient", return_value=mock_client)
        result = asyncio.get_event_loop().run_until_complete(check_ollama("qwen3"))
        assert result.status == "Warning"

    def test_check_github_token_returns_ok_when_valid(self, monkeypatch):
        from tools.health import check_github_token
        import config
        monkeypatch.setattr(config, "GITHUB_TOKEN", "valid-token")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__aenter__ = MagicMock(return_value=mock_client)
        mock_client.__aexit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr("tools.health.httpx.AsyncClient", return_value=mock_client)
        result = asyncio.get_event_loop().run_until_complete(check_github_token())
        assert result.status == "OK"

    def test_check_github_token_returns_error_when_invalid(self, monkeypatch):
        from tools.health import check_github_token
        import config
        monkeypatch.setattr(config, "GITHUB_TOKEN", "invalid-token")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client = MagicMock()
        mock_client.__aenter__ = MagicMock(return_value=mock_client)
        mock_client.__aexit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr("tools.health.httpx.AsyncClient", return_value=mock_client)
        result = asyncio.get_event_loop().run_until_complete(check_github_token())
        assert result.status == "Error"

    def test_check_git_config_returns_ok_when_configured(self, monkeypatch):
        from tools.health import check_git_config
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("tools.health.subprocess.run", mock_run)
        result = check_git_config()
        assert result.status == "OK"

    def test_check_git_config_returns_warning_when_missing(self, monkeypatch):
        from tools.health import check_git_config
        mock_run = MagicMock(side_effect=subprocess.CalledProcessError(1, "git"))
        monkeypatch.setattr("tools.health.subprocess.run", mock_run)
        result = check_git_config()
        assert result.status == "Warning"

    def test_check_disk_space_returns_ok_when_enough_space(self, monkeypatch, tmp_path):
        from tools.health import check_disk_space
        import config
        monkeypatch.setattr(config, "DEV_DIR", tmp_path)
        monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
        mock_usage = MagicMock()
        mock_usage.free = 10 * (1024 ** 3)  # 10GB
        monkeypatch.setattr("tools.health.shutil.disk_usage", return_value=mock_usage)
        result = check_disk_space()
        assert result.status == "OK"

    def test_check_disk_space_returns_error_when_low_space(self, monkeypatch, tmp_path):
        from tools.health import check_disk_space
        import config
        monkeypatch.setattr(config, "DEV_DIR", tmp_path)
        monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
        mock_usage = MagicMock()
        mock_usage.free = 0.5 * (1024 ** 3)  # 0.5GB
        monkeypatch.setattr("tools.health.shutil.disk_usage", return_value=mock_usage)
        result = check_disk_space()
        assert result.status == "Error"

    def test_check_memory_db_returns_ok_when_accessible(self, monkeypatch, tmp_path):
        from tools.health import check_memory_db
        import config
        db_path = tmp_path / "memory.db"
        db_path.touch()
        monkeypatch.setattr(config, "MEMORY_DB", str(db_path))
        mock_db = MagicMock()
        mock_db.__aenter__ = MagicMock(return_value=mock_db)
        mock_db.__aexit__ = MagicMock(return_value=False)
        mock_db.execute = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("tools.health.aiosqlite.connect", return_value=mock_db)
        result = asyncio.get_event_loop().run_until_complete(check_memory_db())
        assert result.status == "OK"

    def test_check_pwsh_returns_ok_when_available(self, monkeypatch):
        from tools.health import check_pwsh
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="PowerShell 7.0"))
        monkeypatch.setattr("tools.health.subprocess.run", mock_run)
        result = check_pwsh()
        assert result.status == "OK"

    def test_check_node_returns_ok_when_available(self, monkeypatch):
        from tools.health import check_node
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="v18.0.0"))
        monkeypatch.setattr("tools.health.subprocess.run", mock_run)
        result = check_node()
        assert result.status == "OK"

    def test_render_health_report_returns_panel(self):
        from tools.health import render_health_report, HealthCheck
        checks = [HealthCheck("Test", "OK", "details")]
        panel = render_health_report(checks)
        assert panel is not None

    def test_run_health_checks_returns_list(self, monkeypatch):
        from tools.health import run_health_checks
        mock_check = MagicMock(return_value=MagicMock(status="OK"))
        monkeypatch.setattr("tools.health.check_ollama", mock_check)
        monkeypatch.setattr("tools.health.check_github_token", mock_check)
        monkeypatch.setattr("tools.health.check_git_config", mock_check)
        monkeypatch.setattr("tools.health.check_disk_space", mock_check)
        monkeypatch.setattr("tools.health.check_memory_db", mock_check)
        monkeypatch.setattr("tools.health.check_pwsh", mock_check)
        monkeypatch.setattr("tools.health.check_node", mock_check)
        result = asyncio.get_event_loop().run_until_complete(run_health_checks())
        assert isinstance(result, list)
        assert len(result) == 7


# ──────────────────────────────────────────────────────────────────────────────
# tools/test_runner.py
# ──────────────────────────────────────────────────────────────────────────────

class TestTestRunner:
    """Tests for tools/test_runner.py."""

    def test_repo_path_returns_absolute_path_as_is(self):
        from tools.test_runner import _repo_path
        result = _repo_path("/absolute/path")
        assert result == Path("/absolute/path")

    def test_repo_path_finds_in_dev_dir(self, monkeypatch, tmp_path):
        from tools.test_runner import _repo_path
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        (dev_dir / "my-repo").mkdir()
        monkeypatch.setattr("tools.test_runner.DEV_DIR", dev_dir)
        monkeypatch.setattr("tools.test_runner.WORKSPACE_DIR", tmp_path / "ws")
        result = _repo_path("my-repo")
        assert result == dev_dir / "my-repo"

    def test_repo_path_falls_back_to_workspace(self, monkeypatch, tmp_path):
        from tools.test_runner import _repo_path
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        monkeypatch.setattr("tools.test_runner.DEV_DIR", dev_dir)
        monkeypatch.setattr("tools.test_runner.WORKSPACE_DIR", tmp_path / "ws")
        result = _repo_path("my-repo")
        assert result == tmp_path / "ws" / "my-repo"

    def test_detect_test_commands_finds_gradle(self, tmp_path):
        from tools.test_runner import _detect_test_commands
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "build.gradle").touch()
        (repo_root / "gradlew").touch()
        suites = _detect_test_commands(repo_root)
        assert any("Groovy/Gradle" in s["label"] for s in suites)

    def test_detect_test_commands_finds_cucumber(self, tmp_path):
        from tools.test_runner import _detect_test_commands
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "build.gradle").touch()
        (repo_root / "gradlew").touch()
        (repo_root / "features").mkdir()
        (repo_root / "features" / "test.feature").touch()
        suites = _detect_test_commands(repo_root)
        assert any("Cucumber" in s["label"] for s in suites)

    def test_detect_test_commands_finds_vitest(self, tmp_path):
        from tools.test_runner import _detect_test_commands
        import json
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        pkg = {"scripts": {"test": "vitest"}}
        (repo_root / "package.json").write_text(json.dumps(pkg))
        suites = _detect_test_commands(repo_root)
        assert any("Vitest" in s["label"] for s in suites)

    def test_run_tests_returns_error_when_repo_not_found(self):
        from tools.test_runner import run_tests
        result = run_tests.func("nonexistent")
        assert "Repo not found" in result

    def test_run_tests_returns_error_when_no_test_config(self, tmp_path):
        from tools.test_runner import run_tests
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        monkeypatch = MagicMock()
        monkeypatch.setattr("tools.test_runner.DEV_DIR", tmp_path / "dev")
        monkeypatch.setattr("tools.test_runner.WORKSPACE_DIR", repo_root)
        result = run_tests.func("repo")
        assert "No recognisable test configuration" in result


# ──────────────────────────────────────────────────────────────────────────────
# tools/code_search.py
# ──────────────────────────────────────────────────────────────────────────────

class TestCodeSearch:
    """Tests for tools/code_search.py."""

    def test_rg_available_returns_true_when_rg_exists(self, monkeypatch):
        from tools.code_search import _rg_available
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("tools.code_search.subprocess.run", mock_run)
        assert _rg_available() is True

    def test_rg_available_returns_false_when_rg_missing(self, monkeypatch):
        from tools.code_search import _rg_available
        mock_run = MagicMock(side_effect=FileNotFoundError())
        monkeypatch.setattr("tools.code_search.subprocess.run", mock_run)
        assert _rg_available() is False

    def test_search_with_rg_returns_output(self, monkeypatch):
        from tools.code_search import _search_with_rg
        mock_run = MagicMock(return_value=MagicMock(stdout="match", stderr=""))
        monkeypatch.setattr("tools.code_search.subprocess.run", mock_run)
        result = _search_with_rg("pattern", Path("/tmp"), "*", 50)
        assert result == "match"

    def test_search_with_rg_returns_error_on_stderr(self, monkeypatch):
        from tools.code_search import _search_with_rg
        mock_run = MagicMock(return_value=MagicMock(stdout="", stderr="error"))
        monkeypatch.setattr("tools.code_search.subprocess.run", mock_run)
        result = _search_with_rg("pattern", Path("/tmp"), "*", 50)
        assert "ripgrep error" in result

    def test_search_python_fallback_returns_matches(self, tmp_path):
        from tools.code_search import _search_python_fallback
        search_root = tmp_path / "search"
        search_root.mkdir()
        (search_root / "test.txt").write_text("hello world")
        result = _search_python_fallback("hello", search_root, "*", 50)
        assert "test.txt" in result

    def test_search_python_fallback_returns_no_matches(self, tmp_path):
        from tools.code_search import _search_python_fallback
        search_root = tmp_path / "search"
        search_root.mkdir()
        (search_root / "test.txt").write_text("hello world")
        result = _search_python_fallback("missing", search_root, "*", 50)
        assert "No matches" in result

    def test_search_local_code_searches_single_repo(self, monkeypatch, tmp_path):
        from tools.code_search import search_local_code
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        (dev_dir / "my-repo").mkdir()
        monkeypatch.setattr("tools.code_search.DEV_DIR", dev_dir)
        monkeypatch.setattr("tools.code_search.WORKSPACE_DIR", tmp_path / "ws")
        mock_search = MagicMock(return_value="match")
        monkeypatch.setattr("tools.code_search", "_search_python_fallback", mock_search)
        result = search_local_code.func("pattern", "my-repo")
        assert mock_search.called

    def test_search_local_code_searches_all_repos(self, monkeypatch, tmp_path):
        from tools.code_search import search_local_code
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        monkeypatch.setattr("tools.code_search.DEV_DIR", dev_dir)
        mock_search = MagicMock(return_value="match")
        monkeypatch.setattr("tools.code_search", "_search_python_fallback", mock_search)
        result = search_local_code.func("pattern")
        assert mock_search.called


# ──────────────────────────────────────────────────────────────────────────────
# tools/shell.py
# ──────────────────────────────────────────────────────────────────────────────

class TestShell:
    """Tests for tools/shell.py."""

    def test_run_powershell_runs_command(self, monkeypatch):
        from tools.shell import run_powershell
        mock_run = MagicMock(return_value=MagicMock(stdout="output", stderr=""))
        monkeypatch.setattr("tools.shell.subprocess.run", mock_run)
        result = run_powershell.func("echo hello")
        assert result == "output"

    def test_run_powershell_returns_error_on_stderr(self, monkeypatch):
        from tools.shell import run_powershell
        mock_run = MagicMock(return_value=MagicMock(stdout="output", stderr="error"))
        monkeypatch.setattr("tools.shell.subprocess.run", mock_run)
        result = run_powershell.func("echo hello")
        assert "STDERR" in result

    def test_list_available_modules_returns_modules(self, monkeypatch, tmp_path):
        from tools.shell import list_available_modules
        import config
        monkeypatch.setattr(config, "PS_MODULE_PATH", str(tmp_path))
        (tmp_path / "module1").mkdir()
        (tmp_path / "module2.psm1").touch()
        result = list_available_modules.func()
        assert "module1" in result
        assert "module2.psm1" in result

    def test_list_available_modules_returns_error_when_path_missing(self, monkeypatch, tmp_path):
        from tools.shell import list_available_modules
        import config
        monkeypatch.setattr(config, "PS_MODULE_PATH", str(tmp_path / "nonexistent"))
        result = list_available_modules.func()
        assert "Module path not found" in result


# ──────────────────────────────────────────────────────────────────────────────
# tools/__init__.py
# ──────────────────────────────────────────────────────────────────────────────

class TestToolsInit:
    """Tests for tools/__init__.py."""

    def test_load_tool_module_imports_successfully(self, monkeypatch):
        from tools import _load_tool_module
        mock_mod = MagicMock()
        mock_mod.run_powershell = MagicMock()
        monkeypatch.setattr("importlib.import_module", return_value=mock_mod)
        result = _load_tool_module("shell", "run_powershell")
        assert result == mock_mod.run_powershell

    def test_load_tool_module_raises_on_failure(self, monkeypatch):
        from tools import _load_tool_module
        monkeypatch.setattr("importlib.import_module", side_effect=ImportError("fail"))
        with pytest.raises(ImportError):
            _load_tool_module("shell", "run_powershell")

    def test_local_tools_is_list(self):
        from tools import LOCAL_TOOLS
        assert isinstance(LOCAL_TOOLS, list)


# ──────────────────────────────────────────────────────────────────────────────
# agent.py
# ──────────────────────────────────────────────────────────────────────────────

class TestAgent:
    """Tests for agent.py."""

    def test_build_agent_creates_agent(self, monkeypatch):
        from agent import build_agent
        mock_agent = MagicMock()
        mock_build_local = MagicMock(return_value=[])
        mock_build_github = MagicMock(return_value=[])
        mock_chat = MagicMock()
        mock_chat.bind_tools = MagicMock(return_value=mock_chat)
        mock_chat_with_checkpointer = MagicMock(return_value=mock_agent)
        monkeypatch.setattr("agent.ChatOllama", mock_chat)
        monkeypatch.setattr("agent.build_local_tools", mock_build_local)
        monkeypatch.setattr("agent.build_github_mcp_tools", mock_build_github)
        result = build_agent("qwen3")
        assert result == mock_agent

    def test_build_local_tools_returns_tools(self, monkeypatch):
        from agent import build_local_tools
        mock_tools = [MagicMock(), MagicMock()]
        monkeypatch.setattr("tools.LOCAL_TOOLS", mock_tools)
        result = build_local_tools()
        assert result == mock_tools

    def test_build_github_mcp_tools_returns_tools(self, monkeypatch):
        from agent import build_github_mcp_tools
        mock_tools = [MagicMock(), MagicMock()]
        monkeypatch.setattr("agent._load_github_mcp_tools", return_value=mock_tools)
        result = build_github_mcp_tools()
        assert result == mock_tools


# ──────────────────────────────────────────────────────────────────────────────
# streaming.py
# ──────────────────────────────────────────────────────────────────────────────

class TestStreaming:
    """Tests for streaming.py."""

    def test_safe_close_llm_calls_aclose(self):
        from streaming import _safe_close_llm
        llm = MagicMock()
        llm.aclose = MagicMock(return_value=None)
        asyncio.get_event_loop().run_until_complete(_safe_close_llm(llm))
        llm.aclose.assert_called_once()

    def test_safe_close_llm_calls_close_when_aclose_missing(self):
        from streaming import _safe_close_llm
        llm = MagicMock()
        del llm.aclose
        llm.close = MagicMock(return_value=None)
        asyncio.get_event_loop().run_until_complete(_safe_close_llm(llm))
        llm.close.assert_called_once()

    def test_safe_close_llm_ignores_non_callable(self):
        from streaming import _safe_close_llm
        llm = MagicMock()
        llm.aclose = "not callable"
        asyncio.get_event_loop().run_until_complete(_safe_close_llm(llm))

    def test_astream_with_chunk_timeout_yields_chunks(self):
        from streaming import _astream_with_chunk_timeout
        async def gen():
            yield "chunk1"
            yield "chunk2"
        result = []
        for chunk in _astream_with_chunk_timeout(gen(), 1.0):
            result.append(chunk)
        assert result == ["chunk1", "chunk2"]

    def test_astream_with_chunk_timeout_raises_on_timeout(self):
        from streaming import _astream_with_chunk_timeout
        async def gen():
            await asyncio.sleep(10)
            yield "chunk"
        with pytest.raises(asyncio.TimeoutError):
            for chunk in _astream_with_chunk_timeout(gen(), 0.1):
                pass

    def test_run_agent_turn_returns_text_and_tokens(self, monkeypatch):
        from streaming import run_agent_turn
        mock_agent = MagicMock()
        mock_agent.astream = MagicMock(return_value=iter([
            {"agent": {"messages": [MagicMock(tool_calls=[], usage_metadata={}, content="hello")]}},
        ]))
        result = asyncio.get_event_loop().run_until_complete(
            run_agent_turn(mock_agent, "test", "t1")
        )
        assert result[0] == "hello"
        assert result[1].input_tokens == 0
        assert result[1].output_tokens == 0


# ──────────────────────────────────────────────────────────────────────────────
# commands.py
# ──────────────────────────────────────────────────────────────────────────────

class TestCommands:
    """Tests for commands.py."""

    def test_clear_thread_clears_history(self, monkeypatch):
        from commands import ReplCommands
        state = MagicMock()
        state.session_history = ["msg1", "msg2"]
        cmd = ReplCommands(state)
        cmd.clear_thread("t1")
        assert state.session_history == []

    def test_clear_thread_handles_exception(self, monkeypatch):
        from commands import ReplCommands
        state = MagicMock()
        state.session_history = ["msg1"]
        state.session_history.clear = MagicMock(side_effect=Exception("fail"))
        cmd = ReplCommands(state)
        cmd.clear_thread("t1")

    def test_cmd_model_shows_current_when_no_args(self):
        from commands import ReplCommands
        state = MagicMock()
        state.model = "qwen3"
        cmd = ReplCommands(state)
        cmd.cmd_model([])

    def test_cmd_model_switches_model(self, monkeypatch):
        from commands import ReplCommands
        state = MagicMock()
        state.model = "qwen3"
        cmd = ReplCommands(state)
        mock_build = MagicMock()
        monkeypatch.setattr(cmd, "_build_agent", mock_build)
        cmd.cmd_model(["new-model"])
        assert state.model == "new-model"

    def test_cmd_model_handles_exception(self, monkeypatch):
        from commands import ReplCommands
        state = MagicMock()
        state.model = "qwen3"
        cmd = ReplCommands(state)
        monkeypatch.setattr(cmd, "_build_agent", MagicMock(side_effect=Exception("fail")))
        cmd.cmd_model(["new-model"])

    def test_cmd_cost_shows_table(self):
        from commands import ReplCommands
        state = MagicMock()
        state.session_tokens.input_tokens = 100
        state.session_tokens.output_tokens = 200
        state.session_tokens.total = 300
        state.session_history = ["msg1", "msg2"]
        cmd = ReplCommands(state)
        cmd.cmd_cost()

    def test_cmd_retry_returns_last_user_input(self):
        from commands import ReplCommands
        state = MagicMock()
        state.last_user_input = "test input"
        cmd = ReplCommands(state)
        result = cmd.cmd_retry()
        assert result == "test input"

    def test_cmd_retry_returns_none_when_no_input(self):
        from commands import ReplCommands
        state = MagicMock()
        state.last_user_input = ""
        cmd = ReplCommands(state)
        result = cmd.cmd_retry()
        assert result is None

    def test_cmd_issue_calls_issue_fn(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        issue_fn = MagicMock(return_value="issue result")
        result = cmd.cmd_issue(["owner/repo#1"], issue_fn)
        assert result == "issue result"

    def test_cmd_issue_shows_usage_when_no_args(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        result = cmd.cmd_issue([], MagicMock())
        assert result is None

    def test_cmd_review_calls_pr_fn(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        pr_fn = MagicMock(return_value="pr result")
        result = cmd.cmd_review(["owner/repo#1"], pr_fn)
        assert result == "pr result"

    def test_cmd_review_shows_usage_when_no_args(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        result = cmd.cmd_review([], MagicMock())
        assert result is None

    def test_cmd_pr_creates_pr_prompt(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        result = cmd.cmd_pr(["owner/repo", "title", "body"])
        assert "owner/repo" in result
        assert "title" in result
        assert "body" in result

    def test_cmd_pr_shows_usage_when_insufficient_args(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        result = cmd.cmd_pr(["owner/repo"])
        assert result is None

    def test_cmd_merge_creates_merge_prompt(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        result = cmd.cmd_merge(["owner/repo#1"])
        assert "owner/repo#1" in result

    def test_cmd_merge_shows_usage_when_no_args(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        result = cmd.cmd_merge([])
        assert result is None

    def test_cmd_health_returns_panel(self, monkeypatch):
        from commands import ReplCommands
        state = MagicMock()
        state.model = "qwen3"
        cmd = ReplCommands(state)
        mock_health = MagicMock()
        mock_render = MagicMock()
        monkeypatch.setattr(cmd, "cmd_health", mock_health)
        result = asyncio.get_event_loop().run_until_complete(cmd.cmd_health())
        assert result == mock_render

    def test_cmd_exit_returns_exit(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        result = cmd.cmd_exit()
        assert result == "exit"

    def test_dispatch_routes_command(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        mock_handler = MagicMock(return_value="result")
        monkeypatch.setattr(cmd, "cmd_test", mock_handler)
        result = asyncio.get_event_loop().run_until_complete(cmd.dispatch("!test", MagicMock(), MagicMock()))
        assert result == "result"

    def test_dispatch_handles_async_command(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        async def mock_handler():
            return "async result"
        monkeypatch.setattr(cmd, "cmd_test", mock_handler)
        result = asyncio.get_event_loop().run_until_complete(cmd.dispatch("!test", MagicMock(), MagicMock()))
        assert result == "async result"

    def test_dispatch_returns_true_for_unknown_command(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        result = asyncio.get_event_loop().run_until_complete(cmd.dispatch("!unknown", MagicMock(), MagicMock()))
        assert result is True

    def test_dispatch_returns_true_for_empty_command(self):
        from commands import ReplCommands
        state = MagicMock()
        cmd = ReplCommands(state)
        result = asyncio.get_event_loop().run_until_complete(cmd.dispatch("", MagicMock(), MagicMock()))
        assert result is True


