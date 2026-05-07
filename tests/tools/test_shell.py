from tools.shell import run_in_terminal, run_powershell


class _FakeCompletedProcess:
    def __init__(self, stdout: str = "", stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr


def test_run_in_terminal_executes_powershell_command(monkeypatch):
    calls = {}

    def fake_run(args, capture_output, text, timeout):
        calls["args"] = args
        calls["capture_output"] = capture_output
        calls["text"] = text
        calls["timeout"] = timeout
        return _FakeCompletedProcess(stdout="ok\n", stderr="")

    monkeypatch.setattr("tools.shell.subprocess.run", fake_run)

    result = run_in_terminal.func("Write-Output 'ok'")

    assert result == "ok"
    assert calls["args"][0] == "pwsh"
    assert "Write-Output 'ok'" in calls["args"][4]


def test_run_in_terminal_supports_import_modules(monkeypatch):
    calls = {}

    def fake_run(args, capture_output, text, timeout):
        calls["args"] = args
        return _FakeCompletedProcess(stdout="ok\n", stderr="")

    monkeypatch.setattr("tools.shell.subprocess.run", fake_run)

    run_in_terminal.func("Write-Output 'ok'", import_modules=["Trevorism"])

    assert "Import-Module 'Trevorism' -ErrorAction Stop;" in calls["args"][4]


def test_run_powershell_alias_matches_run_in_terminal(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        return _FakeCompletedProcess(stdout="same\n", stderr="")

    monkeypatch.setattr("tools.shell.subprocess.run", fake_run)

    assert run_powershell.func("Write-Output 'same'") == run_in_terminal.func("Write-Output 'same'")


def test_run_in_terminal_returns_stderr_block(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        return _FakeCompletedProcess(stdout="", stderr="boom")

    monkeypatch.setattr("tools.shell.subprocess.run", fake_run)

    result = run_in_terminal.func("bad")

    assert "STDERR:" in result
    assert "boom" in result


