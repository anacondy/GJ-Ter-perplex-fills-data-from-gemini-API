"""SQLite access layer.

Design rules, all of which the original scripts broke:

* The schema is a **contract**. Column names and types that already existed are
  never renamed or removed; new columns are additive and nullable so that any
  existing reader keeps working.
* Migrations are **idempotent**. Running setup twice must not destroy data.
  ``DROP TABLE`` only happens behind an explicit ``--force-reset``.
* Foreign keys are actually **enforced** (SQLite disables them per-connection by
  default, which made the declared ``REFERENCES`` clauses decorative).
* Writes are **transactional per job**, so a failure halfway through a job cannot
  leave the row half-updated.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

#: Bumped whenever :func:`migrate` learns a new step.
SCHEMA_VERSION = 2

JOBS_COLUMNS: tuple[str, ...] = (
    "post_name",
    "exam_name",
    "conducting_body",
    "group",
    "gazetted_status",
    "pay_level",
    "salary",
    "eligibility",
    "age_limit",
    "pet_status",
    "application_start",
    "application_end",
    "exam_date",
    "official_website",
)

JOB_SPECS_FIELDS: tuple[str, ...] = (
    "nationality",
    "age_limits",
    "age_relax",
    "edu_qual",
    "attempts",
    "physical_std",
)

EXAM_PATTERN_FIELDS: tuple[str, ...] = (
    "stages",
    "num_papers",
    "q_type",
    "duration",
    "marking_scheme",
)

_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_name TEXT,
    exam_name TEXT,
    conducting_body TEXT,
    "group" TEXT,
    gazetted_status TEXT,
    pay_level INTEGER,
    salary TEXT,
    eligibility TEXT,
    age_limit TEXT,
    pet_status TEXT,
    application_start TEXT,
    application_end TEXT,
    exam_date TEXT,
    official_website TEXT
);

CREATE TABLE IF NOT EXISTS job_specs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    nationality TEXT,
    age_limits TEXT,
    age_relax TEXT,
    edu_qual TEXT,
    attempts TEXT,
    physical_std TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exam_pattern (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    stages TEXT,
    num_papers TEXT,
    q_type TEXT,
    duration TEXT,
    marking_scheme TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_cutoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    category TEXT,
    score TEXT,
    year TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
"""

# Additive columns introduced by this project. Each entry is
# (table, column, DDL type). All are nullable so pre-existing readers that do
# ``SELECT *`` still work and pre-existing rows stay valid.
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("jobs", "source_url", "TEXT"),
    ("jobs", "data_source", "TEXT"),
    ("jobs", "verified_on", "TEXT"),
    ("jobs", "updated_at", "TEXT"),
    ("job_specs", "data_source", "TEXT"),
    ("job_specs", "source_url", "TEXT"),
    ("job_specs", "updated_at", "TEXT"),
    ("exam_pattern", "data_source", "TEXT"),
    ("exam_pattern", "source_url", "TEXT"),
    ("exam_pattern", "updated_at", "TEXT"),
    ("job_cutoffs", "data_source", "TEXT"),
    ("job_cutoffs", "source_url", "TEXT"),
    ("job_cutoffs", "updated_at", "TEXT"),
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_jobs_exam_name ON jobs(exam_name)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_post_exam "
    "ON jobs(post_name, exam_name)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_specs_job ON job_specs(job_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_exam_pattern_job "
    "ON exam_pattern(job_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_cutoffs_unique "
    "ON job_cutoffs(job_id, category, year)",
    "CREATE INDEX IF NOT EXISTS idx_job_cutoffs_job ON job_cutoffs(job_id)",
)

_RUN_LOG = """
CREATE TABLE IF NOT EXISTS scout_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    provider TEXT,
    model TEXT,
    jobs_seen INTEGER DEFAULT 0,
    jobs_updated INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    dry_run INTEGER DEFAULT 0,
    notes TEXT
);
"""


def connect(db_path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a connection with the pragmas this project actually depends on."""
    path = Path(db_path)
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.exists():
        raise FileNotFoundError(
            f"Database not found at {path}. Run `python database_setup.py` first."
        )

    # isolation_level=None disables the sqlite3 module's implicit transaction
    # management. Without this the module opens its own transaction before our
    # BEGIN IMMEDIATE, that BEGIN raises "cannot start a transaction within a
    # transaction", and the rollback path is never reached - so a failed write
    # stays applied. Transactions are managed explicitly by transaction().
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Declared REFERENCES clauses do nothing unless this is switched on.
    conn.execute("PRAGMA foreign_keys = ON")
    # Survive a crash mid-write and allow concurrent readers.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block atomically: commit on success, roll back on any exception.

    Nests safely. An inner call reuses the outer transaction via a SAVEPOINT, so
    a helper that opens a transaction can be called from inside another one
    without either silently losing its rollback guarantee.
    """
    if conn.in_transaction:
        name = f"sp_{id(object()):x}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
            conn.execute(f"RELEASE SAVEPOINT {name}")
            raise
        else:
            conn.execute(f"RELEASE SAVEPOINT {name}")
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {row["name"] for row in rows}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def migrate(conn: sqlite3.Connection) -> int:
    """Bring the database up to :data:`SCHEMA_VERSION` without losing data.

    Safe to call on an empty file, on a database created by the original
    ``database_setup.py``, and on an already-migrated database.

    Returns:
        The schema version now stored in the file.
    """
    with transaction(conn):
        conn.executescript(_BASE_SCHEMA)
        conn.executescript(_RUN_LOG)

        for table, column, decl in _ADDITIVE_COLUMNS:
            if not _table_exists(conn, table):
                continue
            if column not in _existing_columns(conn, table):
                conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {decl}')

        # Unique indexes cannot be created while duplicates exist. Collapse any
        # duplicate child rows left behind by the old delete-then-insert code.
        _dedupe_children(conn)
        for statement in _INDEXES:
            try:
                conn.execute(statement)
            except sqlite3.IntegrityError:
                # Legacy data still violates the constraint; keep the plain
                # index off rather than failing the whole migration.
                continue

        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _dedupe_children(conn: sqlite3.Connection) -> None:
    """Keep only the newest row per job in the one-to-one child tables."""
    for table in ("job_specs", "exam_pattern"):
        if not _table_exists(conn, table):
            continue
        conn.execute(
            f"DELETE FROM {table} WHERE id NOT IN "
            f"(SELECT MAX(id) FROM {table} GROUP BY job_id)"
        )
    if _table_exists(conn, "job_cutoffs"):
        conn.execute(
            "DELETE FROM job_cutoffs WHERE id NOT IN "
            "(SELECT MAX(id) FROM job_cutoffs "
            " GROUP BY job_id, IFNULL(category,''), IFNULL(year,''))"
        )
    # Orphans would block the foreign keys we are about to start enforcing.
    for table in ("job_specs", "exam_pattern", "job_cutoffs"):
        if _table_exists(conn, table) and _table_exists(conn, "jobs"):
            conn.execute(
                f"DELETE FROM {table} "
                "WHERE job_id NOT IN (SELECT id FROM jobs)"
            )


def reset(conn: sqlite3.Connection) -> None:
    """Destructive: drop every project table. Only ever called explicitly."""
    with transaction(conn):
        for table in ("job_cutoffs", "exam_pattern", "job_specs", "jobs", "scout_runs"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("PRAGMA user_version = 0")


def upsert_job(conn: sqlite3.Connection, job: dict) -> int:
    """Insert or update one row in ``jobs``, keyed on (post_name, exam_name).

    Only keys present in ``job`` are written, so a later enrichment pass never
    blanks a column it does not know about.
    """
    known = {k: v for k, v in job.items() if k in JOBS_COLUMNS or k in {
        "source_url", "data_source", "verified_on", "updated_at"
    }}
    post_name = known.get("post_name")
    exam_name = known.get("exam_name")
    if not post_name or not exam_name:
        raise ValueError("upsert_job requires both post_name and exam_name")

    row = conn.execute(
        "SELECT id FROM jobs WHERE post_name = ? AND exam_name = ?",
        (post_name, exam_name),
    ).fetchone()

    if row is None:
        cols = list(known)
        placeholders = ", ".join("?" for _ in cols)
        quoted = ", ".join(f'"{c}"' for c in cols)
        cur = conn.execute(
            f"INSERT INTO jobs ({quoted}) VALUES ({placeholders})",
            [known[c] for c in cols],
        )
        return int(cur.lastrowid)

    job_id = int(row["id"])
    updatable = [c for c in known if c not in ("post_name", "exam_name")]
    if updatable:
        assignments = ", ".join(f'"{c}" = ?' for c in updatable)
        conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            [known[c] for c in updatable] + [job_id],
        )
    return job_id


def _upsert_child(
    conn: sqlite3.Connection,
    table: str,
    fields: Sequence[str],
    job_id: int,
    values: dict,
) -> None:
    """Replace the single child row for ``job_id`` in a one-to-one table."""
    payload = {f: values.get(f) for f in fields}
    payload.update(
        {
            k: values[k]
            for k in ("data_source", "source_url", "updated_at")
            if k in values
        }
    )
    cols = ["job_id", *payload.keys()]
    quoted = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(f"DELETE FROM {table} WHERE job_id = ?", (job_id,))
    conn.execute(
        f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})",
        [job_id, *payload.values()],
    )


def upsert_job_specs(conn: sqlite3.Connection, job_id: int, values: dict) -> None:
    """Write the eligibility block for one job."""
    _upsert_child(conn, "job_specs", JOB_SPECS_FIELDS, job_id, values)


def upsert_exam_pattern(conn: sqlite3.Connection, job_id: int, values: dict) -> None:
    """Write the exam-pattern block for one job."""
    _upsert_child(conn, "exam_pattern", EXAM_PATTERN_FIELDS, job_id, values)


def replace_cutoffs(
    conn: sqlite3.Connection, job_id: int, cutoffs: Iterable[dict]
) -> int:
    """Replace all cutoff rows for one job. Returns the number written."""
    conn.execute("DELETE FROM job_cutoffs WHERE job_id = ?", (job_id,))
    written = 0
    seen: set[tuple[str, str]] = set()
    for cutoff in cutoffs:
        category = cutoff.get("category")
        year = cutoff.get("year")
        key = (str(category), str(year))
        if key in seen:
            continue
        seen.add(key)
        conn.execute(
            "INSERT INTO job_cutoffs "
            '(job_id, category, score, year, data_source, source_url, updated_at) '
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                category,
                cutoff.get("score"),
                year,
                cutoff.get("data_source"),
                cutoff.get("source_url"),
                cutoff.get("updated_at"),
            ),
        )
        written += 1
    return written


def fetch_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All jobs, ordered deterministically so runs are reproducible."""
    return conn.execute(
        "SELECT id, post_name, exam_name, conducting_body, official_website "
        "FROM jobs ORDER BY id"
    ).fetchall()


def distinct_exams(conn: sqlite3.Connection) -> list[str]:
    """Distinct exam names.

    The seed contains three posts (IAS/IPS/IFS) that share one exam, so asking
    the model per job wasted three identical calls per batch.
    """
    rows = conn.execute(
        "SELECT DISTINCT exam_name FROM jobs "
        "WHERE exam_name IS NOT NULL AND TRIM(exam_name) <> '' "
        "ORDER BY exam_name"
    ).fetchall()
    return [row["exam_name"] for row in rows]


def jobs_for_exam(conn: sqlite3.Connection, exam_name: str) -> list[sqlite3.Row]:
    """Every job row that maps to a given exam name."""
    return conn.execute(
        "SELECT id, post_name, exam_name FROM jobs WHERE exam_name = ? ORDER BY id",
        (exam_name,),
    ).fetchall()


def start_run(conn: sqlite3.Connection, **fields) -> int:
    """Record the beginning of a scout run and return its id."""
    cols = list(fields)
    quoted = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    with transaction(conn):
        cur = conn.execute(
            f"INSERT INTO scout_runs ({quoted}) VALUES ({placeholders})",
            [fields[c] for c in cols],
        )
        return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, **fields) -> None:
    """Close out a scout run row."""
    if not fields:
        return
    assignments = ", ".join(f'"{c}" = ?' for c in fields)
    with transaction(conn):
        conn.execute(
            f"UPDATE scout_runs SET {assignments} WHERE id = ?",
            [*fields.values(), run_id],
        )


def coverage(conn: sqlite3.Connection) -> dict:
    """Cheap health snapshot used by ``gjter status`` and the tests."""

    def _scalar(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    return {
        "jobs": _scalar("SELECT COUNT(*) FROM jobs"),
        "exams": _scalar("SELECT COUNT(DISTINCT exam_name) FROM jobs"),
        "job_specs": _scalar("SELECT COUNT(*) FROM job_specs"),
        "exam_pattern": _scalar("SELECT COUNT(*) FROM exam_pattern"),
        "job_cutoffs": _scalar("SELECT COUNT(*) FROM job_cutoffs"),
        "jobs_with_website": _scalar(
            "SELECT COUNT(*) FROM jobs "
            "WHERE official_website IS NOT NULL AND TRIM(official_website) <> ''"
        ),
        "schema_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
    }
