# Platform overview

Describes the technology stack and repo structure for this platform.
Update this file as the stack evolves.

---

## Technology stack

| Layer | Technology                                                                          |
|---|-------------------------------------------------------------------------------------|
| Backend | Groovy, Micronaut framework                                                         |
| Frontend | Vue 3, Vuestic, Javascript, Tailwind                                                |
| Backend tests | Junit (Groovy) unit tests in src/main/test, Cucumber Groovy (BDD) in src/acceptance |
| Frontend tests | Vitest                                                                              |
| CI / hosting | GitHub Actions, GitHub-hosted repos                                                 |
| Client tooling | PowerShell                                                                          |
---

## Repo conventions

- Each service/module lives in its own GitHub repository.
- Backend repos follow standard Gradle project layout (`src/main/groovy/`, `src/test/groovy/`).
- A service optionally has a frontend. Frontend code lives in `src/app` within the same repo, built with Vite.

