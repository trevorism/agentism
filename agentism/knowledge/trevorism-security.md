# Trevorism Security Model

Rules for working with the Trevorism JWT-based security model in Micronaut services.

---

## Overview

Trevorism replaces Micronaut's default security model with a custom JWT token validation pipeline. Two libraries define the model:

| Library | Purpose |
|---|---|
| `com.trevorism:secure-utils` | Core `@Secure` annotation, `Roles`, `Permissions`, JWT claims parsing (`ClaimsProvider`, `ClaimProperties`) |
| `com.trevorism:micronaut-security-utils` | Micronaut integration — `TrevorismAuthenticationFetcher` (token extraction & JWT verification) and `TrevorismSecurityRule` (authorization enforcement) |

The security rule **replaces** Micronaut's `SecuredAnnotationRule` via `@Replaces(SecuredAnnotationRule.class)`.

---

## JWT Token Structure

Tokens are HMAC-SHA signed JWTs. The following custom claims are extracted from the payload:

| JWT Claim Key | ClaimProperties Field | Description |
|---|---|---|
| `sub` | `subject` | Identity of the token holder |
| `iss` | `issuer` | Token issuer — **must be** `"https://trevorism.com"` |
| `aud` | `audience` (Set\<String\>) | Target audience(s) for the token |
| `dbId` | `id` | Database ID of the entity |
| `role` | `role` | Role string (e.g. `"admin"`, `"user"`, `"system"`, `"tenant_admin"`, `"internal"`) |
| `permissions` | `permissions` | Permission string — a concatenation of permission chars (e.g. `"CRUD"`) |
| `entityType` | `type` | Entity type identifier |
| `tenant` | `tenant` | Tenant GUID |

All claims are placed into `Authentication.getAttributes()` as a `Map<String, Object>`.

---

## Role Hierarchy

Roles are defined in `com.trevorism.secure.Roles`:

| Role Constant | String Value | Who Can Access |
|---|---|---|
| `Roles.ADMIN` | `"admin"` | Only tokens with `role == "admin"` |
| `Roles.SYSTEM` | `"system"` | Tokens with `role == "admin"` **or** `"system"` |
| `Roles.TENANT_ADMIN` | `"tenant_admin"` | Tokens with `role == "admin"`, `"system"`, **or** `"tenant_admin"` |
| `Roles.USER` | `"user"` | Default — any authenticated token (role present and non-empty) |
| `Roles.INTERNAL` | `"internal"` | Special long-lived internal tokens (only allowed when `allowInternal = true`) |

### Role validation logic

When `@Secure(value = Roles.X)` is applied:

1. `Roles.ADMIN` — claim role must equal `"admin"`
2. `Roles.SYSTEM` — claim role must equal `"admin"` or `"system"`
3. `Roles.TENANT_ADMIN` — claim role must equal `"admin"`, `"system"`, or `"tenant_admin"`
4. `Roles.USER` — any authenticated token with a non-empty role
5. `Roles.INTERNAL` — only allowed if `allowInternal = true` on the annotation

---

## @Secure Annotation

Defined in `com.trevorism.secure.Secure`. Target: `METHOD`, retention: `RUNTIME`.

```java
@Secure(value = Roles.USER, authorizeAudience = false, allowInternal = false, permissions = "")
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `value` | `String` | `Roles.USER` | Required role for access |
| `authorizeAudience` | `boolean` | `false` | When `true`, the token's `aud` set must contain the app's `clientId` (from `secrets.properties`) |
| `allowInternal` | `boolean` | `false` | When `true`, tokens with `role == "internal"` are authorized |
| `permissions` | `String` | `""` | Permission string — each character is checked against the token's `permissions` claim. E.g. `"CR"` requires both C and R |

### Permission Characters

Defined in `com.trevorism.secure.Permissions`:

| Constant | Char | Meaning |
|---|---|---|
| `Permissions.CREATE` | `"C"` | Create |
| `Permissions.READ` | `"R"` | Read |
| `Permissions.UPDATE` | `"U"` | Update |
| `Permissions.DELETE` | `"D"` | Delete |
| `Permissions.EXECUTE` | `"E"` | Execute |

### Examples

```java
// Standard user authorization
@Secure(Roles.USER)

// Admin only
@Secure(Roles.ADMIN)

// Service-to-service
@Secure(Roles.SYSTEM)

// Tenant-scoped admin
@Secure(Roles.TENANT_ADMIN)

// Audience-restricted + internal tokens + create permission required
@Secure(value = Roles.USER, authorizeAudience = true, allowInternal = true, permissions = "C")
```

---

## Authentication Flow

`TrevorismAuthenticationFetcher` (order `-1000`) extracts tokens from two sources, in priority order:

1. **Bearer token** — `Authorization: Bearer <token>` header
2. **Session cookie** — cookie named `session`

If neither is present, returns an empty authentication (`Authentication.build("")`).

On success, the JWT is verified against the **signing key** loaded from `secrets.properties` (`signingKey` property). If the key is missing or blank, a `SigningKeyException` is thrown.

The issuer is validated — **must be** `"https://trevorism.com"`. Any other issuer causes rejection.

---

## Authorization Flow

`TrevorismSecurityRule` (order `-1000`) replaces `SecuredAnnotationRule`. It:

1. Checks if the route has a `@Secure` annotation
2. If **no** `@Secure` annotation → `SecurityRuleResult.ALLOWED` (public endpoint)
3. If **yes** → validates claims against the annotation:
   - Verifies authentication exists and has roles
   - Validates issuer is `"https://trevorism.com"`
   - Validates role hierarchy (see Role Hierarchy above)
   - Optionally validates audience against `clientId` from `secrets.properties`
   - Optionally validates each permission character in the annotation against the token's permissions claim

If any validation fails, `AuthenticationFailedException` is thrown → Micronaut returns **401 Unauthorized**.

---

## Configuration

### Required properties (in `secrets.properties` on the classpath)

| Property | Description |
|---|---|
| `signingKey` | HMAC-SHA signing key (BASE64-encoded). Required for JWT verification. |
| `clientId` | App identifier. Used when `authorizeAudience = true` to validate the token's audience. |

### Environment variables (`.env`)

| Variable | Description |
|---|---|
| `TREVORISM_TENANT_GUID` | Tenant GUID for multi-tenant scenarios |
| `TREVORISM_USERNAME` | Service account username |
| `TREVORISM_PASSWORD` | Service account password |

---

## Adding Security to a Controller

### Step 1: Add the dependency

```groovy
dependencies {
    implementation 'com.trevorism:micronaut-security-utils:<version>'
    implementation 'com.trevorism:secure-utils:<version>'
}
```

### Step 2: Annotate controller methods

```groovy
import com.trevorism.secure.Roles
import com.trevorism.secure.Secure

@Controller('/myResource')
class MyResourceController {

    @Get(value = "/", produces = MediaType.APPLICATION_JSON)
    @Secure(Roles.USER)
    def list() { ... }

    @Get(value = "{id}", produces = MediaType.APPLICATION_JSON)
    @Secure(Roles.ADMIN)
    def getById(String id) { ... }

    @Post(value = "/", produces = MediaType.APPLICATION_JSON, consumes = MediaType.APPLICATION_JSON)
    @Secure(value = Roles.SYSTEM, permissions = "C")
    def create(Map<String, Object> body) { ... }
}
```

### Step 3: Ensure `secrets.properties` is on the classpath

Place `secrets.properties` in `src/main/resources/` (or configure via `ClasspathBasedPropertiesProvider` constructor).

---

## Common Patterns

### Public endpoint (no authentication)

```groovy
@Get(value = "/health", produces = MediaType.TEXT_PLAIN)
def health() { "pong" }
```

No `@Secure` annotation → always allowed.

### Service-to-service call

```groovy
@Secure(Roles.SYSTEM)
```

Allows both `admin` and `system` role tokens.

### Tenant-scoped access

```groovy
@Secure(Roles.TENANT_ADMIN)
```

Allows `admin`, `system`, and `tenant_admin` role tokens. The `tenant` claim from the JWT is available via `authentication.getAttributes().get("tenant")`.

### Audience-restricted access

```groovy
@Secure(value = Roles.USER, authorizeAudience = true)
```

Token's `aud` set must contain the app's `clientId` from `secrets.properties`.

### Permission-restricted access

```groovy
@Secure(value = Roles.USER, permissions = "CRUD")
```

Token's `permissions` claim must contain all of `C`, `R`, `U`, `D`.

### Combined: audience + internal + permissions

```groovy
@Secure(value = Roles.USER, authorizeAudience = true, allowInternal = true, permissions = "C")
```

Allows:
- Regular user tokens whose `aud` contains `clientId`
- Internal tokens (`role == "internal"`)
- All of the above must have `C` in their `permissions` claim

---

## Error Handling

Validation failures throw `com.trevorism.AuthenticationFailedException` with a message. Micronaut translates this to **401 Unauthorized**.

| Failure | Message |
|---|---|
| No roles in token | `"Unable to parse incoming token; cannot find identity's role"` |
| No `@Secure` on method | `"Unable to validate against a method without the @Secure annotation"` |
| Wrong issuer | `"Unexpected issuer: ${issuer}"` |
| Role insufficient | `"Insufficient access"` |
| Audience mismatch | `"Audience not found in token"` |
| Permission missing | `"Insufficient access"` |
| Missing signing key | `SigningKeyException("Unable to retrieve signing key from properties file")` |

---

## Key Conventions

- **Never** use Micronaut's default `@Secured` — always use `@Secure` from `com.trevorism.secure`.
- **Never** hardcode the signing key — it comes from `secrets.properties`.
- **Never** assume a token is valid — always check the issuer is `"https://trevorism.com"`.
- Controllers with no `@Secure` are **public** — no authentication required.
- The `@Secure` annotation defaults to `Roles.USER` — any authenticated user.
- Use `authentication.getAttributes().get("tenant")` to access the tenant claim.
- Use `authentication.getAttributes().get("permissions")` to access the permissions claim.
- Use `authentication.getAttributes().get("audience")` to access the audience claim.
- Use `authentication.getAttributes().get("subject")` to access the subject claim.
- Use `authentication.getAttributes().get("id")` to access the dbId claim.

---

## Reference Repositories

| Repository | URL |
|---|---|
| `secure-utils` | https://github.com/trevorism/secure-utils |
| `micronaut-security-utils` | https://github.com/trevorism/micronaut-security-utils |
