# Security Review

**Date:** 2026-07-27 · **Commit reviewed:** `3f268fc`

---

## SEC-1 — Live Google API key committed to public git history

**Severity: CRITICAL · Status: code fixed, KEY REVOCATION STILL REQUIRED**

### What happened

`data_scout.py` line 8, introduced in commit `87315c3` (2025-10-18):

```python
API_KEY = "AIzaSyD****************************Z3Z8  # masked"
```

Commit `3f268fc` replaced the literal with `"KEY HERE"`.

### Why the "fix" did not fix it

Git stores history immutably. The key is still retrievable by anyone:

```bash
git show 87315c3:data_scout.py | grep API_KEY
```

It is also served by the GitHub REST API, mirrored in forks and clones, and
present in any cached copy. The repository is public.

Automated scrapers monitor GitHub for the `AIza[0-9A-Za-z_-]{35}` pattern
continuously; keys pushed to public repositories are typically found and tested
within minutes. **Assume this key is compromised.**

### Impact

- Unauthorised API calls billed to the owner's Google Cloud account
- Quota exhaustion, denying service to the legitimate application
- If the key is unrestricted, access to any other Google API enabled on the project

### Remediation

**Required, and not doable from code:**

1. **Revoke immediately** at <https://aistudio.google.com/apikey>. This is the
   only action that stops abuse. Do it before anything else.
2. Create a replacement key. Apply API restrictions (Generative Language API
   only) and, where possible, application restrictions.
3. Review billing for unexpected usage since 2025-10-18.
4. Optionally rewrite history with `git filter-repo --replace-text`. This
   invalidates forks and does **not** un-leak the key — revocation is what
   matters.

**Done in this PR:**

- Key resolved from `GEMINI_API_KEY` / `GOOGLE_API_KEY` at call time, never from source
- Placeholder strings (`"KEY HERE"`, `"YOUR_API_KEY"`, …) explicitly rejected, so a
  half-configured run fails with a clear message instead of sending a bogus key
- `.gitignore` covers `.env`, `*.key`, `credentials.json`, `service-account*.json`
- `.env.example` documents configuration without carrying a secret
- A CI job (in `docs/ci/`, ready to enable) fails the build on any `AIza…` literal
- `tests/test_config_and_cli.py::TestNoSecretsInSource` asserts the same locally

---

## SEC-2 — Destructive operations at import time

**Severity: HIGH · Status: fixed**

`database_setup.py` executed four `DROP TABLE` statements at module scope with
no `__main__` guard. Any import — a REPL, a test collector, an IDE indexer, a
future web layer — irrecoverably destroyed the database. No backup, no
confirmation, no warning.

**Fixed:** migrations are idempotent and additive; `DROP TABLE` requires an
explicit `--force-reset`; all execution sits behind a `__main__` guard.

---

## SEC-3 — Unvalidated model output written to a URL column

**Severity: MEDIUM · Status: fixed**

`official_website` was written straight from model output with no validation. A
model can emit anything there — the sentinel string, prose, or a link to an
attacker-controlled domain that looks plausible. Any consumer rendering that
column as a hyperlink would present it to users as the official government site.

**Fixed:** `validate_url()` requires a well-formed `http(s)` URL with no
whitespace and a dot in the host; anything else leaves the column untouched.
`gjter verify` flags any non-URL value that predates the fix.

---

## SEC-4 — Bare `except Exception` masking failures

**Severity: MEDIUM · Status: fixed**

Two bare handlers (`data_scout.py:69`, `:135`) caught everything — including
`KeyboardInterrupt`-adjacent conditions, auth failures, quota exhaustion and
programming errors — printed a line and continued. Operationally this means an
expired key, a revoked key and a network outage are indistinguishable, and the
run still ends with `🎉 Mission Complete!`.

**Fixed:** exceptions are classified (retryable vs terminal), logged with
context, and surfaced in the run report and the process exit code.

---

## SEC-5 — Foreign keys declared but not enforced

**Severity: MEDIUM · Status: fixed**

SQLite ignores `FOREIGN KEY` clauses unless `PRAGMA foreign_keys = ON` is set on
each connection. It never was, so all three constraints were decorative and
orphaned rows were silently accepted.

**Fixed:** pragma set in `db.connect()`, `ON DELETE CASCADE` added, orphans
cleaned during migration, and `gjter verify` runs `PRAGMA foreign_key_check`.

---

## SEC-6 — Database artefact not ignored

**Severity: LOW · Status: fixed**

No `.gitignore` existed. `jobs.db` — a build artefact — was a commit candidate,
as was any `.env` a developer created. Committing the database would also commit
whatever the model had generated, with no provenance.

**Fixed:** comprehensive `.gitignore`; CI fails if `jobs.db` is tracked.

---

---

## SEC-7 — Reverse tabnabbing via `target="_blank"`

**Severity: LOW · Status: fixed**

`details.html` opened the official-website link with `target="_blank"` and no
`rel`. The opened page receives a `window.opener` reference and can navigate the
dashboard tab elsewhere — e.g. to a credential-harvesting lookalike. Fixed by
adding `rel="noopener noreferrer"`; a test asserts it stays.

---

## SEC-8 — Debug console exposable to the network

**Severity: MEDIUM · Status: fixed**

Flask's debug mode enables the Werkzeug interactive console, which executes
arbitrary Python from the browser. Running `--debug` while bound to `0.0.0.0`
would expose remote code execution to anyone on the network. `app.py` now
refuses that combination outright.

---

## Not applicable

Assessed and found not to be issues:

- **SQL injection** — all queries use parameter binding. Column names are
  interpolated in `db.py`, but only from module-level constants, never user input.
- **Path traversal** — `--db` takes an operator-supplied path; there is no
  untrusted input surface.
- **Deserialisation** — `json.loads` only; no `pickle`, `eval` or `yaml.load`.
- **Dependency CVEs** — the core package has zero runtime dependencies. The
  optional `google-genai` extra is the vendor's current SDK. Note that the
  previously-used `google-generativeai` reached end-of-life on **2025-11-30** and
  will receive no further security fixes.

---

## Summary

| ID | Issue | Severity | Code fixed | Action still needed |
|---|---|---|---|---|
| SEC-1 | API key in git history | Critical | Yes | **Revoke the key** |
| SEC-2 | Destructive import side effect | High | Yes | — |
| SEC-3 | Unvalidated URL written | Medium | Yes | — |
| SEC-4 | Bare exception handlers | Medium | Yes | — |
| SEC-5 | Foreign keys unenforced | Medium | Yes | — |
| SEC-6 | No `.gitignore` | Low | Yes | — |
| SEC-7 | `target="_blank"` without `rel="noopener"` | Low | Yes | — |
| SEC-8 | Werkzeug debug console could bind to a public interface | Medium | Yes | — |

**One item requires human action: revoke the exposed key.** Everything else is
resolved in code and covered by tests.
