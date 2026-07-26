# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
