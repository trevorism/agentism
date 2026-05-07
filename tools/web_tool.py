"""HTTP tools – for fetching API docs, external resources, and calling the platform."""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
from langchain_core.tools import tool
from agentism.config import PLATFORM_BASE_URL, TREVORISM_TENANT_GUID, TREVORISM_USERNAME, TREVORISM_PASSWORD, PS_MODULE_PATH
import httpx

# Derive the platform hostname once so no org-specific string is hardcoded here.
_PLATFORM_HOST = urlparse(PLATFORM_BASE_URL).hostname or ""

# ── OpenAPI spec cache ────────────────────────────────────────────────────────
# Keyed by base URL, value is a tuple of (spec_text, cached_timestamp).
# Specs expire after 24 hours to avoid stale documentation.
_SPEC_CACHE: dict[str, tuple[str, datetime]] = {}
_SPEC_CACHE_TTL = timedelta(hours=24)

# Common Micronaut / Spring OpenAPI spec paths, tried in order.
_OPENAPI_PATHS = [
    "/swagger/swagger.yml",
    "/swagger/swagger.json",
    "/swagger-ui/swagger.json",
    "/v3/api-docs",
    "/v2/api-docs",
    "/openapi.json",
    "/openapi.yaml",
]

# ── Token cache ───────────────────────────────────────────────────────────────
# Tokens are cached in-process and refreshed when they are close to expiry.
_TOKEN_CACHE: dict[str, float | str] = {"token": "", "expires_at": 0.0}
_TOKEN_TTL_SECONDS = 55 * 60  # refresh 5 min before a typical 60-min expiry


def _validate_credentials() -> None:
    """Validate that required credentials are configured, raising if not."""
    if not TREVORISM_USERNAME or not TREVORISM_PASSWORD:
        raise RuntimeError("TREVORISM_USERNAME and TREVORISM_PASSWORD must be set")


def _acquire_token() -> str:
    """
    Obtain a platform user token by calling the PowerShell module non-interactively.
    Returns the raw token string, or raises RuntimeError on failure.
    """
    _validate_credentials()
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


@tool
def get_platform_api_spec(service_base_url: str = "", force_refresh: bool = False) -> str:
    """
    Fetch and return the OpenAPI/Swagger spec for a platform service.

    Tries common Micronaut OpenAPI paths automatically. The result is cached
    in-memory for 24 hours so repeated calls within a session are instant.

    Use this before calling any platform REST endpoint to get accurate path,
    method, and parameter information. Never guess endpoint signatures.

    Args:
        service_base_url: Base URL of the service (e.g. https://platform.example.com).
                          Defaults to PLATFORM_BASE_URL from config.
        force_refresh:    If True, bypass cached spec and re-fetch.

    Returns:
        OpenAPI spec text (YAML or JSON), a summary of found endpoints, or an error.
    """
    base = (service_base_url or PLATFORM_BASE_URL).rstrip("/")
    if not base:
        return "No service URL provided and PLATFORM_BASE_URL is not configured."

    # Check cache with TTL expiration
    if not force_refresh and base in _SPEC_CACHE:
        spec_text, cached_time = _SPEC_CACHE[base]
        if datetime.now() - cached_time < _SPEC_CACHE_TTL:
            return f"[cached] {spec_text}"
        # Spec has expired; remove it so we fetch fresh below
        del _SPEC_CACHE[base]

    headers = _auth_headers() if _PLATFORM_HOST and _PLATFORM_HOST in base else {}

    with httpx.Client(follow_redirects=True, timeout=15) as client:
        for path in _OPENAPI_PATHS:
            url = base + path
            try:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    spec = resp.text
                    _SPEC_CACHE[base] = (spec, datetime.now())
                    # Return a size-limited version to avoid flooding the context window
                    if len(spec) > 8000:
                        return spec[:8000] + f"\n\n… (truncated, full spec is {len(spec)} chars, fetched from {url})"
                    return f"# Spec from {url}\n{spec}"
            except Exception:
                continue

    return (
        f"Could not find an OpenAPI spec at {base}. "
        f"Tried: {_OPENAPI_PATHS}\n"
        "The service may not expose a spec, or it may require authentication."
    )