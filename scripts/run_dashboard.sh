#!/usr/bin/env bash
#
# One-command setup and launch for the GJ Terminal dashboard.
# Works in Git Bash (MINGW64) on Windows, and on macOS/Linux.
#
#     ./scripts/run_dashboard.sh
#     ./scripts/run_dashboard.sh --port 8000
#     ./scripts/run_dashboard.sh --rebuild     # start from a fresh database
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PORT=5000
REBUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:?--port needs a number}"; shift 2 ;;
    --rebuild) REBUILD=1; shift ;;
    -h|--help) sed -n '3,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Windows consoles default to a legacy code page; the seed contains rupee signs.
export PYTHONUTF8=1

# --- Find a usable Python -------------------------------------------------
PY=""
for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PY="$candidate"
      break
    fi
  fi
done

if [[ -z "$PY" ]]; then
  echo "ERROR: Python 3.9+ not found. Install it from https://python.org/downloads" >&2
  echo "       On Windows, tick 'Add Python to PATH' during installation." >&2
  exit 1
fi
echo "==> Using $($PY --version) ($PY)"

# --- Dependency -----------------------------------------------------------
if ! "$PY" -c "import flask" 2>/dev/null; then
  echo "==> Flask not found. Installing..."
  if ! "$PY" -m pip install --quiet --disable-pip-version-check flask 2>/tmp/pip_err.log; then
    echo
    echo "ERROR: could not install Flask." >&2
    sed 's/^/    /' /tmp/pip_err.log >&2 || true
    echo >&2
    if grep -q "externally-managed-environment" /tmp/pip_err.log 2>/dev/null; then
      cat >&2 <<'EOF'
Your Python is "externally managed" (common on Debian/Ubuntu and Homebrew).
Use a virtual environment:

    python3 -m venv .venv
    source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
    pip install flask
    ./scripts/run_dashboard.sh
EOF
    else
      echo "Try installing it manually:  $PY -m pip install flask" >&2
    fi
    exit 1
  fi
  # Installing into a --user location may still not be importable.
  if ! "$PY" -c "import flask" 2>/dev/null; then
    echo "ERROR: Flask installed but is not importable by $PY." >&2
    echo "       You likely have multiple Pythons. Try: $PY -m pip install flask" >&2
    exit 1
  fi
fi

# --- Database -------------------------------------------------------------
if [[ $REBUILD -eq 1 ]]; then
  echo "==> Removing existing database..."
  rm -f jobs.db jobs.db-wal jobs.db-shm
fi

echo "==> Preparing database..."
"$PY" database_setup.py

NEEDS_FILL=$("$PY" - <<'PYEOF'
import sqlite3
try:
    conn = sqlite3.connect("jobs.db")
    filled = conn.execute("SELECT COUNT(*) FROM job_specs").fetchone()[0]
    conn.close()
    print("0" if filled else "1")
except Exception:
    print("1")
PYEOF
)

if [[ "$NEEDS_FILL" == "1" ]]; then
  echo "==> Filling exam details from the curated dataset (no API key needed)..."
  "$PY" data_scout.py --offline
else
  echo "==> Exam details already present; skipping fill."
  echo "    (use --rebuild to start over)"
fi

"$PY" -m gjter verify

cat <<EOF

============================================================
  GJ Terminal is starting.

  Open:  http://127.0.0.1:${PORT}

  Ctrl+K  search        Click a header  sort
  Arrows  scroll        Click a row     details

  Press Ctrl+C here to stop.
============================================================

EOF

exec "$PY" app.py --port "$PORT"
