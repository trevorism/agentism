"""PowerShell execution tool – lets the agent run commands on the local Windows host."""
import subprocess
from langchain_core.tools import tool
from agentism.config import PS_MODULE_PATH

_PREAMBLE = rf"$env:PSModulePath = $env:PSModulePath + ';{PS_MODULE_PATH}'; "


@tool
def run_powershell(command: str, import_modules: list[str] | None = None) -> str:
    """
    Run a pwsh (PowerShell 7+) command on the local machine and return its output.

    The PS_MODULE_PATH directory is added to $env:PSModulePath automatically
    so any module stored there can be imported by name.

    Use this to:
    - Invoke platform APIs via PowerShell client scripts
    - Run tests, builds, or deployment scripts
    - Query system state or environment
    - Use custom modules from the configured PowerShell Modules directory

    Args:
        command:        A valid pwsh expression or script block.
        import_modules: Optional list of module names to Import-Module before
                        running the command (e.g. ["MyModule", "Deploy"]).

    Returns:
        Combined stdout and stderr from the pwsh process.
    """
    imports = ""
    if import_modules:
        imports = " ".join(f"Import-Module '{m}' -ErrorAction Stop;" for m in import_modules) + " "

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", _PREAMBLE + imports + command],
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout.strip()
    error = result.stderr.strip()
    if error:
        return f"STDOUT:\n{output}\n\nSTDERR:\n{error}"
    return output or "(no output)"


@tool
def list_available_modules() -> str:
    """
    List all PowerShell modules available under the configured PS_MODULE_PATH.

    Use this to discover what platform/custom modules can be imported before
    running a command that needs them.

    Returns:
        Newline-separated list of module names found in the Modules directory.
    """
    import os

    if not os.path.isdir(PS_MODULE_PATH):
        return f"Module path not found: {PS_MODULE_PATH}"

    modules = [
        item.name for item in os.scandir(PS_MODULE_PATH)
        if item.is_dir() or item.name.endswith((".psm1", ".psd1"))
    ]
    return "\n".join(sorted(modules)) if modules else f"No modules found under {PS_MODULE_PATH}"


