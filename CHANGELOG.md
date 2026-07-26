# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.1] — 2026-07-27

### Fixed

- **`UnicodeEncodeError` crashed the app on Windows.** Git Bash and older
  PowerShell consoles default to cp1252, which cannot encode `₹` or `→`.
  `python app.py` died on its startup banner and `gjter export` died on the
  first salary field. Added `gjter/console.py`, which switches the console to
  UTF-8 and transliterates (`₹`→`Rs.`) where it cannot. Regression tests
  simulate a cp1252 stream.
- `scripts/run_dashboard.sh` continued after a failed `pip install`, producing a
  confusing downstream error. It now stops and explains the fix, with specific
  guidance for externally-managed Python environments.

### Added

- **`scripts/run_dashboard.sh`** — one command to install Flask, build the
  database, verify it and serve the UI. Works in Git Bash on Windows.
- **`docs/RUNNING.md`** — step-by-step run instructions and a troubleshooting
  section covering port conflicts, missing Flask, empty tables and the
  UTF-16 paste error Git Bash reports as `$'\377\376[': command not found`.

## [1.1.0] — 2026-07-27

Frontend release. The dashboard templates were supplied after 1.0.0 and had
never been committed, along with the server they require. Full analysis in
[`reports/FRONTEND_AUDIT.md`](reports/FRONTEND_AUDIT.md).

### Fixed

- **JavaScript parse error disabled the entire dashboard.** Four calls in
  `sortTableByColumn` were written as ``a.querySelector`td:nth-child(${n})`)``
  — a backtick opening a tagged template plus an unmatched `)`. Confirmed with
  `node --check`. Because a parse error aborts the whole `<script>` block, this
  killed sorting, `Ctrl+K` search, arrow-key scrolling, row-click navigation and
  the status poller. Every interactive feature on the page was dead.
- **Numeric sorting produced fabricated values.** `replace(/[₹,+-]/g,'')` strips
  hyphens, so `"21-32 years"` parsed as **2132**, and `"N/A"` became `NaN`,
  making the comparator non-transitive. Now extracts the first number and sorts
  unparseable cells last.
- **Two cards could never show data.** `details.html` reads `application_fee`,
  `vacancies` and `vacancies_year`; none existed in the schema, so the Fee and
  Vacancies cards were permanently stuck on their fallback text.
- `target="_blank"` links had no `rel="noopener noreferrer"`.
- The website card could render `"Information not available"` as a live link.

### Added

- **`app.py`** — the Flask server the templates required. Routes: `/`,
  `/details/<int:job_id>`, `/update_status`, `/healthz`. Supplies every variable
  the templates reference.
- **`templates/index.html`, `templates/details.html`** — committed for the
  first time. Visual design preserved byte-for-byte.
- **Schema v3**: `jobs.application_fee`, `jobs.vacancies`, `jobs.vacancies_year`
  (nullable, additive), populated with verified 2025 figures and sources.
- **`scripts/purge_key_from_history.sh`** — tested, verified procedure to remove
  the leaked key from all git history, with backup, dry-run and per-blob
  verification.
- Styled 404/503 error pages; a 503 names `database_setup.py` when the database
  is missing rather than showing a traceback.
- `Cache-Control: no-store` on `/update_status`; thread-safe update flag.
- Refuses `--debug` on a non-loopback host (Werkzeug's console is RCE).
- 25 web tests (157 total), including a `node --check` assertion on the
  rendered JavaScript.
- `web` optional dependency group: `pip install -e ".[web]"`.

### Changed

- `reports/CODE_AUDIT.md` corrected: it claimed no frontend existed. Total
  findings across both audits: **42**.
- Both audit reports had quoted the leaked API key verbatim; now masked.

## [1.0.0] — 2026-07-27

Repair and hardening release. The two original entry points behave the same from
the outside; everything beneath them was rebuilt. Full analysis in
[`reports/CODE_AUDIT.md`](reports/CODE_AUDIT.md).

### Security

- **API key removed from source.** Resolved from `GEMINI_API_KEY` /
  `GOOGLE_API_KEY` at call time. Committed placeholders such as `"KEY HERE"` are
  rejected so a half-configured run fails clearly instead of sending a bogus key.
  ⚠️ **The key previously committed at `87315c3` is still in git history and must
  be revoked manually** — see [`reports/SECURITY.md`](reports/SECURITY.md).
- Added `.gitignore` covering `.env`, `*.key`, credentials files and `*.db`.
- CI fails the build on any `AIza…` literal; a unit test asserts the same locally.
- `official_website` is validated as a real URL before being stored, so model
  output can no longer place arbitrary text in a column consumers render as a link.

### Fixed

- **Wrong exam data written to the wrong exam.** `difflib` cutoff of 0.4 let
  `UPSC CSE` match `UPSC ESE` (similarity 0.875), and the substring fallback
  tested `'' in name`, which is always true — so any response item with a blank
  `exam_name` was applied to the first exam that asked. Replaced with exact →
  normalised → acronym-guarded fuzzy matching that rejects ambiguous ties.
- **`database_setup.py` destroyed the database on import.** `DROP TABLE` ran at
  module scope with no `__main__` guard. Migrations are now idempotent and
  additive; destruction requires `--force-reset`.
- **Nested JSON values aborted writes.** Lists and dicts raised
  `sqlite3.InterfaceError`, which was caught and mislabelled as a database error,
  leaving rows deleted but not replaced. All values are now flattened to
  bindable scalars.
- **Blocked and truncated responses were silently swallowed.** `response.text`
  raises when a candidate is filtered or hits `MAX_TOKENS`; the bare `except`
  turned that into an empty batch and a success message. Finish reason and
  safety feedback are now surfaced.
- **Foreign keys were not enforced.** `PRAGMA foreign_keys = ON` is now set per
  connection; `ON DELETE CASCADE` added; orphans cleaned during migration.
- **Partial writes on failure.** Commit happened once per batch after swallowing
  per-job errors. Each job now writes in its own transaction.
- **Transaction rollback did not work.** The sqlite3 module's implicit
  transaction handling made `BEGIN IMMEDIATE` fail, so the rollback path was
  never reached. Connections now use `isolation_level=None` with explicit
  transaction control and SAVEPOINT-based nesting.
- **Positional inserts.** `INSERT INTO t VALUES (NULL,?,…)` would silently
  misalign every value if a column were added. All inserts now name columns.
- **~30 % of API calls were redundant.** Batches were built from job rows, so
  `UPSC CSE` was requested three times per batch. Batching now runs over
  distinct exam names.
- Removed the 30-second sleep after the final batch.
- Connections are closed in `finally` blocks.

### Added

- `gjter` package: `config`, `db`, `matching`, `validation`, `pipeline`, `seed`,
  `cli`, and a `providers` sub-package.
- **Offline provider** — a curated, source-checked dataset covering all ten
  exams. Runs the full pipeline with no API key, no network and no cost.
- `--dry-run`, `--only`, `--limit`, `--batch-size`, `--pause`, `--max-retries`.
- New commands: `gjter status`, `gjter export`, `gjter verify`.
- Retry with exponential backoff and jitter; errors classified retryable vs terminal.
- **Provenance columns** on every enriched table: `data_source`, `source_url`,
  `verified_on`, `updated_at`.
- `scout_runs` audit table.
- Unique constraints: `jobs(post_name, exam_name)`, `job_specs(job_id)`,
  `exam_pattern(job_id)`, `job_cutoffs(job_id, category, year)`.
- **132 tests**, covering every critical and high-severity finding as a
  regression test. No network required.
- CI workflow for Python 3.9/3.11/3.12 with an offline end-to-end smoke test
  and a secret scan, provided in `docs/ci/` ready to enable.
- `pyproject.toml` (core has **zero** runtime dependencies; Gemini is an extra).
- Documentation: `docs/ARCHITECTURE.md`, `docs/SCHEMA.md`, `docs/DATA_SOURCES.md`,
  `reports/CODE_AUDIT.md`, `reports/SECURITY.md`, and a real README.

### Changed

- **Seed data corrected against official sources.** 15 field-level errors across
  8 posts, including LIC AAO salary understated by more than half (₹40,000+ vs
  ₹88,635), ISRO and DRDO age limits inverted, and SSC CGL AAO marked
  Non-Gazetted when it is Group B Gazetted. Each row now carries `source_url`
  and `verified_on`. Full table in `reports/CODE_AUDIT.md` §5.
- `pay_level` is now NULL for posts not on the 7th CPC matrix (RBI, SBI, IBPS,
  LIC) instead of carrying an invented number.
- `salary` states entry **basic pay** explicitly rather than a `₹NN,NNN+` figure
  that conflated basic and gross.
- Default model changed from `gemini-2.5-pro` to `gemini-2.5-flash`;
  `temperature` pinned to 0.
- Prefers the current `google-genai` SDK; falls back to `google-generativeai`
  (end-of-life 2025-11-30) with a warning.
- Prompt rewritten to forbid invention and to request a source URL per record.
- `print` replaced with `logging` for diagnostics; stdout reserved for progress.

### Compatibility

- All original table and column names are preserved. New columns are nullable,
  so `SELECT *` consumers are unaffected.
- `python database_setup.py` and `python data_scout.py` work as before.
- Databases created by the previous version migrate in place with no data loss
  (`tests/test_db.py::test_migrate_upgrades_a_legacy_database`).

---

## [0.1.0] — 2025-10-18

Initial version: `data_scout.py` and `database_setup.py`.
