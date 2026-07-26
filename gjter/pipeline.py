"""The enrichment pipeline: fetch facts, verify them, write them once.

Behavioural differences from the original ``update_all_job_info``:

* Batches are built from **distinct exam names**, not from job rows. The seed has
  three posts sharing ``UPSC CSE``, so the old loop paid for the same answer
  three times and then matched it three times.
* Every job is written inside its **own transaction**. The old code committed
  once per batch after catching per-job exceptions, so a failure left partial
  rows committed alongside good ones.
* A record is only written when it **matches confidently**. Unmatched exams are
  reported, not silently filled with a neighbour's data.
* ``official_website`` is only written when it parses as a real URL, so the
  sentinel string can never be rendered as a link.
* The pause between batches is skipped on the last batch and in offline mode.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import db
from .config import UNKNOWN, Settings
from .matching import find_best_match
from .providers.base import Provider, ProviderError
from .validation import clean_cutoffs, clean_record, validate_url

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ExamOutcome:
    """What happened for a single exam name."""

    exam_name: str
    status: str  # "updated" | "unmatched" | "failed" | "skipped"
    job_ids: list[int] = field(default_factory=list)
    detail: str = ""
    cutoffs_written: int = 0
    fields_known: int = 0
    fields_total: int = 0


@dataclass
class RunReport:
    """Aggregate result of one pipeline run."""

    started_at: str
    finished_at: str = ""
    provider: str = ""
    model: str = ""
    dry_run: bool = False
    outcomes: list[ExamOutcome] = field(default_factory=list)

    @property
    def updated(self) -> list[ExamOutcome]:
        return [o for o in self.outcomes if o.status == "updated"]

    @property
    def unmatched(self) -> list[ExamOutcome]:
        return [o for o in self.outcomes if o.status == "unmatched"]

    @property
    def failed(self) -> list[ExamOutcome]:
        return [o for o in self.outcomes if o.status == "failed"]

    @property
    def jobs_updated(self) -> int:
        return sum(len(o.job_ids) for o in self.updated)

    def summary(self) -> str:
        parts = [
            f"{len(self.updated)} exam(s) updated",
            f"{self.jobs_updated} job row(s) touched",
        ]
        if self.unmatched:
            parts.append(f"{len(self.unmatched)} unmatched")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        if self.dry_run:
            parts.append("DRY RUN - nothing written")
        return ", ".join(parts)


def _batched(items: Sequence[str], size: int) -> list[list[str]]:
    size = max(1, size)
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def enrich(
    conn,
    provider: Provider,
    settings: Settings,
    *,
    only: Sequence[str] | None = None,
    limit: int | None = None,
    progress=None,
) -> RunReport:
    """Fill the detail tables for every exam in the database.

    Args:
        conn: An open connection from :func:`gjter.db.connect`.
        provider: Where the facts come from.
        settings: Batch size, pauses, dry-run flag and match cutoff.
        only: Restrict the run to these exam names.
        limit: Process at most this many distinct exams.
        progress: Optional ``callable(str)`` used for human-readable output.

    Returns:
        A :class:`RunReport`.
    """
    emit = progress or (lambda _msg: None)

    exams = db.distinct_exams(conn)
    if only:
        wanted = {name.strip().lower() for name in only}
        exams = [e for e in exams if e.strip().lower() in wanted]
        unknown = wanted - {e.strip().lower() for e in exams}
        for name in sorted(unknown):
            emit(f"  ! '{name}' is not in the database; skipping")
    if limit is not None:
        exams = exams[:limit]

    report = RunReport(
        started_at=_now(),
        provider=getattr(provider, "name", "unknown"),
        model=getattr(provider, "model_name", "") or settings.model,
        dry_run=settings.dry_run,
    )

    if not exams:
        report.finished_at = _now()
        emit("No exams to process.")
        return report

    run_id = None
    if not settings.dry_run:
        run_id = db.start_run(
            conn,
            started_at=report.started_at,
            provider=report.provider,
            model=report.model,
            jobs_seen=len(exams),
            dry_run=0,
        )

    batches = _batched(exams, settings.batch_size)
    emit(f"Processing {len(exams)} exam(s) in {len(batches)} batch(es).")

    for index, batch in enumerate(batches, 1):
        emit(f"\n[batch {index}/{len(batches)}] {', '.join(batch)}")

        try:
            response = provider.fetch_batch(batch)
        except ProviderError as exc:
            emit(f"  x batch failed: {exc}")
            for name in batch:
                report.outcomes.append(
                    ExamOutcome(name, "failed", detail=str(exc))
                )
            continue

        for name in batch:
            outcome = _apply_exam(conn, name, response.records, settings, emit)
            report.outcomes.append(outcome)

        is_last = index == len(batches)
        if not is_last and settings.batch_pause_seconds > 0 and _is_live(provider):
            emit(f"  … pausing {settings.batch_pause_seconds:g}s for rate limits")
            time.sleep(settings.batch_pause_seconds)

    report.finished_at = _now()
    if run_id is not None:
        db.finish_run(
            conn,
            run_id,
            finished_at=report.finished_at,
            jobs_updated=report.jobs_updated,
            jobs_failed=len(report.failed) + len(report.unmatched),
            notes=report.summary(),
        )
    return report


def _is_live(provider: Provider) -> bool:
    """True when calls cost money and hit a rate limit."""
    return getattr(provider, "name", "") not in {"curated-offline", "stub"}


def _apply_exam(conn, exam_name, records, settings, emit) -> ExamOutcome:
    """Match one exam to a record and write it, atomically."""
    match = find_best_match(exam_name, records, cutoff=settings.match_cutoff)
    if not match:
        emit(f"  ? {exam_name}: no confident match ({match.reason})")
        return ExamOutcome(exam_name, "unmatched", detail=match.reason)

    record = match.item
    jobs = db.jobs_for_exam(conn, exam_name)
    if not jobs:
        return ExamOutcome(exam_name, "skipped", detail="no job rows for this exam")

    specs = clean_record(record, fields=db.JOB_SPECS_FIELDS)
    pattern = clean_record(record, fields=db.EXAM_PATTERN_FIELDS)
    cutoffs = clean_cutoffs(
        record.get("cutoffs"), year_hint=record.get("year") or record.get("cutoff_year")
    )
    website = validate_url(record.get("official_website"))
    source_url = validate_url(record.get("source_url")) or website

    known = sum(1 for v in {**specs, **pattern}.values() if v and v != UNKNOWN)
    total = len(specs) + len(pattern)

    if settings.dry_run:
        emit(
            f"  = {exam_name}: would update {len(jobs)} job(s), "
            f"{known}/{total} fields known, {len(cutoffs)} cutoff(s) [dry run]"
        )
        return ExamOutcome(
            exam_name,
            "updated",
            [int(j["id"]) for j in jobs],
            f"dry run via {match.strategy}",
            len(cutoffs),
            known,
            total,
        )

    stamp = _now()
    provenance = {
        "data_source": record.get("data_source") or "provider",
        "source_url": source_url,
        "updated_at": stamp,
    }

    written_ids: list[int] = []
    cutoff_rows = 0
    for job in jobs:
        job_id = int(job["id"])
        try:
            with db.transaction(conn):
                db.upsert_job_specs(conn, job_id, {**specs, **provenance})
                db.upsert_exam_pattern(conn, job_id, {**pattern, **provenance})
                cutoff_rows = db.replace_cutoffs(
                    conn,
                    job_id,
                    [{**c, **provenance} for c in cutoffs],
                )
                updates = {"updated_at": stamp}
                if website:
                    updates["official_website"] = website
                if source_url:
                    updates["source_url"] = source_url
                if record.get("verified_on"):
                    updates["verified_on"] = str(record["verified_on"])
                if record.get("conducting_body"):
                    updates["data_source"] = provenance["data_source"]
                assignments = ", ".join(f'"{k}" = ?' for k in updates)
                conn.execute(
                    f"UPDATE jobs SET {assignments} WHERE id = ?",
                    [*updates.values(), job_id],
                )
            written_ids.append(job_id)
        except Exception as exc:  # noqa: BLE001 - reported, run continues
            emit(f"  x {exam_name} (job {job_id}): write failed, rolled back: {exc}")
            log.exception("Write failed for job %s", job_id)

    if not written_ids:
        return ExamOutcome(exam_name, "failed", detail="all writes rolled back")

    emit(
        f"  + {exam_name}: {len(written_ids)} job(s), {known}/{total} fields known, "
        f"{cutoff_rows} cutoff(s) [{match.strategy}]"
    )
    return ExamOutcome(
        exam_name,
        "updated",
        written_ids,
        match.strategy,
        cutoff_rows,
        known,
        total,
    )
