#!/usr/bin/env python3
"""Flask web server for the GJ Terminal dashboard.

Serves ``templates/index.html`` (the sortable job table) and
``templates/details.html`` (the per-exam card grid), plus the
``/update_status`` endpoint the dashboard polls every 2 seconds.

    python app.py                  # http://127.0.0.1:5000
    python app.py --port 8000
    python app.py --host 0.0.0.0   # LAN; refuses to also enable debug

The templates were written against a server that was never committed. Every
variable they reference is supplied here:

  index.html    jobs[], is_updating
  details.html  job, job_spec, exam_pattern, cutoffs[], url_for('index')

Both templates read ``job.application_fee``, ``job.vacancies`` and
``job.vacancies_year``, which did not exist in the schema before v3 - the Fee
and Vacancies cards could only ever show their fallback text.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import threading
from pathlib import Path

try:
    from flask import Flask, abort, jsonify, render_template
except ImportError:  # pragma: no cover - dependency guidance
    sys.exit(
        "Flask is not installed. Install the web extra:\n"
        "    pip install -e '.[web]'\n"
        "or:\n"
        "    pip install flask"
    )

from gjter import db
from gjter.config import UNKNOWN, settings_from_env
from gjter.console import emit as console_emit
from gjter.console import enable_utf8
from gjter.console import safe as console_safe

log = logging.getLogger("gjter.web")

app = Flask(__name__)

# Guards the flag the dashboard polls. A plain bool would be read and written
# from both the request thread and any background refresh thread.
_update_lock = threading.Lock()
_update_state = {"updating": False}

#: Values that mean "we do not know". The templates already filter a few of
#: these; centralising the list keeps sentinel text out of the UI entirely.
_EMPTY_VALUES = frozenset(
    {"", "n/a", "na", "tba", "tbd", "none", "null", "-", UNKNOWN.lower()}
)


def is_updating() -> bool:
    with _update_lock:
        return _update_state["updating"]


def set_updating(value: bool) -> None:
    with _update_lock:
        _update_state["updating"] = bool(value)


def get_db() -> sqlite3.Connection:
    """Open a connection for this request.

    SQLite connections are not shareable across threads and Flask serves
    requests on several, so a connection is opened and closed per request
    rather than cached globally.
    """
    settings = settings_from_env()
    if not Path(settings.db_path).exists():
        abort(
            503,
            description=(
                f"Database not found at {settings.db_path}. "
                "Run `python database_setup.py` first."
            ),
        )
    return db.connect(settings.db_path, read_only=True)


def _clean(value):
    """Return ``None`` for sentinel/placeholder text so templates fall back.

    Without this, a row enriched with "Information not available" would render
    that phrase inside the table instead of the template's own 'N/A'.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in _EMPTY_VALUES:
        return None
    return value


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: _clean(row[key]) for key in row.keys()}


@app.route("/")
def index():
    """The dashboard table."""
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT id, post_name, exam_name, conducting_body, "group", '
            "gazetted_status, pay_level, salary, eligibility, age_limit, "
            "pet_status FROM jobs ORDER BY id"
        ).fetchall()
        jobs = [_row_to_dict(row) for row in rows]
    except sqlite3.Error as exc:
        log.error("Failed to load jobs: %s", exc)
        jobs = []
    finally:
        conn.close()

    return render_template("index.html", jobs=jobs, is_updating=is_updating())


@app.route("/details/<int:job_id>")
def details(job_id: int):
    """The per-job card grid."""
    conn = get_db()
    try:
        job = _row_to_dict(
            conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        )
        if job is None:
            abort(404, description=f"No job with id {job_id}.")

        job_spec = _row_to_dict(
            conn.execute(
                "SELECT * FROM job_specs WHERE job_id = ?", (job_id,)
            ).fetchone()
        )
        exam_pattern = _row_to_dict(
            conn.execute(
                "SELECT * FROM exam_pattern WHERE job_id = ?", (job_id,)
            ).fetchone()
        )
        # Newest year first: details.html labels the card with cutoffs[0].year.
        cutoffs = [
            _row_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM job_cutoffs WHERE job_id = ? "
                "ORDER BY year DESC, id ASC",
                (job_id,),
            ).fetchall()
        ]
    finally:
        conn.close()

    return render_template(
        "details.html",
        job=job,
        job_spec=job_spec,
        exam_pattern=exam_pattern,
        cutoffs=cutoffs,
    )


@app.route("/update_status")
def update_status():
    """Polled every 2 s by index.html to drive the flickering indicator."""
    response = jsonify({"updating": is_updating()})
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.route("/healthz")
def healthz():
    """Liveness probe that also reports whether the database is usable."""
    settings = settings_from_env()
    if not Path(settings.db_path).exists():
        return jsonify({"status": "degraded", "reason": "database missing"}), 503
    try:
        conn = db.connect(settings.db_path, read_only=True)
        try:
            stats = db.coverage(conn)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return jsonify({"status": "error", "reason": str(exc)}), 503
    return jsonify({"status": "ok", "coverage": stats})


@app.errorhandler(404)
def handle_404(error):
    return (
        render_template_string_fallback("Not found", error),
        404,
    )


@app.errorhandler(503)
def handle_503(error):
    return (
        render_template_string_fallback("Service unavailable", error),
        503,
    )


def render_template_string_fallback(title: str, error) -> str:
    """Minimal error page styled to match the dashboard.

    Kept inline rather than as a template so an error can still be rendered if
    the templates directory is missing.
    """
    description = getattr(error, "description", str(error))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - GJ Terminal</title>
<style>
  body {{ font-family: 'Manrope', system-ui, sans-serif; background:#0d0d0f;
         color:#e0e0e0; margin:0; padding:2rem 3rem;
         background-image: radial-gradient(rgba(255,255,255,0.05) 1px, transparent 1px);
         background-size: 20px 20px; }}
  .box {{ max-width:640px; margin:12vh auto; background:rgba(255,255,255,0.03);
          border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:2rem; }}
  h1 {{ margin:0 0 1rem; font-size:1.6rem; color:#fff; }}
  p {{ color:#b0b0b0; line-height:1.6; }}
  code {{ background:rgba(255,255,255,0.08); padding:2px 6px; border-radius:4px; }}
  a {{ color:#FFD700; text-decoration:none; }}
</style></head>
<body><div class="box">
  <h1>{title}</h1>
  <p>{description}</p>
  <p><a href="/">&larr; Back to Terminal</a></p>
</div></body></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the GJ Terminal dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    # A Windows console using cp1252 cannot encode the arrow below.
    enable_utf8()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # The debug console offers arbitrary code execution to anyone who can reach
    # it. Binding it to a non-loopback interface would expose that to the network.
    if args.debug and args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error(
            "--debug may not be combined with a non-loopback --host: the Werkzeug "
            "debugger allows remote code execution."
        )

    settings = settings_from_env()
    if not Path(settings.db_path).exists():
        print(
            f"Warning: no database at {settings.db_path}.\n"
            "  Run `python database_setup.py` and then "
            "`python data_scout.py --offline`.",
            file=sys.stderr,
        )

    console_emit(console_safe(f"GJ Terminal \u2192 http://{args.host}:{args.port}"))
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
