# API conventions

Rules for designing and calling REST APIs on this platform.

---

## URL design

- All paths are kebabCase: `/userProfiles` or `/reportRuns`.
- Nest related resources: `/projects/{id}/members`, not a flat `/project-members?projectId=`.
- Use `GET /resource` for lists, `GET /resource/{id}` for single items. Avoid RPC-style paths like `/getUser`.

### CRUD/Operation endpoints
- `POST /` — Executes the operation or creates an object using a typed JSON request body.
- `GET /` — Lists all objects of this type'
- `GET /{id}` — Retrieves the result or state of a type.
- `PUT /{id}` — Idempotent updates.
- `DELETE /{id}` — Deletes a type.

### Context Root Conventions
- `GET /ping` — Returns plain text `"pong"` to verify the service is alive.
- `GET /help` — Redirects to the Swagger UI.
- Contained in a `RootController.groovy`
- `Get /` -- Contains links to ping and help endpoints. There is always an endpoint at the context root of the service.

---

## Request / response shape

- All request and response bodies are JSON; never plain text or form-encoded for API calls.
- Timestamps are ISO-8601 UTC strings: `"2024-03-01T12:00:00Z"`, represented using java.util.Date
- Objects have an id field of type String

---

## HTTP status codes

| Scenario | Code |
|---|---|
| Created resource | 201 |
| No content (delete) | 204 |
| Validation failed | 400 |
| Unauthorised | 401 |
| Forbidden | 403 |
| Not found | 404 |
| Conflict (duplicate) | 409 |
| Internal error | 500 |

---

## Security

- All non-public endpoints require an `Authorization: Bearer <token>` header.
- Controller endpoints are annotated with `@Secure` to enforce authentication. It has a value for the required role.
- Roles are `Roles.ADMIN` (only admins), `Roles.USER` (any authenticated user), `Roles.SYSTEM` (service-to-service calls). Example: `@Secure(value = Roles.USER)`.
- Controllers that pass through requests to downstream services inject `SecureHttpClient` via constructor.
- Never log request bodies or authorization headers.
- Platform tokens are read from environment variables; never hardcode them.

---

### Documentation

- Endpoints have a @Tag and @Operation annotation for Swagger documentation.
- Secured operations include `**Secure` at the end of their `@Operation(summary = "...")` text to indicate the endpoint requires authentication.

---

## Controller patterns

### Structure

- Controllers are annotated `@Controller('/path')` and methods with `@Get`, `@Post`, `@Put`, `@Delete`.
- POST operation endpoints use `@Post(value = "/", produces = MediaType.APPLICATION_JSON, consumes = MediaType.APPLICATION_JSON)`.
- GET by-id endpoints use `@Get(value = "{id}", produces = MediaType.APPLICATION_JSON)`.
- Controllers use `@Tag(name = "... Operations")` and `@Operation(summary = "...")` annotations.

### Service pattern

- Each controller delegates to a service interface.
- Services have an implementation class constructed in the controller constructor.
- Services take `SecureHttpClient` in their constructor for pass-through authentication.

### Error handling

- Use `log.error()` with `LoggerFactory.getLogger(Class.name)` for error logging; never use `println`.
- Validation errors throw `HttpResponseException(400, e.message)`.

### Generic CRUD pattern

Controllers providing generic resource management follow these conventions:
- Uses `@Status(HttpStatus.CREATED)` on POST endpoints to return 201.
- Accepts `Map<String, Object>` as the request body for generic resource creation/update.
- Uses `Optional<String>` for optional query parameters.
---
