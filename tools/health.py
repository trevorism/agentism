"""Health diagnostic checks for the agent runtime environment."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import config

console = Console()


@dataclass
class HealthCheck:
    """Result of a single health check."""
    name: str
    status: str  # "OK", "Warning", "Error"
    details: str
    remediation: str = ""


def _normalize_model_name(name: str) -> str:
    """Normalize model names so `foo` and `foo:latest` compare as the same model."""
    clean = (name or "").strip()
    if not clean:
        return ""
    return clean.split(":", 1)[0]


async def check_ollama(model_name: str | None = None) -> HealthCheck:
    """Check if Ollama is running and the configured model is available."""
    requested_model = (model_name or config.OLLAMA_MODEL).strip()
    requested_normalized = _normalize_model_name(requested_model)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
            if resp.status_code != 200:
                return HealthCheck(
                    "Ollama", "Error", f"HTTP {resp.status_code}",
                    "Ensure Ollama is running: `ollama serve`",
                )
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]

            matched_model = next(
                (
                    installed
                    for installed in models
                    if installed == requested_model
                    or _normalize_model_name(installed) == requested_normalized
                ),
                None,
            )
            if matched_model:
                return HealthCheck("Ollama", "OK", f"Installed: {matched_model}")

            return HealthCheck(
                "Ollama", "Warning",
                f"Model '{requested_model}' not found. Available: {', '.join(models[:5])}",
                f"Pull the model: `ollama pull {requested_model}`",
            )
    except Exception as e:
        return HealthCheck("Ollama", "Error", str(e), "Start Ollama: `ollama serve`")


async def check_github_token() -> HealthCheck:
    """Validate the GitHub personal access token."""
    if not config.GITHUB_TOKEN:
        return HealthCheck("GitHub", "Warning", "GITHUB_TOKEN not set",
                           "Set GITHUB_TOKEN in .env for GitHub MCP tools")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {config.GITHUB_TOKEN}"},
            )
            if resp.status_code == 200:
                return HealthCheck("GitHub", "OK", "Token valid")
            if resp.status_code == 401:
                return HealthCheck("GitHub", "Error", "Token expired or invalid",
                                   "Regenerate your GitHub PAT with 'repo' scope")
            return HealthCheck("GitHub", "Warning", f"HTTP {resp.status_code}",
                               "Check your token permissions")
    except Exception as e:
        return HealthCheck("GitHub", "Error", str(e), "Check your network connection")


def check_git_config() -> HealthCheck:
    """Check if Git is configured with user.name and user.email."""
    try:
        subprocess.run(["git", "version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return HealthCheck("Git", "Error", "Git not found", "Install Git from https://git-scm.com")

    issues = []
    for key in ["user.name", "user.email"]:
        try:
            result = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True)
            if result.returncode != 0:
                issues.append(key)
        except Exception:
            issues.append(key)

    if issues:
        return HealthCheck("Git", "Warning", f"Missing: {', '.join(issues)}",
                           "Run: git config --global user.name 'Your Name'")
    return HealthCheck("Git", "OK", "Configured")


def check_disk_space() -> HealthCheck:
    """Check available disk space on the development directory."""
    try:
        for dir_path in [config.DEV_DIR, config.WORKSPACE_DIR]:
            if dir_path.exists():
                usage = shutil.disk_usage(str(dir_path))
                free_gb = usage.free / (1024 ** 3)
                if free_gb < 1:
                    return HealthCheck("Disk Space", "Error", f"Only {free_gb:.1f}GB free on {dir_path}",
                                       "Free up disk space")
                if free_gb < 5:
                    return HealthCheck("Disk Space", "Warning", f"{free_gb:.1f}GB free on {dir_path}",
                                       "Consider freeing up disk space")
                return HealthCheck("Disk Space", "OK", f"{free_gb:.1f}GB free on {dir_path}")
        return HealthCheck("Disk Space", "Warning", "Could not find DEV_DIR or WORKSPACE_DIR")
    except Exception as e:
        return HealthCheck("Disk Space", "Error", str(e))


async def check_memory_db() -> HealthCheck:
    """Check if the SQLite memory database is accessible."""
    db_path = Path(config.MEMORY_DB)
    if not db_path.exists():
        return HealthCheck("Memory DB", "Warning", f"Database file not found: {config.MEMORY_DB}",
                           "The database will be created on first use")
    try:
        async with aiosqlite.connect(config.MEMORY_DB) as db:
            await db.execute("SELECT 1")
        return HealthCheck("Memory DB", "OK", f"Accessible: {config.MEMORY_DB}")
    except Exception as e:
        return HealthCheck("Memory DB", "Error", str(e), "Check database file permissions")


def check_pwsh() -> HealthCheck:
    """Check if PowerShell 7+ is available."""
    try:
        result = subprocess.run(["pwsh", "-version"], capture_output=True, text=True)
        if result.returncode == 0:
            return HealthCheck("PowerShell", "OK", result.stdout.strip())
    except FileNotFoundError:
        pass
    return HealthCheck("PowerShell", "Error", "PowerShell 7+ not found",
                       "Install from https://aka.ms/powershell")


def check_node() -> HealthCheck:
    """Check if Node.js is available for MCP servers."""
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return HealthCheck("Node.js", "OK", result.stdout.strip())
    except FileNotFoundError:
        pass
    return HealthCheck("Node.js", "Warning", "Not found",
                       "Install from https://nodejs.org for MCP server support")


def render_health_report(checks: list[HealthCheck]) -> Panel:
    """Render a Rich Panel with health check results."""
    table = Table(title="Agentism Health Check", border_style="cyan")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details")
    table.add_column("Remediation")

    for check in checks:
        status_style = {
            "OK": "green",
            "Warning": "yellow",
            "Error": "red",
        }.get(check.status, "white")

        table.add_row(
            check.name,
            f"[{status_style}]{check.status}[/{status_style}]",
            check.details,
            check.remediation or "",
        )

    return Panel(table, title="Agentism Health Check", border_style="cyan")


async def run_health_checks(active_model: str | None = None) -> list[HealthCheck]:
    """Run all health checks and return results."""
    async def _async_check(fn, *args):
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args)
        return await asyncio.to_thread(fn, *args)

    checks = [
        _async_check(check_ollama, active_model),
        _async_check(check_github_token),
        _async_check(check_git_config),
        _async_check(check_disk_space),
        _async_check(check_memory_db),
        _async_check(check_pwsh),
        _async_check(check_node),
    ]
    return await asyncio.gather(*checks)
