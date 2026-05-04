"""
Level 2 Smoke Tests – Platform authentication and GitHub cmdlet integration.
"""
from tools.shell import run_powershell
from tools.web_tool import _acquire_token


class TestPlatformToken:
    def test_token_is_acquired(self):
        """A non-empty platform token is returned by the PowerShell cmdlet."""
        token = _acquire_token()
        assert token, "Token was empty – check TREVORISM_USERNAME / TREVORISM_PASSWORD / TREVORISM_TENANT_GUID in .env"
        # Tokens are typically JWTs (three base64 segments) or similar bearer strings
        assert len(token) > 20, f"Token suspiciously short: {token!r}"
        print(f"\nToken acquired (first 40 chars): {token[:40]}…")

    def test_token_is_refreshed_on_second_call(self):
        """Calling _acquire_token twice returns a valid string both times."""
        t1 = _acquire_token()
        t2 = _acquire_token()
        assert t1 and t2, "One of the two token calls returned empty"

class TestAddGithubRepository:
    def test_cmdlet_help_is_readable(self):
        """Get-Help Add-GithubRepository returns syntax including required params."""
        result = run_powershell.invoke({
            "command": "Get-Help Add-GithubRepository -Full",
            "import_modules": ["Github"],
        })
        assert "Add-GithubRepository" in result, (
            f"Cmdlet not found in help output:\n{result}"
        )
        assert "serviceName" in result, (
            f"Expected -serviceName parameter in help, got:\n{result}"
        )
        assert "token" in result, (
            f"Expected -token parameter in help, got:\n{result}"
        )
        print(f"\nCmdlet help:\n{result}")

    def test_cmdlet_parameters_are_correct(self):
        """Verify serviceName is required and token is optional per the help."""
        result = run_powershell.invoke({
            "command": "Get-Help Add-GithubRepository -Full",
            "import_modules": ["Github"],
        })
        # serviceName must be required
        service_name_block = result[result.find("serviceName"):]
        assert "Required?                    true" in service_name_block, (
            "-serviceName should be Required=true"
        )
        # token must be optional
        token_block = result[result.find("-token"):]
        assert "Required?                    false" in token_block, (
            "-token should be Required=false"
        )
