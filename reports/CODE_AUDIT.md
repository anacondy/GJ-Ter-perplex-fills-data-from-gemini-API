# Code Audit — GJ-Ter (Gemini exam-data filler)

**Audited commit:** `3f268fc` ("Replace API key with placeholder")
**Audit date:** 2026-07-27
**Scope:** the entire repository — `data_scout.py` (145 lines), `database_setup.py` (101 lines), `README.md` (2 lines), `LICENSE`.
**Auditor's note:** the repository contains **no frontend, no tests, no dependency manifest, no CI and no `.gitignore`.** The whole project is 246 lines of Python.

---

## 1. Executive summary

The project has a sound *idea*: normalise a set of Indian government exams into a relational schema, then use an LLM to fill the parts that are tedious to compile by hand. The schema design is genuinely reasonable — a `jobs` spine with three satellite tables is the right shape for this data.

The *implementation* does not hold up. Of the two scripts, one destroys the database as an import side effect and the other cannot run at all as committed. Between them I found **4 critical, 7 high, 9 medium and 8 low-severity issues** — 28 in total.

The most serious finding is not the leaked API key (bad, but a known quantity). It is that **the pipeline silently writes wrong data into the database and reports success while doing it.** A user running this tool would end up with a database that looks fully populated and is confidently incorrect in ways no error message reveals. For a dataset whose entire purpose is telling people whether they are eligible for a career-defining exam, that is the worst possible failure mode.

**Overall rating: 3.5 / 10.** Detailed scorecard in §6.

---

## 2. Critical severity

### C1 — A live API key was committed to git history
`data_scout.py:8` at commit `87315c3` contained:

```python
API_KEY = "AIzaSyDx5BzjMTff0pHzJAZVDYQE-I9j5RSz3Z8"
```

Commit `3f268fc` replaced it with `"KEY HERE"`. **This does not remediate anything.** The key remains in the object database, is reachable via `git show 87315c3:data_scout.py`, is served by the GitHub API, and has almost certainly been harvested — GitHub is continuously scraped for exactly this pattern, typically within minutes of a push.

*Impact:* unauthorised billing against the owner's Google Cloud account, quota exhaustion, and potential access to other services if the key is not scoped.

*Required action — the code fix in this PR does not do this for you:*
1. **Revoke the key now** at <https://aistudio.google.com/apikey>. This is the only step that actually stops the bleeding.
2. Rotate to a new key, stored in the environment.
3. Optionally purge history with `git filter-repo`, but treat the key as burned regardless.

*Fixed here:* keys are now read via `load_api_key()` from `GEMINI_API_KEY`/`GOOGLE_API_KEY`; the string `"KEY HERE"` is explicitly rejected as a placeholder; `.gitignore` covers `.env`; a CI job (in `docs/ci/`) fails on any `AIza[0-9A-Za-z_-]{35}` literal.

### C2 — Importing `database_setup.py` destroys the database
The script has no `if __name__ == '__main__'` guard. All four `DROP TABLE` statements run at module scope (`database_setup.py:13-16`). Any `import database_setup` — from a REPL, a test, a future web layer, or an IDE's autocomplete indexer — irrecoverably deletes every table.

There is also no backup, no confirmation prompt and no warning. The docstring calls it the "FINAL version", implying it is meant to be run repeatedly.

*Fixed:* migrations are idempotent and additive; destruction requires an explicit `--force-reset`; all execution is behind a `__main__` guard.

### C3 — Wrong exam data is written to the wrong exam, silently
`find_best_match()` (`data_scout.py:18-30`) has two independent defects that both corrupt data:

```python
match = difflib.get_close_matches(exam_name_db, names_in_api, n=1, cutoff=0.4)
```

**Defect 1 — the cutoff is far too loose.** `"UPSC CSE"` and `"UPSC ESE"` score **0.875** against each other. At `cutoff=0.4`, if the model omits CSE from a batch, the Civil Services row is confidently filled with **Engineering Services** eligibility rules — a different age limit (21-30 vs 21-32), a different qualification (engineering degree vs any degree) and a different attempt policy. Verified experimentally; both exams are in this project's own seed data, so the collision is guaranteed, not hypothetical.

**Defect 2 — the fallback matches everything.** Lines 26-29:

```python
if exam_name_db.lower() in item.get('exam_name', '').lower() or \
   item.get('exam_name', '').lower() in exam_name_db.lower():
```

When an item lacks `exam_name`, `.get()` returns `''`, and **`'' in anything` is always `True`**. Any malformed response item is therefore handed to the first exam that asks, whose data is then written as fact.

Neither path logs a warning. The code prints `✅ All data updated`.

*Fixed:* `gjter/matching.py` tries exact → normalised → conservative fuzzy; requires identifying acronym tokens to be preserved (so CSE can never satisfy ESE); rejects ambiguous near-ties; and treats a blank `exam_name` as unusable rather than as a wildcard. Regression tests in `tests/test_matching.py`.

### C4 — Nested JSON values abort the write, and the error is mislabelled
The prompt asks for fields like `stages` and `age_relax`, which models very often return as arrays or objects. `sqlite3` cannot bind those and raises `InterfaceError`. That is caught by the per-job handler at line 135 and printed as `❌ Database Error` — blaming the database for a data-shape problem, and skipping the exam entirely. Because the `INSERT`s into `job_specs`, `exam_pattern` and `job_cutoffs` are sequential inside one `try`, a failure on the first leaves the later two unwritten while the earlier `DELETE` has already removed the old rows. **Net effect: pre-existing good data is deleted and not replaced.**

*Fixed:* `coerce_scalar()` flattens any JSON value to a bindable string; every job is written in its own transaction, so a failure rolls back to the prior state rather than leaving a hole.

---

## 3. High severity

### H1 — `response.text` can raise, and the bare `except` hides it
`data_scout.py:63` accesses `response.text` before validating the response. In the Google SDK this raises `ValueError` when the candidate was blocked by a safety filter or truncated at `MAX_TOKENS`. The `except Exception` at line 69 catches it and returns `[]`, so a systematically blocked prompt is indistinguishable from a network blip. The batch is skipped and the run reports success.

*Fixed:* finish reason and `prompt_feedback` are inspected and surfaced; truncation is classified as retryable; safety blocks raise a distinct, non-retryable error.

### H2 — No retry logic; a transient 429 loses the whole batch
On any failure the code sleeps a flat 30 s and `continue`s (lines 85-88). Rate limits are the *expected* condition on a free-tier key, so ordinary operation silently drops five exams at a time.

*Fixed:* up to 4 attempts with exponential backoff and jitter, with errors classified as retryable vs terminal.

### H3 — Declared foreign keys are not enforced
All three child tables declare `FOREIGN KEY(job_id) REFERENCES jobs(id)`, but SQLite ignores foreign keys unless `PRAGMA foreign_keys = ON` is set **per connection**. It never is. The constraints are decorative; orphaned rows are accepted silently.

*Fixed:* the pragma is set in `db.connect()`, with `ON DELETE CASCADE`; `gjter verify` runs `foreign_key_check`.

### H4 — Redundant API calls; roughly 30 % of spend is wasted
Batches are built from **job rows**, but the prompt asks about **exam names**. IAS, IPS and IFS all map to `UPSC CSE`, so the model is asked about the same exam three times in one prompt — and `find_best_match` then resolves all three to whichever copy the model returned. 12 jobs cover only 10 distinct exams.

*Fixed:* batching runs over `SELECT DISTINCT exam_name`; one answer fans out to all jobs sharing that exam.

### H5 — Commit granularity guarantees partial writes
`conn.commit()` is called once per batch (line 137) *after* per-job exceptions have been swallowed. A crash, `Ctrl-C` or power loss mid-batch leaves some jobs updated and others with deleted-but-not-replaced rows. There is no `try/finally`, so `conn.close()` is skipped on any uncaught exception.

*Fixed:* one transaction per job; connections closed in `finally`.

### H6 — Hallucinated URLs are written into `official_website`
`exam_data.get('official_website', 'Information not available')` is written unconditionally (lines 132-133). When the model does not know, the literal string `"Information not available"` is stored in a column any consumer will render as a hyperlink. There is no URL validation whatsoever.

*Fixed:* `validate_url()` requires a well-formed `http(s)` URL; anything else leaves the column untouched.

### H7 — The prompt invites fabrication
The instruction `If information is unavailable for any field, write "Information not available"` is a weak, easily-ignored hint placed *after* the schema. Combined with `temperature` left at its default, the model has every incentive to produce plausible-looking cutoff marks. **Several bodies in this dataset (SSC, IBPS, LIC, DRDO) do not publish official cutoffs in the form requested at all**, so any value returned for them is invented — and it lands in a table called `job_cutoffs` where it reads as authoritative.

*Fixed:* `temperature=0.0`; hard rules stating that the sentinel is preferable to a guess; explicit instruction not to invent cutoffs; a `source_url` is requested per record and stored alongside the data.

---

## 4. Medium severity

| # | Issue | Location | Status |
|---|-------|----------|--------|
| M1 | `INSERT INTO t VALUES (NULL,?,...)` relies on positional column order. Adding a column anywhere silently shifts every value into the wrong field. | `data_scout.py:97,110,124` | Fixed — all inserts name their columns |
| M2 | Hardcoded `gemini-2.5-pro` — expensive, and the batch is well within `flash` capability | `data_scout.py:11` | Fixed — configurable, defaults to `flash` |
| M3 | No dependency manifest. `google.generativeai` is imported but never declared | repo root | Fixed — `pyproject.toml`; core has zero deps |
| M4 | Uses `google-generativeai`, whose support **ended 2025-11-30** | `data_scout.py:2` | Fixed — prefers `google-genai`, falls back with a warning |
| M5 | Fixed 30 s sleep even after the final batch — 30 s wasted per run | `data_scout.py:138-140` | Fixed — skipped on last batch and offline |
| M6 | No `.gitignore`; `jobs.db` and any `.env` are commit candidates | repo root | Fixed |
| M7 | Seeded facts are unsourced and several are wrong (see §5) | `database_setup.py:79-92` | Fixed — verified values + source URLs |
| M8 | No logging; everything is `print` with emoji, unparseable and not level-filtered | throughout | Fixed — `logging` + clean stdout |
| M9 | No way to run without spending money or holding a key | — | Fixed — `--offline` and `--dry-run` |

## 5. Data-quality findings in the seed

The twelve seeded rows are presented as fact but were evidently written from memory. Errors I confirmed against the conducting bodies:

| Field | Committed value | Verified value | Source |
|---|---|---|---|
| SSC CGL AAO — `gazetted_status` | `Non-Gazetted` | **Gazetted** (Group B Gazetted, the one CGL post that is) | [SSC](https://ssc.gov.in) |
| SSC CGL AAO — `salary` | `₹45,000+` | **₹47,600** basic (Level 8) | [SSC / 7th CPC](https://ssc.gov.in) |
| SBI PO — `pay_level` | `7` | **Not applicable** — bank officer scale (JMGS-I), not on the CPC matrix | [SBI](https://sbi.co.in/web/careers) |
| SBI PO — `salary` | `₹40,000+` | **₹48,480** basic (JMGS-I) | [SBI](https://sbi.co.in/web/careers) |
| IBPS PO — `pay_level` | `7` | **Not applicable** — same reason | [IBPS](https://www.ibps.in) |
| IBPS PO — `salary` | `₹35,000+` | **₹48,480-85,920** | [IBPS](https://www.ibps.in) |
| LIC AAO — `pay_level` | `8` | **Not applicable** — LIC is a statutory corporation with its own scale | [LIC](https://licindia.in/web/guest/careers) |
| LIC AAO — `salary` | `₹40,000+` | **₹88,635** basic — understated by more than half | [LIC](https://licindia.in/web/guest/careers) |
| LIC AAO — `gazetted_status` | `Non-Gazetted` | **Not applicable** — LIC posts are not gazetted either way | [LIC](https://licindia.in/web/guest/careers) |
| RBI Grade B — `pay_level` | `10` | **Not applicable** — RBI runs its own officer scale | [RBI](https://opportunities.rbi.org.in) |
| RBI Grade B — `salary` | `₹70,000+` | **₹55,200** basic (gross is higher; the two were conflated) | [RBI](https://opportunities.rbi.org.in) |
| DRDO Scientist B — `age_limit` | `21-28` | **Up to 35** (unreserved, GATE-based advertisement) | [DRDO RAC](https://rac.gov.in) |
| ISRO Scientist — `age_limit` | `21-35` | **Up to 28** (BE/B.Tech entry) — inverted with DRDO | [ISRO](https://www.isro.gov.in/CareerOpportunities.html) |
| ISRO Scientist — `eligibility` | `60%+` | **65 %** or CGPA 6.84/10 | [ISRO](https://www.isro.gov.in/CareerOpportunities.html) |
| All salaries | `₹NN,NNN+` with a trailing `+` | Ambiguous — basic pay and gross conflated throughout | — |
| All `age_limit` | e.g. `21-32` | Missing the reckoning date, without which the value is unusable | — |

The `pay_level` column is the clearest symptom: it is an `INTEGER` modelling a 7th CPC pay matrix level, but it was populated for four posts that are **not on the pay matrix at all**. That is a data-modelling error, not a typo — the schema had no way to express "not applicable", so a wrong number was invented to fill it.

**Every one of these is corrected in `gjter/seed.py`, with a `source_url` and `verified_on` date attached to each row.** Where a body genuinely does not publish something, the value is now `NULL` or the explicit sentinel — never a guess.

## 6. Ratings

| Dimension | Score | Reasoning |
|---|---|---|
| **Correctness** | **2 / 10** | Silently writes wrong data and reports success. C3 alone is disqualifying for a data pipeline. |
| **Security** | **1 / 10** | Live credential in public git history. No secret management of any kind. |
| **Architecture** | **4 / 10** | The *schema* is good — proper normalisation, sensible satellite tables. Everything above it is one flat script with no separation between config, I/O, transport and persistence. |
| **Error handling** | **2 / 10** | Two bare `except Exception` blocks that convert hard failures into cheerful success messages. |
| **Testability** | **0 / 10** | Zero tests. Impossible to test as written: module-level side effects, no injection points, network required. |
| **Maintainability** | **3 / 10** | Short enough to read, but magic numbers throughout, no docstrings, no types, no logging. |
| **Data integrity** | **2 / 10** | Declared FKs unenforced, no uniqueness constraints, positional inserts, no provenance, unvalidated URLs. |
| **Documentation** | **1 / 10** | A two-line README reading "available to run good," which is also the repo description. No setup, no schema docs, no prerequisites. |
| **Dependency hygiene** | **2 / 10** | No manifest; the one dependency is an SDK that reached end-of-life on 2025-11-30. |
| **Cost efficiency** | **4 / 10** | ~30 % of calls redundant; most expensive model chosen; 30 s wasted per run. |
| **Overall** | **3.5 / 10** | Good schema instincts, prototype-grade execution, with failure modes that are actively dangerous because they are silent. |

## 7. Where the code is weakest

1. **It lies about success.** This is the throughline of nearly every finding. Bare excepts, unvalidated matches and swallowed binding errors all converge on the same outcome: a run that prints `🎉 Mission Complete! Database fully updated with real data. ✅` while having written wrong data, no data, or half-deleted rows. A pipeline that fails loudly is fixable; one that fails quietly erodes trust in the entire dataset.

2. **No boundary between "the model said so" and "this is true."** Model output flows directly into a table named `job_cutoffs` with nothing recording where it came from or when. Once written it is indistinguishable from verified fact. This is the core architectural gap, and it is why provenance columns (`source_url`, `data_source`, `verified_on`) matter more here than any refactor.

3. **Destructive-by-default persistence.** `DROP TABLE` at import scope, `DELETE` before `INSERT` with no transaction, commit-per-batch. The design assumes every run succeeds completely.

4. **Correctness is untestable by construction.** Module-level side effects and a hard network dependency mean not a single behaviour can be asserted. That is *why* C3 survived: no test could have been written to catch it without first restructuring the code.

5. **Silent unit conflation.** "Basic pay" and "gross salary" are mixed within one `TEXT` column, with a `+` suffix papering over the ambiguity. A reader cannot tell which is which, and neither could the author six months later.

## 8. What was changed

See [`CHANGELOG.md`](../CHANGELOG.md) for the full list and [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) for the new structure.

The two original entry points still work exactly as before:

```bash
python database_setup.py     # now non-destructive and idempotent
python data_scout.py         # now needs GEMINI_API_KEY in the environment
python data_scout.py --offline   # new: full run, no key, no network, no cost
```

**132 tests**, all passing, covering every critical and high finding above as an explicit regression test.

## 9. Recommended next steps (not done in this PR)

1. **Revoke the exposed key.** Nothing in this PR can do it for you. (C1)
2. Add cutoff data for the remaining exams from official PDFs, or leave them empty — do not let the model fill them.
3. Consider a `pay_scale_type` enum (`cpc_level` / `bank_scale` / `corporation_scale`) so the "not applicable" case is modelled rather than fudged.
4. Add a `sources` table if multiple citations per field are ever needed.
5. Schedule a re-verification cadence; `verified_on` exists to make staleness visible.
