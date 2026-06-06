"""Test runner tool – detects repo type and runs the appropriate test suite."""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from pathlib import Path
from langchain_core.tools import tool
from agentism.config import DEV_DIR, WORKSPACE_DIR

_GRADLE_SEMANTIC_ANALYSIS_ERROR = "Unsupported class file major version"
_JAVA_RELEASE_VERSION_RE = re.compile(r"JAVA_VERSION=\"(\d+)(?:[.\"]|$)")


def _extract_major_class_version(text: str) -> int | None:
    match = re.search(r"Unsupported class file major version\s+(\d+)", text)
    if not match:
        return None
    return int(match.group(1))


def _java_version_from_release(java_home: str) -> int | None:
    release_file = Path(java_home) / "release"
    if not release_file.exists():
        return None
    try:
        content = release_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = _JAVA_RELEASE_VERSION_RE.search(content)
    return int(match.group(1)) if match else None


def _candidate_java_homes_from_env(env: dict[str, str]) -> list[str]:
    candidates: list[str] = []

    def _append(path_value: str | None) -> None:
        if not path_value:
            return
        p = Path(path_value)
        if (p / "bin" / ("java.exe" if platform.system() == "Windows" else "java")).exists():
            resolved = str(p.resolve())
            if resolved not in candidates:
                candidates.append(resolved)

    _append(env.get("JAVA_HOME"))
    for key, value in env.items():
        key_upper = key.upper()
        if "JAVA_HOME" in key_upper or key_upper.startswith("JDK"):
            _append(value)

    return candidates


def _candidate_java_homes_from_filesystem() -> list[str]:
    candidates: list[str] = []

    if platform.system() == "Windows":
        roots = [
            Path("C:/Program Files/Java"),
            Path("C:/Program Files/Eclipse Adoptium"),
            Path("C:/Program Files/Microsoft"),
        ]
        java_exe = "java.exe"
    else:
        roots = [
            Path("/usr/lib/jvm"),
            Path("/opt/java"),
            Path("/Library/Java/JavaVirtualMachines"),
        ]
        java_exe = "java"

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            # macOS JDK bundles store binaries under Contents/Home.
            java_home = child / "Contents" / "Home" if (child / "Contents" / "Home").is_dir() else child
            if (java_home / "bin" / java_exe).exists():
                resolved = str(java_home.resolve())
                if resolved not in candidates:
                    candidates.append(resolved)

    return candidates


def _select_compatible_java_home(env: dict[str, str], max_java_version: int) -> str | None:
    best_home: str | None = None
    best_version = -1

    ordered_homes = _candidate_java_homes_from_env(env)
    for home in _candidate_java_homes_from_filesystem():
        if home not in ordered_homes:
            ordered_homes.append(home)

    for java_home in ordered_homes:
        version = _java_version_from_release(java_home)
        if version is None:
            continue
        if version <= max_java_version and version > best_version:
            best_home = java_home
            best_version = version

    return best_home


def _build_gradle_retry_env(env: dict[str, str], target_class_major: int | None) -> dict[str, str]:
    retry_env = dict(env)
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "GRADLE_OPTS"):
        retry_env.pop(key, None)

    # Java classfile major version N corresponds to Java (N - 44).
    if target_class_major and target_class_major > 44:
        target_java = target_class_major - 44
        fallback_max_java = max(8, target_java - 1)
        fallback_java_home = _select_compatible_java_home(retry_env, fallback_max_java)
        if fallback_java_home:
            retry_env["JAVA_HOME"] = fallback_java_home
            path_entries = retry_env.get("PATH", "").split(os.pathsep)
            java_bin = str(Path(fallback_java_home) / "bin")
            if java_bin not in path_entries:
                retry_env["PATH"] = java_bin + os.pathsep + retry_env.get("PATH", "")

    return retry_env


def _run_suite_command(command: list[str], cwd: str) -> tuple[subprocess.CompletedProcess[str], str | None]:
    env = os.environ.copy()
    proc = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
        env=env,
    )

    is_gradle = bool(command) and ("gradle" in Path(command[0]).name.lower())
    combined_output = "\n".join(filter(None, [proc.stdout, proc.stderr]))
    if not is_gradle or _GRADLE_SEMANTIC_ANALYSIS_ERROR not in combined_output:
        return proc, None

    target_major = _extract_major_class_version(combined_output)
    retry_env = _build_gradle_retry_env(env, target_major)
    stop_cmd = [command[0], "--stop"]
    retry_command = command if "--no-daemon" in command else [*command, "--no-daemon"]

    try:
        subprocess.run(
            stop_cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
            env=retry_env,
        )
    except Exception:
        # A failed daemon stop should not block the real retry.
        pass

    retry_proc = subprocess.run(
        retry_command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
        env=retry_env,
    )
    note = (
        "Auto-retry: detected Gradle/JDK semantic-analysis mismatch; "
        "stopped daemons, sanitized JVM env, and retried with --no-daemon."
    )
    return retry_proc, note


def _repo_path(repo_name: str) -> Path:
    p = Path(repo_name)
    if p.is_absolute():
        return p
    primary = DEV_DIR / repo_name
    if primary.exists():
        return primary
    return WORKSPACE_DIR / repo_name


def _detect_test_commands(repo_root: Path) -> list[dict]:
    """
    Inspect repo layout and return a list of test suites to run.
    Each entry has: label, cwd, command (list).
    """
    suites = []

    is_windows = platform.system() == "Windows"
    gradle_wrapper = "gradlew.bat" if is_windows else "gradlew"

    # Groovy / Gradle unit tests – prefer wrapper, fall back to system gradle
    gradle_cmd = [gradle_wrapper, "test", "--info"] if (repo_root / gradle_wrapper).exists() \
        else ["gradle", "test", "--info"]
    if (repo_root / "build.gradle").exists() or (repo_root / "build.gradle.kts").exists():
        suites.append({
            "label": "Groovy/Gradle tests",
            "cwd": str(repo_root),
            "command": gradle_cmd,
        })

    # Cucumber acceptance tests (look for a cucumber-specific gradle task or feature files)
    feature_files = list(repo_root.rglob("*.feature"))
    cucumber_gradle_cmd = [gradle_wrapper, "cucumber", "--info"] if (repo_root / gradle_wrapper).exists() \
        else ["gradle", "cucumber", "--info"]
    if feature_files:
        suites.append({
            "label": "Cucumber acceptance tests",
            "cwd": str(repo_root),
            "command": cucumber_gradle_cmd,
        })

    # Node / Vue / Vitest
    package_json = repo_root / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                test_cmd = scripts["test"]
                # Prefer vitest run (non-interactive) over bare "vitest" which watches
                if "vitest" in test_cmd:
                    command = ["npx", "vitest", "run"]
                else:
                    command = ["npm", "test", "--", "--run"]
                suites.append({
                    "label": "Vitest / JS tests",
                    "cwd": str(repo_root),
                    "command": command,
                })
            else:
                # No test script, but try vitest if it's a dependency
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "vitest" in deps:
                    suites.append({
                        "label": "Vitest / JS tests (auto-detected)",
                        "cwd": str(repo_root),
                        "command": ["npx", "vitest", "run"],
                    })
        except Exception:
            pass

    return suites


@tool
def run_tests(repo_name: str, suite: str = "all") -> str:
    """
    Run the test suite(s) for a local repository.

    Automatically detects the repo type:
    - Groovy/Micronaut repos (build.gradle)  → `gradlew test` (or `gradle test`)
    - Vue/JS repos (package.json)            → `npx vitest run` or `npm test`
    - Cucumber feature files present         → `gradlew cucumber` (or `gradle cucumber`)

    Always run tests after writing code to verify correctness before committing.

    Args:
        repo_name: Short name of the repo (checked in DEV_DIR first), or absolute path.
        suite:     Which suite to run: "all" (default), "groovy", "vitest", or "cucumber".

    Returns:
        Combined stdout/stderr per suite with pass/fail summary, or an error message.
    """
    repo_root = _repo_path(repo_name)
    if not repo_root.exists():
        return f"Repo not found: {repo_root}. Use git_clone first."

    suites = _detect_test_commands(repo_root)
    if not suites:
        return (
            f"No recognisable test configuration found in {repo_root}.\n"
            "Expected build.gradle, build.gradle.kts, or package.json.\n"
            f"Directory contents: {[p.name for p in repo_root.iterdir()]}"
        )

    # Filter if a specific suite was requested
    if suite != "all":
        suites = [s for s in suites if suite.lower() in s["label"].lower()]
        if not suites:
            return f"No suite matching '{suite}' found. Available: {[s['label'] for s in _detect_test_commands(repo_root)]}"

    results = []
    for s in suites:
        results.append(f"\n{'─'*60}\n▶ {s['label']}\n{'─'*60}")
        try:
            proc, retry_note = _run_suite_command(s["command"], s["cwd"])
            output = proc.stdout.strip()
            error = proc.stderr.strip()
            combined = "\n".join(filter(None, [output, error]))
            # Truncate very long output but keep the tail (most useful part)
            if len(combined) > 3000:
                combined = "… (truncated) …\n" + combined[-3000:]
            status = "✅ PASSED" if proc.returncode == 0 else f"❌ FAILED (exit {proc.returncode})"
            if retry_note:
                combined = "\n".join(filter(None, [retry_note, combined]))
            results.append(f"{status}\n{combined}")
        except subprocess.TimeoutExpired:
            results.append("❌ TIMED OUT after 300 seconds")
        except FileNotFoundError as e:
            results.append(f"❌ Command not found: {e}\nMake sure the required build tool is on PATH.")
        except Exception as e:
            results.append(f"❌ Error: {e}")

    return "\n".join(results)