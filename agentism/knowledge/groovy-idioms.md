# Groovy / Micronaut idioms

Rules for writing Groovy code on this platform's backend services.

---

## General Groovy style

- Attempt to use idiomatic Groovy constructs and features where they improve readability and conciseness.
- Use `def` only when the type cannot be inferred or is genuinely dynamic; prefer explicit types in method signatures.
- Prefer `?.` (safe navigation) over null checks: `user?.profile?.name` not `if (user && user.profile) { ... }`.
- Prefer `?:` (Elvis) for default values: `value ?: 'default'` not `value != null ? value : 'default'`.
- Use `collect`, `findAll`, `find`, `groupBy`, `each` over imperative loops where intent is clear.

---