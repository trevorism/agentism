"""Tests for the health diagnostic module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console
from rich.panel import Panel

import tools.health as health
from tools.health import (
    HealthCheck,
    check_disk_space,
    check_git_config,
    check_github_token,
    check_memory_db,
    check_node,
    check_ollama,
    check_pwsh,
    render_health_report,
    run_health_checks,
)


def _mock_async_client_with_response(status_code: int = 200, json_payload: dict | None = None):
    """Build a mocked AsyncClient context manager and response object."""
    payload = json_payload or {}
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json = MagicMock(return_value=payload)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# -- check_ollama --

@pytest.mark.asyncio
async def test_check_ollama_ok_exact_match():
    mock_client = _mock_async_client_with_response(
        status_code=200,
        json_payload={"models": [{"name": "llama3.2"}]},
    )
    with patch("tools.health.httpx.AsyncClient", return_value=mock_client):
        result = await check_ollama(model_name="llama3.2")

    assert result.status == "OK"
    assert "Installed: llama3.2" in result.details


@pytest.mark.asyncio
async def test_check_ollama_ok_with_latest_tag_alias():
    mock_client = _mock_async_client_with_response(
        status_code=200,
        json_payload={"models": [{"name": "llama3.2:latest"}]},
    )
    with patch("tools.health.httpx.AsyncClient", return_value=mock_client):
        result = await check_ollama(model_name="llama3.2")

    assert result.status == "OK"
    assert "llama3.2:latest" in result.details


@pytest.mark.asyncio
async def test_check_ollama_model_not_found():
    mock_client = _mock_async_client_with_response(
        status_code=200,
        json_payload={"models": [{"name": "other-model"}]},
    )
    with patch("tools.health.httpx.AsyncClient", return_value=mock_client):
        result = await check_ollama(model_name="my-model")

    assert result.status == "Warning"
    assert "not found" in result.details.lower()


@pytest.mark.asyncio
async def test_check_ollama_connection_error():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("tools.health.httpx.AsyncClient", return_value=mock_client):
        result = await check_ollama(model_name="llama3.2")

    assert result.status == "Error"
    assert "Connection refused" in result.details


@pytest.mark.asyncio
async def test_check_ollama_uses_config_when_no_override():
    mock_client = _mock_async_client_with_response(
        status_code=200,
        json_payload={"models": [{"name": "qwen3.6:latest"}]},
    )

    with patch("tools.health.httpx.AsyncClient", return_value=mock_client):
        with patch.object(health.config, "OLLAMA_MODEL", "qwen3.6"):
            result = await check_ollama()

    assert result.status == "OK"


# -- check_github_token --

@pytest.mark.asyncio
async def test_check_github_token_ok():
    mock_client = _mock_async_client_with_response(status_code=200)
    with patch("tools.health.httpx.AsyncClient", return_value=mock_client):
        with patch.object(health.config, "GITHUB_TOKEN", "test-token"):
            result = await check_github_token()

    assert result.status == "OK"


@pytest.mark.asyncio
async def test_check_github_token_unauthorized():
    mock_client = _mock_async_client_with_response(status_code=401)
    with patch("tools.health.httpx.AsyncClient", return_value=mock_client):
        with patch.object(health.config, "GITHUB_TOKEN", "bad-token"):
            result = await check_github_token()

    assert result.status == "Error"
    assert "Token expired or invalid" in result.details


# -- check_git_config --

def test_check_git_config_ok():
    with patch("tools.health.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="git version 2.43.0\n"),
            MagicMock(returncode=0, stdout="Test User\n"),
            MagicMock(returncode=0, stdout="test@example.com\n"),
        ]

        result = check_git_config()

    assert result.status == "OK"


def test_check_git_config_missing_name():
    with patch("tools.health.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="git version 2.43.0\n"),
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout="test@example.com\n"),
        ]

        result = check_git_config()

    assert result.status == "Warning"
    assert "user.name" in result.details


# -- check_disk_space --

def test_check_disk_space_ok():
    fake_usage = MagicMock()
    fake_usage.free = 100_000_000_000  # ~100GB

    with patch("tools.health.shutil.disk_usage", return_value=fake_usage):
        with patch.object(health.config, "DEV_DIR", Path(".")):
            with patch.object(health.config, "WORKSPACE_DIR", Path(".")):
                result = check_disk_space()

    assert result.status == "OK"


def test_check_disk_space_low():
    fake_usage = MagicMock()
    fake_usage.free = 100_000  # ~0.1MB

    with patch("tools.health.shutil.disk_usage", return_value=fake_usage):
        with patch.object(health.config, "DEV_DIR", Path(".")):
            with patch.object(health.config, "WORKSPACE_DIR", Path(".")):
                result = check_disk_space()

    assert result.status in ("Warning", "Error")


# -- check_memory_db --

@pytest.mark.asyncio
async def test_check_memory_db_file_not_found():
    with patch.object(health.config, "MEMORY_DB", "nonexistent.db"):
        with patch("tools.health.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            result = await check_memory_db()

    assert result.status == "Warning"


@pytest.mark.asyncio
async def test_check_memory_db_ok():
    with patch.object(health.config, "MEMORY_DB", "test.db"):
        with patch("tools.health.Path") as mock_path_cls:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path_cls.return_value = mock_path

            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=None)
            mock_db.execute = AsyncMock(return_value=None)

            with patch("tools.health.aiosqlite.connect", return_value=mock_db):
                result = await check_memory_db()

    assert result.status == "OK"


# -- check_pwsh --

def test_check_pwsh_ok():
    with patch("tools.health.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="PowerShell 7.4.0\n")
        result = check_pwsh()

    assert result.status == "OK"


def test_check_pwsh_not_found():
    with patch("tools.health.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = check_pwsh()

    assert result.status == "Error"


# -- check_node --

def test_check_node_ok():
    with patch("tools.health.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="v20.10.0\n")
        result = check_node()

    assert result.status == "OK"


def test_check_node_not_found():
    with patch("tools.health.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = check_node()

    assert result.status == "Warning"


# -- render_health_report --

def test_render_health_report_returns_panel():
    checks = [
        HealthCheck("Ollama", "OK", "Installed"),
        HealthCheck("GitHub", "Error", "Token invalid", "Fix token"),
    ]
    console = Console(record=True, width=120)
    panel = render_health_report(checks)

    assert isinstance(panel, Panel)
    console.print(panel)
    output = console.export_text()
    assert "Agentism Health Check" in output


def test_render_health_report_shows_remediation():
    checks = [
        HealthCheck("Ollama", "Warning", "Low disk", "Free space"),
    ]
    console = Console(record=True, width=120)
    panel = render_health_report(checks)
    console.print(panel)
    output = console.export_text()

    assert "Remediation" in output
    assert "Free space" in output


# -- run_health_checks --

@pytest.mark.asyncio
async def test_run_health_checks_passes_active_model_override():
    with patch("tools.health.check_ollama", new_callable=AsyncMock) as mock_ollama:
        mock_ollama.return_value = HealthCheck("Ollama", "OK", "OK")
        with patch("tools.health.check_github_token", new_callable=AsyncMock) as mock_gh:
            mock_gh.return_value = HealthCheck("GitHub", "OK", "OK")
            with patch("tools.health.check_git_config", return_value=HealthCheck("Git", "OK", "OK")):
                with patch("tools.health.check_disk_space", return_value=HealthCheck("Disk", "OK", "OK")):
                    with patch("tools.health.check_memory_db", new_callable=AsyncMock) as mock_db:
                        mock_db.return_value = HealthCheck("DB", "OK", "OK")
                        with patch("tools.health.check_embedding_model", new_callable=AsyncMock) as mock_embed:
                            mock_embed.return_value = HealthCheck("Embedding", "OK", "OK")
                            with patch("tools.health.check_pwsh", return_value=HealthCheck("PS", "OK", "OK")):
                                with patch("tools.health.check_node", return_value=HealthCheck("Node", "OK", "OK")):
                                    results = await run_health_checks(active_model="qwen3.6")

    assert len(results) == 8
    assert all(isinstance(r, HealthCheck) for r in results)
    mock_ollama.assert_awaited_once_with("qwen3.6")

