# Database Schema

SQLite. Current `user_version`: **3**.

Legacy columns from the original schema are preserved exactly. Everything added
is nullable, so a consumer doing `SELECT *` continues to work.

---

## `jobs`

One row per **post**. The spine of the database.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | autoincrement |
| `post_name` | TEXT | e.g. `IAS Officer`. Part of the natural key. |
| `exam_name` | TEXT | e.g. `UPSC CSE`. Part of the natural key. Several posts may share one exam. |
| `conducting_body` | TEXT | `UPSC`, `SSC`, `RBI`, … |
| `group` | TEXT | Quoted — `group` is a SQL keyword. `A`, `B`, or a scale name for bank/corporation posts. |
| `gazetted_status` | TEXT | `Gazetted`, or an explicit "not applicable" for non-government-service posts |
| `pay_level` | INTEGER | 7th CPC pay matrix level. **NULL where the post is not on the matrix** (bank and corporation scales). |
| `salary` | TEXT | Entry **basic pay**, stated as such. Not gross. |
| `eligibility` | TEXT | Short form; the full rule lives in `job_specs.edu_qual` |
| `age_limit` | TEXT | Short form, including the reckoning date |
| `pet_status` | TEXT | Physical efficiency test requirement |
| `application_start` | TEXT | ISO date, nullable — varies per cycle |
| `application_end` | TEXT | ISO date, nullable |
| `exam_date` | TEXT | ISO date, nullable |
| `official_website` | TEXT | Validated `http(s)` URL, or NULL. Never a sentinel string. |
| `application_fee` | TEXT | *added v3* — read by `details.html`; the column did not exist before, so the Fee card could only show its fallback |
| `vacancies` | TEXT | *added v3* — read by `details.html`, same story |
| `vacancies_year` | TEXT | *added v3* — the cycle `vacancies` refers to |
| `source_url` | TEXT | *added* — where the row was verified |
| `data_source` | TEXT | *added* — `curated-offline`, `gemini` |
| `verified_on` | TEXT | *added* — ISO date of last human check |
| `updated_at` | TEXT | *added* — UTC ISO timestamp of last write |

**Unique:** `(post_name, exam_name)` — makes seeding idempotent.
**Index:** `exam_name`.

---

## `job_specs` — eligibility (1:1 with a job)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `job_id` | INTEGER NOT NULL | → `jobs(id)` ON DELETE CASCADE. **Unique.** |
| `nationality` | TEXT | Who may apply, by citizenship |
| `age_limits` | TEXT | Unreserved band plus the reckoning date |
| `age_relax` | TEXT | Category-wise relaxations |
| `edu_qual` | TEXT | Minimum qualification |
| `attempts` | TEXT | Attempt limits by category |
| `physical_std` | TEXT | Physical/medical standards, or that none apply |
| `data_source`, `source_url`, `updated_at` | TEXT | *added* — provenance |

---

## `exam_pattern` — exam structure (1:1 with a job)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `job_id` | INTEGER NOT NULL | → `jobs(id)` ON DELETE CASCADE. **Unique.** |
| `stages` | TEXT | Selection stages in order |
| `num_papers` | TEXT | Papers per stage |
| `q_type` | TEXT | Objective, descriptive, or the mix |
| `duration` | TEXT | Time per paper |
| `marking_scheme` | TEXT | Totals and negative marking |
| `data_source`, `source_url`, `updated_at` | TEXT | *added* — provenance |

---

## `job_cutoffs` — cutoff marks (1:N with a job)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `job_id` | INTEGER NOT NULL | → `jobs(id)` ON DELETE CASCADE |
| `category` | TEXT | `General`, `EWS`, `OBC`, `SC`, `ST`, `PwBD-n` |
| `score` | TEXT | TEXT, not REAL — cutoffs are published in incompatible units (marks out of 200, aggregate marks, normalised scores) |
| `year` | TEXT | Exam year the cutoff refers to |
| `data_source`, `source_url`, `updated_at` | TEXT | *added* — provenance |

**Unique:** `(job_id, category, year)`.

> Rows exist only where the conducting body **publishes** official cutoffs.
> SSC, IBPS, LIC, SBI, ISRO and DRDO largely do not, in this form; those exams
> have zero cutoff rows by design. An empty result is correct, not missing data.

---

## `scout_runs` — audit log

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `started_at` / `finished_at` | TEXT | UTC ISO timestamps |
| `provider` / `model` | TEXT | Which backend produced this run |
| `jobs_seen` / `jobs_updated` / `jobs_failed` | INTEGER | Counters |
| `dry_run` | INTEGER | 1 when nothing was written |
| `notes` | TEXT | Human-readable summary |

---

## Consumers

`app.py` reads this schema directly:

| Route | Reads |
|---|---|
| `/` | `jobs` (11 columns for the table) |
| `/details/<id>` | `jobs`, `job_specs`, `exam_pattern`, `job_cutoffs` |
| `/healthz` | `coverage()` counts |

Because the templates render `job.<column>` by name, **removing or renaming a
column silently blanks a cell rather than raising**. Treat the names above as a
published interface; add, never rename.

## Migration policy

`migrate()` is idempotent and additive. It:

1. Creates missing tables with `CREATE TABLE IF NOT EXISTS`
2. Adds missing columns with `ALTER TABLE … ADD COLUMN` (nullable only)
3. Collapses duplicate child rows left by the old delete-then-insert code
4. Removes orphaned children, then creates the unique indexes
5. Sets `PRAGMA user_version`

It **never** drops or renames. Destruction requires `--force-reset`.

A database created by the original `database_setup.py` upgrades in place with no
data loss — covered by `tests/test_db.py::test_migrate_upgrades_a_legacy_database`.

## Useful queries

```sql
-- Everything about one post
SELECT j.post_name, j.salary, s.age_limits, s.attempts, p.stages
FROM jobs j
LEFT JOIN job_specs    s ON s.job_id = j.id
LEFT JOIN exam_pattern p ON p.job_id = j.id
WHERE j.post_name = 'IAS Officer';

-- Coverage: which posts are still unenriched?
SELECT j.post_name, j.exam_name
FROM jobs j LEFT JOIN job_specs s ON s.job_id = j.id
WHERE s.id IS NULL;

-- Cutoffs with their citation
SELECT j.exam_name, c.category, c.score, c.year, c.source_url
FROM job_cutoffs c JOIN jobs j ON j.id = c.job_id
ORDER BY j.exam_name, c.year DESC;

-- Staleness
SELECT post_name, verified_on, updated_at FROM jobs ORDER BY verified_on;
```
