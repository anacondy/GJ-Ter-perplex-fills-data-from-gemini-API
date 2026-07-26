"""Command line interface.

Exposed both as ``python -m gjter`` and, for backwards compatibility, through
the original ``database_setup.py`` and ``data_scout.py`` entry points.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

from . import __version__, db
from .config import DEFAULT_DB_PATH, ConfigError, Settings, settings_from_env
from .providers import ProviderError, get_provider


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _emit(message: str) -> None:
    print(message, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gjter",
        description="Build and enrich the Indian government exam database.",
    )
    parser.add_argument("--version", action="version", version=f"gjter {__version__}")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"Path to the SQLite database (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")

    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Create or migrate the schema and seed rows.")
    p_init.add_argument(
        "--force-reset",
        action="store_true",
        help="Drop every table first. Destroys all existing data.",
    )
    p_init.add_argument(
        "--no-seed", action="store_true", help="Migrate the schema but insert no rows."
    )

    p_scout = sub.add_parser("scout", help="Fill the detail tables.")
    p_scout.add_argument(
        "--provider",
        default="gemini",
        choices=["gemini", "offline"],
        help="Where facts come from. 'offline' uses the bundled curated dataset.",
    )
    p_scout.add_argument(
        "--offline",
        action="store_true",
        help="Shorthand for --provider offline (no API key, no network).",
    )
    p_scout.add_argument("--model", default=None, help="Gemini model name.")
    p_scout.add_argument("--batch-size", type=int, default=None)
    p_scout.add_argument(
        "--pause", type=float, default=None, help="Seconds between batches."
    )
    p_scout.add_argument(
        "--max-retries", type=int, default=None, help="Attempts per batch."
    )
    p_scout.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and match, but write nothing to the database.",
    )
    p_scout.add_argument(
        "--only",
        nargs="+",
        metavar="EXAM",
        help="Restrict the run to these exam names.",
    )
    p_scout.add_argument(
        "--limit", type=int, default=None, help="Process at most N distinct exams."
    )

    p_status = sub.add_parser("status", help="Show coverage and recent runs.")
    p_status.add_argument("--json", action="store_true", help="Machine-readable output.")

    p_export = sub.add_parser("export", help="Dump the database as JSON.")
    p_export.add_argument("-o", "--output", type=Path, default=None)

    sub.add_parser("verify", help="Run integrity checks and exit non-zero on failure.")

    return parser


# --------------------------------------------------------------------- commands


def cmd_init(args, settings: Settings) -> int:
    from .seed import seed

    conn = db.connect(settings.db_path)
    try:
        if args.force_reset:
            _emit("! --force-reset: dropping all tables.")
            db.reset(conn)
        version = db.migrate(conn)
        _emit(f"Schema ready at v{version}: {settings.db_path}")
        if not args.no_seed:
            seed(conn, progress=_emit)
        counts = db.coverage(conn)
        _emit(f"jobs={counts['jobs']} distinct exams={counts['exams']}")
        return 0
    finally:
        conn.close()


def cmd_scout(args, settings: Settings) -> int:
    from .pipeline import enrich

    provider_name = "offline" if getattr(args, "offline", False) else args.provider

    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)
        if not db.distinct_exams(conn):
            _emit("Database has no jobs yet. Run `python database_setup.py` first.")
            return 1

        try:
            provider = get_provider(
                provider_name, settings=settings, model=args.model
            )
        except (ProviderError, ConfigError) as exc:
            _emit(f"Error: {exc}")
            return 2

        _emit(
            f"Provider: {provider.name}"
            + (f" ({settings.model})" if provider_name == "gemini" else "")
        )
        with provider:
            report = enrich(
                conn,
                provider,
                settings,
                only=args.only,
                limit=args.limit,
                progress=_emit,
            )

        _emit("\n" + report.summary())
        for outcome in report.unmatched:
            _emit(f"  unmatched: {outcome.exam_name} ({outcome.detail})")
        for outcome in report.failed:
            _emit(f"  failed:    {outcome.exam_name} ({outcome.detail})")

        return 0 if not report.failed else 3
    finally:
        conn.close()


def cmd_status(args, settings: Settings) -> int:
    try:
        conn = db.connect(settings.db_path, read_only=True)
    except FileNotFoundError as exc:
        _emit(str(exc))
        return 1
    try:
        counts = db.coverage(conn)
        runs = conn.execute(
            "SELECT started_at, finished_at, provider, jobs_updated, notes "
            "FROM scout_runs ORDER BY id DESC LIMIT 5"
        ).fetchall() if _has_table(conn, "scout_runs") else []

        if args.json:
            _emit(
                json.dumps(
                    {"coverage": counts, "recent_runs": [dict(r) for r in runs]},
                    indent=2,
                )
            )
            return 0

        _emit(f"Database: {settings.db_path}")
        _emit(f"Schema version: {counts['schema_version']}")
        _emit(f"Jobs: {counts['jobs']}  (distinct exams: {counts['exams']})")
        _emit(f"  job_specs rows:    {counts['job_specs']}")
        _emit(f"  exam_pattern rows: {counts['exam_pattern']}")
        _emit(f"  job_cutoffs rows:  {counts['job_cutoffs']}")
        _emit(f"  jobs with website: {counts['jobs_with_website']}/{counts['jobs']}")
        if runs:
            _emit("\nRecent runs:")
            for run in runs:
                _emit(
                    f"  {run['started_at']} via {run['provider']}: {run['notes'] or ''}"
                )
        return 0
    finally:
        conn.close()


def _has_table(conn, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def cmd_export(args, settings: Settings) -> int:
    try:
        conn = db.connect(settings.db_path, read_only=True)
    except FileNotFoundError as exc:
        _emit(str(exc))
        return 1
    try:
        payload = []
        for job in conn.execute("SELECT * FROM jobs ORDER BY id"):
            job_id = job["id"]
            record = dict(job)
            specs = conn.execute(
                "SELECT * FROM job_specs WHERE job_id = ?", (job_id,)
            ).fetchone()
            pattern = conn.execute(
                "SELECT * FROM exam_pattern WHERE job_id = ?", (job_id,)
            ).fetchone()
            cutoffs = conn.execute(
                "SELECT category, score, year, source_url FROM job_cutoffs "
                "WHERE job_id = ? ORDER BY id",
                (job_id,),
            ).fetchall()
            record["specs"] = dict(specs) if specs else None
            record["exam_pattern"] = dict(pattern) if pattern else None
            record["cutoffs"] = [dict(c) for c in cutoffs]
            payload.append(record)

        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
            _emit(f"Wrote {len(payload)} job(s) to {args.output}")
        else:
            _emit(text)
        return 0
    finally:
        conn.close()


def cmd_verify(args, settings: Settings) -> int:
    """Integrity checks. Exits non-zero when the database is inconsistent."""
    try:
        conn = db.connect(settings.db_path, read_only=True)
    except FileNotFoundError as exc:
        _emit(str(exc))
        return 1

    problems: list[str] = []
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"SQLite integrity_check returned {integrity!r}")

        for violation in conn.execute("PRAGMA foreign_key_check").fetchall():
            problems.append(f"Foreign key violation: {tuple(violation)}")

        orphans = conn.execute(
            "SELECT COUNT(*) FROM job_specs WHERE job_id NOT IN (SELECT id FROM jobs)"
        ).fetchone()[0]
        if orphans:
            problems.append(f"{orphans} orphaned job_specs row(s)")

        dupes = conn.execute(
            "SELECT COUNT(*) FROM (SELECT job_id FROM job_specs "
            "GROUP BY job_id HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        if dupes:
            problems.append(f"{dupes} job(s) have more than one job_specs row")

        bad_urls = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE official_website IS NOT NULL "
            "AND official_website <> '' AND official_website NOT LIKE 'http%'"
        ).fetchone()[0]
        if bad_urls:
            problems.append(f"{bad_urls} job(s) have a non-URL official_website")

        if problems:
            _emit("FAILED:")
            for problem in problems:
                _emit(f"  - {problem}")
            return 1
        _emit("All integrity checks passed.")
        return 0
    finally:
        conn.close()


# ------------------------------------------------------------------------ entry


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if not args.command:
        parser.print_help()
        return 0

    try:
        settings = settings_from_env(
            db_path=args.db,
            model=getattr(args, "model", None),
            batch_size=getattr(args, "batch_size", None),
            batch_pause_seconds=getattr(args, "pause", None),
            max_retries=getattr(args, "max_retries", None),
            dry_run=getattr(args, "dry_run", False) or None,
        )
    except ConfigError as exc:
        _emit(f"Configuration error: {exc}")
        return 2

    handlers = {
        "init": cmd_init,
        "scout": cmd_scout,
        "status": cmd_status,
        "export": cmd_export,
        "verify": cmd_verify,
    }
    try:
        return handlers[args.command](args, settings)
    except KeyboardInterrupt:
        _emit("\nInterrupted. Committed work is safe; partial writes were rolled back.")
        return 130
    except (ConfigError, ProviderError) as exc:
        _emit(f"Error: {exc}")
        return 2
    except sqlite3.Error as exc:
        _emit(f"Database error: {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
