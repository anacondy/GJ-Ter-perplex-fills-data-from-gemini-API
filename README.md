# GJ-Ter — Indian Government Exam Database

Builds a normalised, **sourced** SQLite database of Indian government
recruitment exams — eligibility rules, exam patterns and cutoff marks — and
fills the gaps using the Gemini API.

Every stored fact carries the URL it came from and the date it was checked.
Where a conducting body does not publish something, the field says so rather
than containing a guess.

---

## Quick start

No API key needed for the offline path:

```bash
git clone https://github.com/anacondy/GJ-Ter-perplex-fills-data-from-gemini-API.git
cd GJ-Ter-perplex-fills-data-from-gemini-API

python database_setup.py          # create jobs.db and seed 12 posts
python data_scout.py --offline    # fill it from the curated dataset
python -m gjter status            # see what you have
```

That produces a complete, verifiable database using only the standard library.

### With the Gemini API

```bash
pip install -e ".[gemini]"
export GEMINI_API_KEY='your-key'        # get one at https://aistudio.google.com/apikey
python data_scout.py --dry-run          # see what it would write, write nothing
python data_scout.py                    # for real
```

> **Never put the key in a source file.** It is read from the environment only.
> A key committed to git is compromised the moment it is pushed, even if a later
> commit removes it. See [`reports/SECURITY.md`](reports/SECURITY.md).

---

## Commands

Both original entry points still work; `gjter` is the full interface.

| Command | Purpose |
|---|---|
| `python database_setup.py` | Create or migrate the schema, then seed. Idempotent. |
| `python database_setup.py --force-reset` | Drop everything first. **Destructive.** |
| `python data_scout.py` | Enrich via Gemini. |
| `python data_scout.py --offline` | Enrich from the curated dataset. No key, no network. |
| `python data_scout.py --dry-run` | Fetch and match, write nothing. |
| `python data_scout.py --only "UPSC CSE"` | Restrict to specific exams. |
| `python -m gjter status` | Coverage summary and recent runs. Add `--json`. |
| `python -m gjter export -o out.json` | Dump everything as nested JSON. |
| `python -m gjter verify` | Integrity checks; exits non-zero on failure. |

### Configuration

CLI flags override environment variables, which override defaults.

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | API key. `GOOGLE_API_KEY` also accepted. |
| `GJTER_DB_PATH` | `jobs.db` | Database location |
| `GJTER_MODEL` | `gemini-2.5-flash` | Model name |
| `GJTER_BATCH_SIZE` | `5` | Exams per request |
| `GJTER_BATCH_PAUSE` | `20` | Seconds between batches |
| `GJTER_MAX_RETRIES` | `4` | Attempts per batch |

Copy `.env.example` to `.env` to keep these together. `.env` is gitignored.

---

## Data model

```
jobs ──< job_specs     (1:1)  nationality, age limits, relaxations, qualifications
     ──< exam_pattern  (1:1)  stages, papers, duration, marking scheme
     ──< job_cutoffs   (1:N)  category-wise cutoff marks, per year
scout_runs                    audit log of every run
```

Twelve seeded posts across ten distinct exams: UPSC CSE (IAS/IPS/IFS), UPSC ESE,
SSC CGL, NDA, RBI Grade B, SBI PO, IBPS PO, LIC AAO, ISRO ICRB, DRDO.

Provenance columns on every enriched table: `data_source`, `source_url`,
`verified_on`, `updated_at`.

Full detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
[`docs/SCHEMA.md`](docs/SCHEMA.md).

---

## Repository structure

```
.
├── data_scout.py              # entry point: enrich  (thin wrapper)
├── database_setup.py          # entry point: init    (thin wrapper)
├── pyproject.toml             # packaging, deps, pytest and ruff config
├── .env.example               # configuration template
│
├── gjter/                     # the package
│   ├── cli.py                 # argument parsing, command handlers
│   ├── config.py              # settings, env resolution, API-key loading
│   ├── db.py                  # schema, idempotent migrations, writes
│   ├── matching.py            # exam-name matching
│   ├── validation.py          # JSON repair, scalar coercion, URL validation
│   ├── pipeline.py            # orchestration
│   ├── seed.py                # the 12 base rows, with sources
│   ├── data/
│   │   └── curated_exams.json # hand-verified dataset (offline provider)
│   └── providers/
│       ├── base.py            # Provider interface
│       ├── gemini.py          # live API, retries, backoff
│       └── offline.py         # curated dataset
│
├── tests/                     # 132 tests
│   ├── test_matching.py
│   ├── test_validation.py
│   ├── test_db.py
│   ├── test_pipeline.py
│   ├── test_gemini_provider.py
│   └── test_config_and_cli.py
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SCHEMA.md
│   └── DATA_SOURCES.md
│
├── reports/
│   ├── CODE_AUDIT.md          # full audit: 28 findings, ratings
│   └── SECURITY.md            # vulnerabilities and remediation
│
├── CHANGELOG.md
└── docs/ci/                   # CI workflow, ready to enable (see docs/ci/README.md)
```

---

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                 # 132 tests, no network required
ruff check gjter tests
```

A GitHub Actions workflow (Python 3.9/3.11/3.12, offline smoke test, secret
scan) is provided in [`docs/ci/`](docs/ci/README.md). It is not active yet —
enabling it is a one-line `git mv`, documented there.

---

## Data accuracy

Seeded values were checked against the conducting bodies in July 2026 and carry
a `source_url`. **Eligibility rules, pay and vacancy counts change with every
notification cycle** — always confirm against the official website before
relying on a row. `verified_on` exists to make staleness visible.

Model-generated values are marked `data_source = 'gemini'`. Treat them as leads,
not authority; the prompt instructs the model to return
`"Information not available"` rather than guess, but that is a mitigation, not a
guarantee.

---

## Project history

This repository previously consisted of two scripts with a live API key in git
history, a matcher that silently wrote one exam's rules onto another, and a
setup script that dropped every table on import. Those and 25 other findings are
documented in [`reports/CODE_AUDIT.md`](reports/CODE_AUDIT.md), each with a
regression test.

## License

MIT — see [LICENSE](LICENSE).
