# Testing patterns

Rules for writing and running tests on this platform.

---

## Test types and tools

| Layer                    | Tool                    | Location                |
|--------------------------|-------------------------|-------------------------|
| Backend unit/integration | Junit (Groovy)          | `src/test/groovy/`      |
| Frontend unit            | Vitest                  | `src/app/*.spec.ts`     |
| End-to-end / BDD         | Cucumber + Groovy steps | `src/acceptance/groovy/` |
| Python tests             | pytest                  | `test/*.py`             |
---

## Vitest conventions

- Test files are located in `src/app/test` and mirror the source structure of `src/app`.
- Use `describe` / `it` blocks; never naked `test()` at file scope.
- Mock external API calls with `vi.mock`; never let tests hit real network endpoints.
- Assert on rendered output, not on implementation details (avoid asserting internal state).

---

## Cucumber conventions

- Feature files are human-readable; no implementation detail in `.feature` files.
- Step definitions live in `src/acceptance/resources/features/`.
- Shared state between steps uses a `ScenarioContext` passed via constructor injection.
- Use `Background:` for preconditions shared across all scenarios in a feature.

---

## Gradle/JDK mismatch policy

- If local Gradle output contains `Unsupported class file major version`, do not stop after the first failure.
- Retry once after clearing sticky JVM env vars and stopping Gradle daemons.
- For retry, prefer a compatible lower JDK home when multiple JDKs are installed.
- Only report local verification as blocked after this recovery retry also fails.

