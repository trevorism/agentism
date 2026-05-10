"""HTTP tools – for fetching API docs, external resources, and calling the platform."""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
from langchain_core.tools import tool
from agentism.config import PLATFORM_BASE_URL, TREVORISM_TENANT_GUID, TREVORISM_USERNAME, TREVORISM_PASSWORD, PS_MODULE_PATH
import httpx

# Derive the platform hostname once so no org-specific string is hardcoded here.
_PLATFORM_HOST = urlparse(PLATFORM_BASE_URL).hostname or ""

# ── OpenAPI spec cache ─────────────────────────────────────────────────────
# Keyed by base URL, value is a tuple of (spec_text, cached_timestamp).
# Specs expire after 24 hours to avoid stale documentation.
_SPEC_CACHE: dict[str, tuple[str, datetime]] = {}
_SPEC_CACHE_TTL = timedelta(hours=24)

_OPENAPI_PATHS = [
    "/help"
]

_SPEC_LINK_PATTERN = re.compile(
    r"[\"']([^\"']*(?:/swagger/[^\"'/]+\.(?:ya?ml|json)|/swagger-ui/swagger\.json|/v3/api-docs(?:/swagger-config)?|/v2/api-docs|/openapi\.(?:json|ya?ml))[^\"']*)[\"']",
    re.IGNORECASE,
)

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


def _looks_like_openapi(text: str) -> bool:
    """Best-effort check for OpenAPI/Swagger JSON or YAML content."""
    candidate = (text or "").strip()
    if not candidate:
        return False

    try:
        obj = json.loads(candidate)
        return isinstance(obj, dict) and ("openapi" in obj or "swagger" in obj)
    except json.JSONDecodeError:
        lowered = candidate.lower()
        return ("openapi:" in lowered or "swagger:" in lowered) and "paths:" in lowered


def _extract_openapi_candidates(text: str) -> list[str]:
    """Extract likely spec/config links from HTML/JS payloads like /help or swagger-ui pages."""
    matches = _SPEC_LINK_PATTERN.findall(text or "")
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in matches:
        link = raw.strip()
        if not link or link in seen:
            continue
        seen.add(link)
        deduped.append(link)
    return deduped


def _as_absolute_url(base: str, discovered: str) -> str:
    if discovered.startswith("http://") or discovered.startswith("https://"):
        return discovered
    return f"{base}/{discovered.lstrip('/')}"


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
def post_platform_api(path: str, json_body: str | dict | list) -> str:
    """
    POST JSON to an endpoint on the platform.

    A Bearer token is acquired automatically via the configured service account.

    Args:
        path:      API path relative to the platform base URL (e.g. /api/deploy).
        json_body: JSON string or already-parsed JSON object/list to send as the request body.

    Returns:
        Response body text, or an error message.
    """
    url = f"{PLATFORM_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    if isinstance(json_body, str):
        try:
            payload = json.loads(json_body)
        except json.JSONDecodeError as e:
            return f"Invalid JSON body: {e}"
    elif isinstance(json_body, (dict, list)):
        payload = json_body
    else:
        return "Invalid JSON body: expected a JSON string, object, or list."
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
            return spec_text
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
                    if _looks_like_openapi(spec):
                        _SPEC_CACHE[base] = (spec, datetime.now())
                        # Return a size-limited version to avoid flooding the context window
                        if len(spec) > 8000:
                            return spec[:8000] + f"\n\n… (truncated, full spec is {len(spec)} chars, fetched from {url})"
                        return spec

                    # /help or swagger HTML may embed the actual spec URL; discover and try it.
                    for candidate in _extract_openapi_candidates(spec):
                        spec_url = _as_absolute_url(base, candidate)
                        try:
                            spec_resp = client.get(spec_url, headers=headers)
                            if spec_resp.status_code == 200 and _looks_like_openapi(spec_resp.text):
                                resolved_spec = spec_resp.text
                                _SPEC_CACHE[base] = (resolved_spec, datetime.now())
                                if len(resolved_spec) > 8000:
                                    return (
                                        resolved_spec[:8000]
                                        + f"\n\n… (truncated, full spec is {len(resolved_spec)} chars, fetched from {spec_url})"
                                    )
                                return resolved_spec
                        except Exception:
                            continue
            except Exception:
                continue

    return (
        f"Could not find an OpenAPI spec at {base}. "
        f"Tried: {_OPENAPI_PATHS}\n"
        "The service may not expose a spec, or it may require authentication."
    )