# Trevorism Security Model

Concise implementation guide for Trevorism JWT security in Micronaut services.

## Core libraries

| Library | Purpose |
|---|---|
| `com.trevorism:secure-utils` | `@Secure`, `Roles`, `Permissions`, claims parsing |
| `com.trevorism:micronaut-security-utils` | Micronaut auth fetcher + security rule |

`TrevorismSecurityRule` replaces Micronaut `SecuredAnnotationRule`.

## Non-negotiable conventions

- Use `@Secure` (`com.trevorism.secure.Secure`), not Micronaut `@Secured`.
- Issuer must be `https://trevorism.com`.
- Endpoints with no `@Secure` are public.
- Signing key is read from `secrets.properties`; never hardcode it.

## JWT claims mapped into `Authentication.getAttributes()`

| JWT key | Attribute key | Notes |
|---|---|---|
| `sub` | `subject` | Identity |
| `iss` | `issuer` | Must match Trevorism issuer |
| `aud` | `audience` | `Set<String>` |
| `dbId` | `id` | Entity id |
| `role` | `role` | `admin/user/system/tenant_admin/internal` |
| `permissions` | `permissions` | String of chars (e.g. `CRUD`) |
| `entityType` | `type` | Entity type |
| `tenant` | `tenant` | Tenant GUID |

## `@Secure` quick reference

```java
@Secure(value = Roles.USER, authorizeAudience = false, allowInternal = false, permissions = "")
```

| Field | Meaning |
|---|---|
| `value` | Minimum role requirement |
| `authorizeAudience` | Require token `aud` to contain `clientId` |
| `allowInternal` | Allow `role == "internal"` |
| `permissions` | Required permission characters |

Permission chars: `C`, `R`, `U`, `D`, `E`.

## Role hierarchy

| Required `@Secure` role | Accepted token role(s) |
|---|---|
| `Roles.ADMIN` | `admin` |
| `Roles.SYSTEM` | `admin`, `system` |
| `Roles.TENANT_ADMIN` | `admin`, `system`, `tenant_admin` |
| `Roles.USER` | any non-empty role |
| `Roles.INTERNAL` | internal only when `allowInternal=true` |

## Role selection decision matrix

| Endpoint intent | Recommended annotation | Notes |
|---|---|---|
| Public health/info endpoint | *(no `@Secure`)* | Public by design |
| Any logged-in user can access | `@Secure(Roles.USER)` | Default authenticated route |
| Admin-only operation | `@Secure(Roles.ADMIN)` | Strictest standard role |
| Service-to-service API | `@Secure(Roles.SYSTEM)` | Allows `admin` + `system` |
| Tenant admin operation | `@Secure(Roles.TENANT_ADMIN)` | Tenant-aware privileged operation |
| Needs audience lock | `@Secure(value = Roles.USER, authorizeAudience = true)` | Enforces `aud` contains `clientId` |
| Needs CRUD capability gating | `@Secure(value = Roles.USER, permissions = "CR" /* etc */)` | Require exact permission chars |
| Allow long-lived internal token | `@Secure(value = Roles.USER, allowInternal = true)` | Use sparingly |
| Internal + audience + permission | `@Secure(value = Roles.USER, authorizeAudience = true, allowInternal = true, permissions = "C")` | Most constrained combined case |

## Runtime flow

### Authentication (`TrevorismAuthenticationFetcher`)

1. Token source priority: `Authorization: Bearer <token>` then `session` cookie.
2. Verify JWT with `signingKey` from `secrets.properties`.
3. Reject issuer mismatch.

### Authorization (`TrevorismSecurityRule`)

1. No `@Secure` -> allow.
2. With `@Secure` -> validate role hierarchy, issuer, optional audience, optional permissions.
3. Any failure -> `AuthenticationFailedException` -> `401`.

## Required config

### `secrets.properties`

| Key | Purpose |
|---|---|
| `signingKey` | JWT verification key (required) |
| `clientId` | Required when `authorizeAudience=true` |

### `.env`

| Variable | Purpose |
|---|---|
| `TREVORISM_TENANT_GUID` | Tenant context |
| `TREVORISM_USERNAME` | Service account user |
| `TREVORISM_PASSWORD` | Service account password |

## Minimal usage example

```groovy
import com.trevorism.secure.Roles
import com.trevorism.secure.Secure

@Controller('/myResource')
class MyResourceController {

    @Get('/')
    @Secure(Roles.USER)
    def list() { ... }

    @Post('/')
    @Secure(value = Roles.SYSTEM, permissions = "C")
    def create(Map<String, Object> body) { ... }
}
```

## Reference repos

- `https://github.com/trevorism/secure-utils`
- `https://github.com/trevorism/micronaut-security-utils`
