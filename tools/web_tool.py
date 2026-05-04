"""HTTP tools – for fetching API docs, external resources, and calling the platform."""
import subprocess
import time
from urllib.parse import urlparse
from langchain_core.tools import tool
from config import PLATFORM_BASE_URL, TREVORISM_TENANT_GUID, TREVORISM_USERNAME, TREVORISM_PASSWORD, PS_MODULE_PATH
import httpx

# Derive the platform hostname once so no org-specific string is hardcoded here.
_PLATFORM_HOST = urlparse(PLATFORM_BASE_URL).hostname or ""

# ── Token cache ───────────────────────────────────────────────────────────────
# Tokens are cached in-process and refreshed when they are close to expiry.
_TOKEN_CACHE: dict[str, float | str] = {"token": "", "expires_at": 0.0}
_TOKEN_TTL_SECONDS = 55 * 60  # refresh 5 min before a typical 60-min expiry


def _acquire_token() -> str:
    """
    Obtain a platform user token by calling the PowerShell module non-interactively.
    Returns the raw token string, or raises RuntimeError on failure.
    """
    ps_command = (
        f"$env:PSModulePath = $env:PSModulePath + ';{PS_MODULE_PATH}'; "
        f"$cred = New-Object System.Management.Automation.PSCredential("
        f"'{TREVORISM_USERNAME}', "
        f"(ConvertTo-SecureString '{TREVORISM_PASSWORD}' -AsPlainText -Force)); "
        f"Get-TrevorismUserToken -tenantGuid '{TREVORISM_TENANT_GUID}' -credential $cred"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    token = result.stdout.strip()
    if not token or result.returncode != 0:
        raise RuntimeError(
            f"Token acquisition failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return token


def _get_token(force_refresh: bool = False) -> str:
    """Return a valid cached token, refreshing automatically when near expiry."""
    now = time.monotonic()
    if force_refresh or now >= float(_TOKEN_CACHE["expires_at"]):
        _TOKEN_CACHE["token"] = _acquire_token()
        _TOKEN_CACHE["expires_at"] = now + _TOKEN_TTL_SECONDS
    return str(_TOKEN_CACHE["token"])


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_get_token()}"}


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def get_platform_token() -> str:
    """
    Acquire (or return a cached) platform authentication token.

    The token is obtained via the configured PowerShell cmdlet using
    the configured service account. Call this to verify authentication is working,
    or to force a token refresh before making API calls.

    Returns:
        The Bearer token string, or an error message.
    """
    try:
        return _get_token(force_refresh=True)
    except RuntimeError as e:
        return f"Token error: {e}"


@tool
def fetch_url(url: str, timeout: int = 30) -> str:
    """
    Fetch a URL via HTTP GET and return the response body as text.

    For platform URLs the Bearer token is attached automatically.

    Use this to:
    - Read API documentation pages
    - Check GitHub changelogs or release notes
    - Query any authenticated or public REST endpoint

    Args:
        url:     Full URL to fetch (e.g. https://your-platform.com/api/v1/info).
        timeout: Request timeout in seconds (default 30).

    Returns:
        Response body text, or an error message.
    """
    headers = _auth_headers() if _PLATFORM_HOST and _PLATFORM_HOST in url else {}
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPStatusError as e:
        return f"HTTP {e.response.status_code}: {e.response.text[:500]}"
    except Exception as e:
        return f"Request failed: {e}"


@tool
def post_platform_api(path: str, json_body: str) -> str:
    """
    POST JSON to an endpoint on the platform.

    A Bearer token is acquired automatically via the configured service account.

    Args:
        path:      API path relative to the platform base URL (e.g. /api/deploy).
        json_body: JSON string to send as the request body.

    Returns:
        Response body text, or an error message.
    """
    import json

    url = f"{PLATFORM_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        payload = json.loads(json_body)
    except json.JSONDecodeError as e:
        return f"Invalid JSON body: {e}"
    try:
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            resp = client.post(url, json=payload, headers=_auth_headers())
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPStatusError as e:
        return f"HTTP {e.response.status_code}: {e.response.text[:500]}"
    except Exception as e:
        return f"Request failed: {e}"
