"""
Level 1 Smoke Tests – Local connectivity only, no network calls, no git side-effects.

"""
import re
import httpx
import pytest
from config import OLLAMA_BASE_URL, OLLAMA_MODEL

pytestmark = pytest.mark.integration


class TestOllama:
    def test_ollama_api_reachable(self):
        """Ollama HTTP API responds at the configured base URL."""
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
        assert resp.status_code == 200, (
            f"Ollama not reachable at {OLLAMA_BASE_URL}. "
            "Is `ollama serve` running?"
        )

class TestPowerShellModules:
    def test_list_available_modules_returns_results(self):
        """list_available_modules finds at least one module in the Modules dir."""
        from tools.shell import list_available_modules
        result = list_available_modules.invoke({})
        assert "No modules found" not in result, (
            f"No PowerShell modules found. Result: {result}"
        )
        assert len(result.strip().splitlines()) >= 1, (
            "Expected at least one module name in output."
        )
        print(f"\nModules found:\n{result}")

    def test_run_powershell_executes(self):
        """run_powershell can invoke pwsh and return output."""
        from tools.shell import run_powershell
        result = run_powershell.invoke({"command": "Write-Output 'hello-from-pwsh'"})
        assert "hello-from-pwsh" in result, (
            f"run_powershell didn't return expected output. Got: {result}"
        )

    def test_run_powershell_psversion_is_7(self):
        """pwsh version is 7 or higher (not Windows PowerShell 5)."""
        from tools.shell import run_powershell
        result = run_powershell.invoke({"command": "$PSVersionTable.PSVersion.Major"})
        # strip stderr noise and grab the first integer-looking token
        numbers = re.findall(r"\d+", result)
        assert numbers, f"Could not parse PSVersion from output: {result}"
        major = int(numbers[0])
        assert major >= 7, (
            f"Expected pwsh 7+, got major version {major}. "
            "Install PowerShell 7: https://github.com/PowerShell/PowerShell"
        )
        print(f"\nPSVersion major: {major}")

    def test_module_path_injected_into_psmodulepath(self):
        """The configured PS_MODULE_PATH is visible inside the pwsh session."""
        from tools.shell import run_powershell
        from config import PS_MODULE_PATH
        result = run_powershell.invoke({
            "command": "$env:PSModulePath -split ';' | Where-Object { $_ -ne '' }"
        })
        assert PS_MODULE_PATH.replace("\\", "/").lower() in result.replace("\\", "/").lower(), (
            f"PS_MODULE_PATH '{PS_MODULE_PATH}' not found in $env:PSModulePath.\n"
            f"PSModulePath entries:\n{result}"
        )

    def test_import_modules_param_loads_first_available_module(self):
        """import_modules kwarg successfully imports a module without error."""
        from tools.shell import run_powershell, list_available_modules
        modules_output = list_available_modules.invoke({})
        if "No modules found" in modules_output:
            pytest.skip("No modules available to test import_modules with.")

        first_module = modules_output.strip().splitlines()[0].strip()
        result = run_powershell.invoke({
            "command": f"(Get-Module '{first_module}' -ListAvailable | Select-Object -First 1).Name",
            "import_modules": [first_module],
        })
        assert "Error" not in result or first_module.lower() in result.lower(), (
            f"Importing module '{first_module}' produced an unexpected error:\n{result}"
        )
        print(f"\nSuccessfully imported: {first_module} → {result.strip()}")
