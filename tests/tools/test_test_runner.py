import subprocess
from pathlib import Path

from tools import test_runner


def test_extract_major_class_version_parses_value():
    text = "Unsupported class file major version 69"
    assert test_runner._extract_major_class_version(text) == 69


def test_build_gradle_retry_env_clears_sticky_jvm_vars(monkeypatch):
    env = {
        "JAVA_HOME": "C:/jdk-25",
        "PATH": "C:/Windows/System32",
        "JAVA_TOOL_OPTIONS": "-Xmx2g",
        "_JAVA_OPTIONS": "-Xms256m",
        "JDK_JAVA_OPTIONS": "-Dfoo=bar",
        "GRADLE_OPTS": "-Dorg.gradle.jvmargs=-Xmx2g",
    }

    monkeypatch.setattr(
        "tools.test_runner._select_compatible_java_home",
        lambda _env, _max: "C:/jdk-21",
    )

    result = test_runner._build_gradle_retry_env(env, 69)

    assert "JAVA_TOOL_OPTIONS" not in result
    assert "_JAVA_OPTIONS" not in result
    assert "JDK_JAVA_OPTIONS" not in result
    assert "GRADLE_OPTS" not in result
    assert result["JAVA_HOME"] == "C:/jdk-21"
    assert result["PATH"].split(";", 1)[0].endswith("jdk-21\\bin")


def test_run_suite_command_retries_gradle_semantic_analysis_error(monkeypatch):
    calls = []

    def fake_run(command, cwd, capture_output, text, timeout, shell, env):
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="BUG! exception in phase 'semantic analysis' Unsupported class file major version 69",
            )
        if len(calls) == 2:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="tests passed", stderr="")

    monkeypatch.setattr("tools.test_runner.subprocess.run", fake_run)
    monkeypatch.setattr(
        "tools.test_runner._build_gradle_retry_env",
        lambda env, target: env,
    )

    proc, note = test_runner._run_suite_command(["gradlew.bat", "test"], "C:/repo")

    assert proc.returncode == 0
    assert "Auto-retry" in note
    assert calls[1] == ["gradlew.bat", "--stop"]
    assert calls[2] == ["gradlew.bat", "test", "--no-daemon"]


def test_run_suite_command_skips_retry_for_non_gradle(monkeypatch):
    calls = []

    def fake_run(command, cwd, capture_output, text, timeout, shell, env):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Unsupported class file major version 69")

    monkeypatch.setattr("tools.test_runner.subprocess.run", fake_run)

    proc, note = test_runner._run_suite_command(["npm", "test"], "C:/repo")

    assert proc.returncode == 1
    assert note is None
    assert len(calls) == 1


def test_candidate_java_homes_from_filesystem_finds_windows_layout(monkeypatch, tmp_path):
    java_root = tmp_path / "Program Files" / "Java"
    jdk_dir = java_root / "jdk-21"
    (jdk_dir / "bin").mkdir(parents=True)
    (jdk_dir / "bin" / "java.exe").write_text("", encoding="utf-8")

    monkeypatch.setattr("tools.test_runner.platform.system", lambda: "Windows")

    roots = [
        tmp_path / "Program Files" / "Java",
        tmp_path / "Program Files" / "Eclipse Adoptium",
        tmp_path / "Program Files" / "Microsoft",
    ]

    class _PathProxy:
        def __call__(self, value):
            value_str = str(value).replace("\\", "/")
            if value_str == "C:/Program Files/Java":
                return roots[0]
            if value_str == "C:/Program Files/Eclipse Adoptium":
                return roots[1]
            if value_str == "C:/Program Files/Microsoft":
                return roots[2]
            return Path(value)

    monkeypatch.setattr("tools.test_runner.Path", _PathProxy())

    homes = test_runner._candidate_java_homes_from_filesystem()

    assert str(jdk_dir.resolve()) in homes


def test_select_compatible_java_home_uses_filesystem_candidates(monkeypatch):
    monkeypatch.setattr("tools.test_runner._candidate_java_homes_from_env", lambda _env: [])
    monkeypatch.setattr("tools.test_runner._candidate_java_homes_from_filesystem", lambda: ["C:/jdk-17", "C:/jdk-21"])
    monkeypatch.setattr(
        "tools.test_runner._java_version_from_release",
        lambda java_home: {"C:/jdk-17": 17, "C:/jdk-21": 21}.get(java_home),
    )

    selected = test_runner._select_compatible_java_home({}, 21)

    assert selected == "C:/jdk-21"


