# CI configuration

The workflow in this directory is ready to use but **is not active yet**.

It ships here rather than at `.github/workflows/` because the automation that
opened this PR does not hold the GitHub `workflows` permission, so it cannot
create workflow files. Enabling it is a one-line move that you (or any
maintainer with write access) can do:

```bash
mkdir -p .github/workflows
git mv docs/ci/github-actions-ci.yml .github/workflows/ci.yml
git commit -m "Enable CI"
git push
```

## What it does

| Job | Purpose |
|---|---|
| `test` | Installs the package and runs the 132 tests on Python 3.9, 3.11 and 3.12 |
| `test` → lint | `ruff check` (non-blocking, `continue-on-error`) |
| `test` → smoke | Full offline end-to-end run: `init` → `scout --offline` → `verify` → `status`. Needs no API key. |
| `test` → artefact guard | Fails if `jobs.db` was committed |
| `secret-scan` | Fails on any `AIza[0-9A-Za-z_-]{35}` literal in the tree |

No secrets are required. The entire suite runs offline, which is the point of
the `offline` provider — see [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

## Note on the secret scan

The scan checks the **working tree**, not history. The key exposed at commit
`87315c3` will not trip it, and no scanner can un-leak it. That key must be
revoked manually — see [`../../reports/SECURITY.md`](../../reports/SECURITY.md).

Consider also enabling GitHub's native
[secret scanning and push protection](https://docs.github.com/en/code-security/secret-scanning),
which blocks a credential before it ever lands in a commit.
