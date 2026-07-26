"""End-to-end pipeline tests using stub and curated providers."""

from __future__ import annotations

import pytest

from gjter import db
from gjter.config import UNKNOWN, Settings
from gjter.pipeline import enrich
from gjter.providers.base import Provider, ProviderError, ProviderResponse
from gjter.providers.offline import OfflineProvider
from gjter.seed import seed


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "pipe.db")
    db.migrate(connection)
    seed(connection)
    yield connection
    connection.close()


@pytest.fixture()
def settings(tmp_path):
    return Settings(db_path=tmp_path / "pipe.db", batch_pause_seconds=0, batch_size=5)


class StubProvider(Provider):
    name = "stub"

    def __init__(self, records, fail=False):
        self._records = records
        self._fail = fail
        self.calls = []

    def fetch_batch(self, exam_names):
        self.calls.append(list(exam_names))
        if self._fail:
            raise ProviderError("simulated outage")
        return ProviderResponse(records=list(self._records))


def test_offline_run_populates_every_table(conn, settings):
    report = enrich(conn, OfflineProvider(), settings)
    assert report.updated
    assert not report.failed
    stats = db.coverage(conn)
    assert stats["job_specs"] == stats["jobs"]
    assert stats["exam_pattern"] == stats["jobs"]
    assert stats["job_cutoffs"] > 0


def test_dry_run_writes_nothing(conn, settings):
    before = db.coverage(conn)
    report = enrich(conn, OfflineProvider(), settings.replace(dry_run=True))
    assert report.dry_run
    assert report.updated
    assert db.coverage(conn)["job_specs"] == before["job_specs"] == 0


def test_shared_exam_updates_all_its_jobs(conn, settings):
    enrich(conn, OfflineProvider(), settings, only=["UPSC CSE"])
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM job_specs js "
        "JOIN jobs j ON j.id = js.job_id WHERE j.exam_name = 'UPSC CSE'"
    ).fetchone()
    assert rows["n"] == 3  # IAS, IPS, IFS


def test_batching_asks_once_per_distinct_exam(conn, settings):
    stub = StubProvider([])
    enrich(conn, stub, settings)
    asked = [name for call in stub.calls for name in call]
    assert len(asked) == len(set(asked)), "an exam was requested more than once"
    assert len(asked) == len(db.distinct_exams(conn))


def test_cse_data_is_not_written_from_ese_response(conn, settings):
    """The original matcher would have written this onto the IAS rows."""
    stub = StubProvider([{"exam_name": "UPSC ESE", "age_limits": "21-30 ESE"}])
    report = enrich(conn, stub, settings, only=["UPSC CSE"])
    assert not report.updated
    assert report.unmatched
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM job_specs js JOIN jobs j ON j.id = js.job_id "
        "WHERE j.exam_name = 'UPSC CSE'"
    ).fetchone()
    assert row["n"] == 0


def test_blank_exam_name_record_is_not_applied(conn, settings):
    stub = StubProvider([{"exam_name": "", "nationality": "WRONG"}])
    report = enrich(conn, stub, settings, only=["SSC CGL"])
    assert not report.updated
    assert conn.execute("SELECT COUNT(*) FROM job_specs").fetchone()[0] == 0


def test_nested_values_do_not_break_the_write(conn, settings):
    """Lists and dicts used to raise sqlite3.InterfaceError per row."""
    stub = StubProvider(
        [
            {
                "exam_name": "SSC CGL",
                "stages": ["Tier I", "Tier II"],
                "age_relax": {"SC": "5 years", "OBC": "3 years"},
                "nationality": "Indian",
            }
        ]
    )
    report = enrich(conn, stub, settings, only=["SSC CGL"])
    assert report.updated
    row = conn.execute(
        "SELECT stages FROM exam_pattern ep JOIN jobs j ON j.id = ep.job_id "
        "WHERE j.exam_name = 'SSC CGL'"
    ).fetchone()
    assert row["stages"] == "Tier I; Tier II"


def test_sentinel_website_is_never_stored(conn, settings):
    stub = StubProvider(
        [{"exam_name": "SSC CGL", "official_website": UNKNOWN}]
    )
    enrich(conn, stub, settings, only=["SSC CGL"])
    row = conn.execute(
        "SELECT official_website FROM jobs WHERE exam_name = 'SSC CGL'"
    ).fetchone()
    assert row["official_website"] != UNKNOWN
    assert row["official_website"].startswith("http")


def test_provider_outage_is_reported_not_swallowed(conn, settings):
    report = enrich(conn, StubProvider([], fail=True), settings)
    assert report.failed
    assert not report.updated
    assert "simulated outage" in report.failed[0].detail


def test_run_is_logged(conn, settings):
    enrich(conn, OfflineProvider(), settings, only=["SSC CGL"])
    runs = conn.execute("SELECT * FROM scout_runs").fetchall()
    assert len(runs) == 1
    assert runs[0]["finished_at"]
    assert runs[0]["provider"] == "curated-offline"


def test_only_filter_restricts_scope(conn, settings):
    report = enrich(conn, OfflineProvider(), settings, only=["SSC CGL"])
    assert [o.exam_name for o in report.updated] == ["SSC CGL"]


def test_limit_is_respected(conn, settings):
    report = enrich(conn, OfflineProvider(), settings, limit=2)
    assert len(report.outcomes) == 2


def test_rerun_does_not_duplicate_rows(conn, settings):
    enrich(conn, OfflineProvider(), settings)
    first = db.coverage(conn)
    enrich(conn, OfflineProvider(), settings)
    assert db.coverage(conn) == first


def test_provenance_is_recorded(conn, settings):
    enrich(conn, OfflineProvider(), settings, only=["UPSC CSE"])
    row = conn.execute(
        "SELECT source_url, updated_at FROM job_specs LIMIT 1"
    ).fetchone()
    assert row["source_url"].startswith("http")
    assert row["updated_at"]
