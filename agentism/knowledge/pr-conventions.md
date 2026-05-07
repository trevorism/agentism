# PR and branch conventions

Rules for creating and merging pull requests on this platform.

---

## Branch naming

Format: `<type>/<short-slug>`

| Type prefix | When to use |
|---|---|
| `feature/` | New functionality |
| `fix/` | Bug fix |
| `chore/` | Non-functional: deps, config, CI |
| `refactor/` | Code restructuring without behaviour change |
| `test/` | Test-only changes |

Examples:
- `feature/add-user-export`
- `fix/null-pointer-on-empty-list`
- `chore/upgrade-micronaut`

---

## Commit messages

- Format: `<short description>`
- Description: imperative mood, lowercase, no period at end
- Always prefix with `Closes #<N>` or `Refs #<N>` in the commit message body when the commit relates to an issue.

---

## PR description template

```
## Summary
<What this PR does in 2–3 sentences>

## Changes
- <File or module>: <what changed and why>

## Validation
- Tests run: `<command>`
- Test result: <pass/fail count>
- Manual steps (if any): <steps>

## Risks / rollback
<Any concerns, or "Low risk / revert by reverting this commit">

Closes #<issue-number>
```

---

## PR rules

- Always target `master` as the base branch.
- PRs must pass all tests before merge.
- Request review only when tests pass and PR description is complete.
- Use squash merge to keep master history clean.
- After a successful merge, always run `git_sync_master` to update the local checkout.

