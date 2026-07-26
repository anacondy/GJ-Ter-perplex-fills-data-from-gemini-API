# Architecture

## Overview

GJ-Ter turns a list of Indian government recruitment exams into a normalised,
**sourced** SQLite database. It is a batch pipeline, not a service.

```
                        ┌──────────────────────┐
   database_setup.py ──▶│  gjter.cli  (init)   │──┐
                        └──────────────────────┘  │
                        ┌──────────────────────┐  │   ┌──────────────┐
   data_scout.py ──────▶│  gjter.cli  (scout)  │──┼──▶│  gjter.db    │──▶ jobs.db
                        └──────────┬───────────┘  │   └──────┬───────┘
                                   │              │          │ read-only
                                   │              │   ┌──────▼───────┐
                                   │              │   │    app.py    │──▶ browser
                                   │              │   │  Flask + UI  │
                                   │              │   └──────────────┘
                                   │              │
                                   ▼              │
                        ┌──────────────────────┐  │
                        │   gjter.pipeline     │──┘
                        └──────────┬───────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
            ┌──────────────┐ ┌──────────┐ ┌──────────────┐
            │  providers   │ │ matching │ │  validation  │
            │ gemini/offline│ │          │ │              │
            └──────────────┘ └──────────┘ └──────────────┘
```

## Design principles

1. **The schema is a contract.** Existing table and column names are never
   renamed or dropped. New columns are additive and nullable, so any consumer
   doing `SELECT *` keeps working across upgrades.
2. **Never write an unverified claim as fact.** Every enriched row carries
   `data_source`, `source_url` and `updated_at`. If a value cannot be
   established it is the sentinel `"Information not available"`, never a guess.
3. **Fail loudly.** No bare `except`. An exam that cannot be matched confidently
   is reported as unmatched; it is not filled with a neighbour's data.
4. **Runnable with no key, no network, no cost.** The `offline` provider serves a
   curated dataset so the whole pipeline — including every write path — can be
   exercised in CI.
5. **Import must be free of side effects.** Importing any module reads no
   secret, opens no connection and touches no file.

## Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `gjter/config.py` | Settings, env resolution, API-key loading | stdlib |
| `gjter/db.py` | Schema, idempotent migrations, transactional writes | stdlib |
| `gjter/matching.py` | Map a response item to the exam that requested it | stdlib |
| `gjter/validation.py` | Parse/repair JSON, coerce to bindable scalars, validate URLs | `config` |
| `gjter/providers/base.py` | Provider interface | stdlib |
| `gjter/providers/gemini.py` | Live API: retries, backoff, prompt, refusal handling | `config`, `validation` |
| `gjter/providers/offline.py` | Curated dataset, no network | `matching` |
| `gjter/pipeline.py` | Orchestration: batch → fetch → match → write | all of the above |
| `gjter/seed.py` | The twelve base job rows, with sources | `db` |
| `gjter/cli.py` | Argument parsing and command handlers | all of the above |
| `app.py` | Flask server: routes, template context, error pages | `gjter.db`, `gjter.config` |
| `templates/` | The GJ Terminal UI (Jinja2 + vanilla JS, no build step) | — |

The dependency graph is acyclic and points inward: `cli` → `pipeline` →
`providers`/`matching`/`validation` → `config` → stdlib.

## Data model

`jobs` is the spine. Three satellite tables hang off it, each cascading on
delete.

```
jobs (1) ──< job_specs      (1:1)  eligibility rules
     (1) ──< exam_pattern   (1:1)  structure of the exam
     (1) ──< job_cutoffs    (1:N)  category-wise cutoff marks
scout_runs                         audit log, one row per run
```

### Why `job_specs` is 1:1 rather than merged into `jobs`

`jobs` describes a **post** (IAS Officer); `job_specs` describes the **exam's**
eligibility rules. Three posts share `UPSC CSE`, so the specs are logically
per-exam. Keeping them separate makes the redundancy explicit and lets the
enrichment pass rewrite them without touching the post record. A future
normalisation step could promote `exams` to its own table; the current shape is
a deliberate compromise that preserves the original schema.

### Provenance columns (added, nullable)

| Column | Meaning |
|---|---|
| `data_source` | Which provider produced the value (`curated-offline`, `gemini`) |
| `source_url` | The page the claim was taken from |
| `verified_on` | Date a human last checked it against the official source |
| `updated_at` | UTC timestamp of the last write |

### Unique constraints

- `jobs(post_name, exam_name)` — makes the seed idempotent.
- `job_specs(job_id)`, `exam_pattern(job_id)` — enforce the 1:1 relationship.
- `job_cutoffs(job_id, category, year)` — prevents duplicate cutoff rows.

## Pipeline flow

1. `SELECT DISTINCT exam_name` — 12 jobs collapse to 10 exams, so the provider
   is never asked the same question twice.
2. Chunk into batches of `batch_size` (default 5).
3. `provider.fetch_batch(names)` — with retries and backoff on the live path.
4. For each requested name, `find_best_match` against the returned records.
   No confident match ⇒ recorded as unmatched, nothing written.
5. Coerce every field to a bindable scalar; validate URLs; normalise cutoffs.
6. For each job sharing that exam, write `job_specs`, `exam_pattern` and
   `job_cutoffs` **inside one transaction**. A failure rolls back that job only.
7. Pause between batches (live provider only, skipped after the last batch).
8. Record the run in `scout_runs`.

## Matching strategy

Ordered, most-confident first:

1. **Exact** — byte-for-byte. The prompt asks the model to echo the name back.
2. **Normalised exact** — case, punctuation, accents and filler words
   (`exam`, `examination`, `test`) removed. Rejected if two candidates collapse
   to the same normalised form.
3. **Guarded fuzzy** — `difflib` ratio ≥ 0.86, **and** every short alphabetic
   token (acronym) in the target must be present in the candidate, **and** the
   runner-up must be at least 0.04 behind.

The acronym guard is the important one. `"UPSC CSE"` and `"UPSC ESE"` score
0.875 by pure character similarity — high enough to pass any cutoff loose enough
to tolerate real-world formatting noise. Requiring `{upsc, cse} ⊆ candidate`
makes the collision structurally impossible rather than tuned against.

## Web layer

`app.py` is a **read-only** consumer of the database. It never writes, so the
dashboard can be running while `gjter scout` updates the data underneath it —
WAL mode allows the concurrent reader.

| Route | Purpose |
|---|---|
| `/` | Sortable, searchable table of all posts |
| `/details/<int:job_id>` | Card grid: specs, pattern, dates, cutoffs, fee, website, vacancies |
| `/update_status` | JSON `{"updating": bool}`, polled every 2 s by the dashboard |
| `/healthz` | Liveness plus coverage counts |

A connection is opened and closed **per request**: SQLite connections cannot be
shared across threads and Flask serves on several.

`_clean()` maps sentinel strings (`"Information not available"`, `"N/A"`, `""`)
to `None` so the templates' own `or 'N/A'` fallbacks fire instead of printing
the sentinel into the UI.

### Preserving the UI

The templates are treated as a fixed design. When changing them, only defects
are in scope — every colour, font, spacing rule, animation and breakpoint is
load-bearing. See [`../reports/FRONTEND_AUDIT.md`](../reports/FRONTEND_AUDIT.md)
§6 for exactly what was and was not touched.

## Extending

### Adding a provider

Subclass `Provider`, implement `fetch_batch`, register it in
`gjter/providers/__init__.py`. The pipeline treats providers opaquely; `_is_live`
governs whether rate-limit pauses apply.

### Adding an exam

Append to `SEED_JOBS` in `gjter/seed.py` (with `source_url` and `verified_on`),
and optionally add a curated record to `gjter/data/curated_exams.json`. Re-run
`python database_setup.py` — it is idempotent and will not disturb existing rows.

### Adding a column

Append to `_ADDITIVE_COLUMNS` in `gjter/db.py` and bump `SCHEMA_VERSION`.
Never rename or drop; `migrate()` runs `ALTER TABLE ADD COLUMN` only.
