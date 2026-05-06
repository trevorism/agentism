"""Test runner tool – detects repo type and runs the appropriate test suite."""
import subprocess
from pathlib import Path
from langchain_core.tools import tool
from agentism.config import DEV_DIR, WORKSPACE_DIR


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

    # Groovy / Gradle unit tests
    if (repo_root / "build.gradle").exists() or (repo_root / "build.gradle.kts").exists():
        gradle_wrapper = "gradlew.bat" if (repo_root / "gradlew.bat").exists() else "gradlew"
        suites.append({
            "label": "Groovy/Gradle tests",
            "cwd": str(repo_root),
            "command": [gradle_wrapper, "test", "--info"],
        })

    # Cucumber acceptance tests (look for a cucumber-specific gradle task or feature files)
    feature_dirs = list(repo_root.rglob("*.feature"))
    if feature_dirs:
        gradle_wrapper = "gradlew.bat" if (repo_root / "gradlew.bat").exists() else "gradlew"
        if (repo_root / "build.gradle").exists() or (repo_root / "build.gradle.kts").exists():
            suites.append({
                "label": "Cucumber acceptance tests",
                "cwd": str(repo_root),
                "command": [gradle_wrapper, "cucumber", "--info"],
            })

    # Node / Vue / Vitest
    package_json = repo_root / "package.json"
    if package_json.exists():
        import json
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                test_cmd = scripts["test"]
                # Prefer vitest run (non-interactive) over bare "vitest" which watches
                if "vitest" in test_cmd and "run" not in test_cmd:
                    command = ["npx", "vitest", "run"]
                else:
                    command = ["npm", "test", "--", "--run"]
            else:
                command = ["npx", "vitest", "run"]
            suites.append({
                "label": "Vitest / JS tests",
                "cwd": str(repo_root),
                "command": command,
            })
        except Exception:
            pass

    return suites


@tool
def run_tests(repo_name: str, suite: str = "all") -> str:
    """
    Run the test suite(s) for a local repository.

    Automatically detects the repo type:
    - Groovy/Micronaut repos (build.gradle)  → `gradlew test`
    - Vue/JS repos (package.json)            → `npx vitest run` or `npm test`
    - Cucumber feature files present         → `gradlew cucumber`

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
            proc = subprocess.run(
                s["command"],
                cwd=s["cwd"],
                capture_output=True,
                text=True,
                timeout=300,
                shell=False,
            )
            output = proc.stdout.strip()
            error = proc.stderr.strip()
            combined = "\n".join(filter(None, [output, error]))
            # Truncate very long output but keep the tail (most useful part)
            if len(combined) > 3000:
                combined = "… (truncated) …\n" + combined[-3000:]
            status = "✅ PASSED" if proc.returncode == 0 else f"❌ FAILED (exit {proc.returncode})"
            results.append(f"{status}\n{combined}")
        except subprocess.TimeoutExpired:
            results.append("❌ TIMED OUT after 300 seconds")
        except FileNotFoundError as e:
            results.append(f"❌ Command not found: {e}\nMake sure the required build tool is on PATH.")
        except Exception as e:
            results.append(f"❌ Error: {e}")

    return "\n".join(results)

