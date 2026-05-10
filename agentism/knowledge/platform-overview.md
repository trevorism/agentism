# Platform overview

Describes the technology stack and repo structure for this platform.
Update this file as the stack evolves.

---

## Technology stack

| Layer          | Technology                                                                          |
|----------------|-------------------------------------------------------------------------------------|
| Backend        | Groovy, Micronaut framework                                                         |
| Frontend       | Vue 3, Vuestic, Javascript, Tailwind                                                |
| Backend tests  | Junit (Groovy) unit tests in src/main/test, Cucumber Groovy (BDD) in src/acceptance |
| Frontend tests | Vitest                                                                              |
| CI / hosting   | GitHub Actions, GitHub-hosted repos                                                 |
| Client tooling | PowerShell                                                                          |
| AI/ML          | Python                                                                              |
---

## Repo conventions

- Each service/module lives in its own GitHub repository.
- Backend repos follow standard Gradle project layout (`src/main/groovy/`, `src/test/groovy/`).
- A service optionally has a frontend. Frontend code lives in `src/app` within the same repo, built with Vite.

---

## Deployment URL resolution

Use these rules before any platform web/API call:

1. Do not guess a host from `trevorism.com` root.
2. Resolve the deployed base URL from repo docs/config first (`README.md`, `ContextRoot.feature`, deployment workflow files).
3. If unresolved but the operation is an action service, prefer the `*.action.trevorism.com` host pattern.
4. For threshold operations, use `https://threshold.action.trevorism.com` as the service base URL unless repo/config explicitly says otherwise.
5. Prefer `<service-base>/help` for docs discovery; it reliably redirects or links to Swagger/OpenAPI resources.
6. Call `get_platform_api_spec` against the resolved base URL before endpoint calls.

