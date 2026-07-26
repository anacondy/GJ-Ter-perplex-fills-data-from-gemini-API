"""Tests for the schema, migrations and write paths."""

from __future__ import annotations

import sqlite3

import pytest

from gjter import db
from gjter.seed import SEED_JOBS, seed


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.migrate(connection)
    yield connection
    connection.close()


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "idem.db"
    c = db.connect(path)
    assert db.migrate(c) == db.SCHEMA_VERSION
    assert db.migrate(c) == db.SCHEMA_VERSION
    assert db.migrate(c) == db.SCHEMA_VERSION
    c.close()


def test_migrate_preserves_existing_data(tmp_path):
    """The old setup script dropped every table at import time."""
    path = tmp_path / "keep.db"
    c = db.connect(path)
    db.migrate(c)
    job_id = db.upsert_job(c, {"post_name": "P", "exam_name": "E"})
    c.commit()
    c.close()

    c2 = db.connect(path)
    db.migrate(c2)
    rows = c2.execute("SELECT id FROM jobs").fetchall()
    assert [r["id"] for r in rows] == [job_id]
    c2.close()


def test_migrate_upgrades_a_legacy_database(tmp_path):
    """A database made by the original script must migrate without data loss."""
    path = tmp_path / "legacy.db"
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, post_name TEXT, exam_name TEXT,
            conducting_body TEXT, "group" TEXT, gazetted_status TEXT,
            pay_level INTEGER, salary TEXT, eligibility TEXT, age_limit TEXT,
            pet_status TEXT, application_start TEXT, application_end TEXT,
            exam_date TEXT, official_website TEXT);
        CREATE TABLE job_specs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, nationality TEXT,
            age_limits TEXT, age_relax TEXT, edu_qual TEXT, attempts TEXT,
            physical_std TEXT);
        CREATE TABLE exam_pattern (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, stages TEXT,
            num_papers TEXT, q_type TEXT, duration TEXT, marking_scheme TEXT);
        CREATE TABLE job_cutoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, category TEXT,
            score TEXT, year TEXT);
        INSERT INTO jobs (post_name, exam_name) VALUES ('IAS Officer', 'UPSC CSE');
        -- duplicates the old delete-then-insert code could leave behind
        INSERT INTO job_specs (job_id, nationality) VALUES (1, 'old');
        INSERT INTO job_specs (job_id, nationality) VALUES (1, 'newer');
        """
    )
    raw.commit()
    raw.close()

    c = db.connect(path)
    assert db.migrate(c) == db.SCHEMA_VERSION
    assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    # Duplicate collapsed, newest kept.
    specs = c.execute("SELECT nationality FROM job_specs").fetchall()
    assert len(specs) == 1 and specs[0]["nationality"] == "newer"
    # Additive column present.
    cols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)")}
    assert {"source_url", "verified_on", "updated_at"} <= cols
    c.close()


def test_legacy_columns_are_never_removed(conn):
    """Any existing reader doing SELECT * must keep working."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    for legacy in db.JOBS_COLUMNS:
        assert legacy in cols


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction(conn):
            conn.execute("INSERT INTO job_specs (job_id) VALUES (99999)")


def test_upsert_job_is_idempotent(conn):
    a = db.upsert_job(conn, {"post_name": "IAS Officer", "exam_name": "UPSC CSE"})
    b = db.upsert_job(
        conn, {"post_name": "IAS Officer", "exam_name": "UPSC CSE", "salary": "x"}
    )
    assert a == b
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert conn.execute("SELECT salary FROM jobs").fetchone()["salary"] == "x"


def test_upsert_job_does_not_blank_unspecified_columns(conn):
    db.upsert_job(
        conn, {"post_name": "P", "exam_name": "E", "salary": "keep", "group": "A"}
    )
    db.upsert_job(conn, {"post_name": "P", "exam_name": "E", "group": "B"})
    row = conn.execute("SELECT salary, \"group\" FROM jobs").fetchone()
    assert row["salary"] == "keep"
    assert row["group"] == "B"


def test_upsert_job_requires_keys(conn):
    with pytest.raises(ValueError):
        db.upsert_job(conn, {"post_name": "only"})


def test_child_upserts_stay_one_to_one(conn):
    job_id = db.upsert_job(conn, {"post_name": "P", "exam_name": "E"})
    for value in ("first", "second", "third"):
        db.upsert_job_specs(conn, job_id, {"nationality": value})
    rows = conn.execute("SELECT nationality FROM job_specs").fetchall()
    assert len(rows) == 1 and rows[0]["nationality"] == "third"


def test_replace_cutoffs_dedupes(conn):
    job_id = db.upsert_job(conn, {"post_name": "P", "exam_name": "E"})
    written = db.replace_cutoffs(
        conn,
        job_id,
        [
            {"category": "General", "score": "92", "year": "2025"},
            {"category": "General", "score": "93", "year": "2025"},
            {"category": "OBC", "score": "91", "year": "2025"},
        ],
    )
    assert written == 2


def test_transaction_rolls_back(conn):
    db.upsert_job(conn, {"post_name": "P", "exam_name": "E"})
    with pytest.raises(RuntimeError):
        with db.transaction(conn):
            conn.execute("UPDATE jobs SET salary = 'dirty'")
            raise RuntimeError("boom")
    assert conn.execute("SELECT salary FROM jobs").fetchone()["salary"] is None


def test_distinct_exams_collapses_shared_exams(conn):
    seed(conn)
    exams = db.distinct_exams(conn)
    # IAS, IPS and IFS all sit behind one UPSC CSE exam.
    assert len(exams) < len(SEED_JOBS)
    assert exams.count("UPSC CSE") == 1


def test_seed_is_idempotent(conn):
    seed(conn)
    first = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    seed(conn)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == first
    assert first == len(SEED_JOBS)


def test_reset_clears_everything(conn):
    seed(conn)
    db.reset(conn)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone()[0]
    assert remaining == 0


def test_coverage_shape(conn):
    seed(conn)
    stats = db.coverage(conn)
    assert stats["jobs"] == len(SEED_JOBS)
    assert stats["schema_version"] == db.SCHEMA_VERSION
