# Platform CLI preference

Decision rules for platform CRUD operations.

---

## Method selection (required)

1. Prefer PowerShell CLI cmdlets for platform CRUD when an equivalent cmdlet exists.
2. Use `run_in_terminal` for CLI execution and provide required modules via `import_modules`.
3. Fall back to platform web/API tools only when no equivalent cmdlet exists or CLI invocation fails due to missing command/module.
4. Do not mix CLI and API in one attempt; finish one path, then fallback if needed.

---

## CLI-first execution pattern

- Discover/confirm modules as needed (`list_available_modules`).
- Execute cmdlets through `run_in_terminal` with `import_modules`.
- For authenticated cmdlets, acquire token first with platform cmdlets, then pass token to operation cmdlet.

Example (threshold create):

```powershell
$token = Get-TrevorismUserToken -tenantGuid <tenant-guid>
Add-Threshold -name "<name>" -description "<desc>" -operator ">=" -value 4 -token $token
```

---

## API fallback requirements

When falling back to platform API tools:

1. Call `get_platform_api_spec` to verify endpoint and request shape.
2. Call `get_platform_token`.
3. Call `post_platform_api` (mutations) or `fetch_url` (reads) with `Authorization: Bearer {token}`.
4. Use exact parameter names and body schema from tool metadata and API spec.

