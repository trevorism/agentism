"""PowerShell execution tool – lets the agent run commands on the local Windows host."""
import re
import subprocess
from langchain_core.tools import tool
from agentism.config import PS_MODULE_PATH

_PREAMBLE = rf"$env:PSModulePath = $env:PSModulePath + ';{PS_MODULE_PATH}'; "
_GRADLE_SEMANTIC_ANALYSIS_ERROR = "Unsupported class file major version"


def _extract_major_class_version(text: str) -> int | None:
    match = re.search(r"Unsupported class file major version\s+(\d+)", text)
    if not match:
        return None
    return int(match.group(1))


def _run_pwsh(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _format_output(result: subprocess.CompletedProcess[str]) -> str:
    output = result.stdout.strip()
    error = result.stderr.strip()
    if error:
        return f"STDOUT:\n{output}\n\nSTDERR:\n{error}"
    return output or "(no output)"


def _is_gradle_command(command: str) -> bool:
    lowered = command.lower()
    return "gradle" in lowered or "gradlew" in lowered


def _build_gradle_recovery_script(command: str, target_major: int | None) -> str:
    target_java = (target_major - 44) if target_major and target_major > 44 else None
    fallback_max_java = max(8, target_java - 1) if target_java else None
    fallback_java_clause = ""
    if fallback_max_java:
        fallback_java_clause = (
            "$candidates = @(); "
            "$envCandidates = Get-ChildItem Env: | Where-Object { $_.Name -match 'JAVA_HOME|JDK' } | Select-Object -ExpandProperty Value; "
            "$candidates += $envCandidates; "
            "$roots = @('C:\\Program Files\\Java','C:\\Program Files\\Eclipse Adoptium','C:\\Program Files\\Microsoft'); "
            "foreach ($root in $roots) { "
            "  if (Test-Path $root) { "
            "    $dirs = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName; "
            "    $candidates += $dirs "
            "  } "
            "}; "
            "$bestHome = $null; $bestVersion = -1; "
            "foreach ($home in ($candidates | Where-Object { $_ } | Select-Object -Unique)) { "
            "  $releaseFile = Join-Path $home 'release'; "
            "  $javaExe = Join-Path $home 'bin\\java.exe'; "
            "  if (-not (Test-Path $javaExe) -or -not (Test-Path $releaseFile)) { continue }; "
            "  $line = Get-Content -Path $releaseFile -ErrorAction SilentlyContinue | Where-Object { $_ -like 'JAVA_VERSION=*' } | Select-Object -First 1; "
            "  if (-not $line) { continue }; "
            "  if ($line -match 'JAVA_VERSION=\"([0-9]+)') { "
            "    $v = [int]$Matches[1]; "
            f"    if ($v -le {fallback_max_java} -and $v -gt $bestVersion) {{ $bestVersion = $v; $bestHome = $home }} "
            "  } "
            "}; "
            "if ($bestHome) { "
            "  $env:JAVA_HOME = $bestHome; "
            "  $env:PATH = (Join-Path $bestHome 'bin') + ';' + $env:PATH; "
            "}; "
        )

    return (
        "$env:JAVA_TOOL_OPTIONS=''; "
        "$env:_JAVA_OPTIONS=''; "
        "$env:JDK_JAVA_OPTIONS=''; "
        "$env:GRADLE_OPTS=''; "
        "Remove-Item Env:JAVA_HOME -ErrorAction SilentlyContinue; "
        f"{fallback_java_clause}"
        "$gradleCmd = $null; "
        "if (Test-Path .\\gradlew.bat) { $gradleCmd = '.\\gradlew.bat' } "
        "elseif (Get-Command gradle -ErrorAction SilentlyContinue) { $gradleCmd = 'gradle' }; "
        "if ($gradleCmd) { & $gradleCmd --stop | Out-Null }; "
        f"{command}"
    )


def _execute_powershell(command: str, import_modules: list[str] | None = None) -> str:
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

    result = _run_pwsh(_PREAMBLE + imports + command)
    first_output = _format_output(result)

    combined = "\n".join(filter(None, [result.stdout, result.stderr]))
    if not _is_gradle_command(command) or _GRADLE_SEMANTIC_ANALYSIS_ERROR not in combined:
        return first_output

    target_major = _extract_major_class_version(combined)
    retry = _run_pwsh(_PREAMBLE + imports + _build_gradle_recovery_script(command, target_major))
    retry_output = _format_output(retry)
    return (
        "Auto-retry: detected Gradle/JDK semantic-analysis mismatch; "
        "cleared sticky JVM env vars, stopped daemons, and retried once.\n\n"
        f"{retry_output}"
    )


@tool
def run_powershell(command: str, import_modules: list[str] | None = None) -> str:
    """Run a pwsh command on the local machine and return its output."""
    return _execute_powershell(command, import_modules)


@tool
def run_in_terminal(command: str, import_modules: list[str] | None = None) -> str:
    """Alias for run_powershell with the same parameters."""
    return _execute_powershell(command, import_modules)


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


