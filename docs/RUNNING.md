# Running the dashboard

Tested on Windows (Git Bash / MINGW64, which is what VS Code's terminal uses),
macOS and Linux.

---

## Get the branch

The work is on a branch, not on `main`. From your repo folder:

```bash
git fetch origin
git checkout arena/019f9ffb-gj-ter-perplex-fills-data-from
```

Confirm you have it — you should now see `app.py`, `gjter/`, `templates/`:

```bash
ls
```

---

## Run it (4 commands)

```bash
pip install flask
python database_setup.py
python data_scout.py --offline
python app.py
```

Then open <http://127.0.0.1:5000>.

Press `Ctrl+C` in the terminal to stop the server.

---

## What each command does

| Command | Effect |
|---|---|
| `pip install flask` | The only dependency needed for the UI. The rest of the project uses the standard library. |
| `python database_setup.py` | Creates `jobs.db` and seeds 12 posts. Safe to re-run — it will not wipe data. |
| `python data_scout.py --offline` | Fills eligibility, exam pattern and cutoffs from the bundled verified dataset. **No API key, no network, no cost.** |
| `python app.py` | Serves the dashboard on <http://127.0.0.1:5000>. |

---

## Using the UI

**Table page** (`/`)

- Click any **column header** to sort; click again to reverse.
- Click any **row** to open its detail page.
- **`Ctrl+K`** opens search. Type to filter, `Enter` or `Esc` to close.
- **Arrow keys** scroll — left/right moves the wide table horizontally.

**Detail page** (`/details/1`)

Seven cards: Job Specifications, Exam Pattern, Important Dates, Recent Year
Cutoffs, Application Fee, Official Website, Vacancies.
`←` (top left) returns to the table.

Row 1 (IAS Officer) is the fullest example — it is the only exam with published
cutoffs, so its Cutoffs card shows real 2025 UPSC marks.

---

## Other useful commands

```bash
python app.py --port 8000        # if 5000 is taken
python -m gjter status           # coverage summary in the terminal
python -m gjter verify           # integrity checks
python -m gjter export -o out.json
python -m pytest                 # 161 tests
```

To check the server is healthy without opening a browser:

```bash
curl http://127.0.0.1:5000/healthz
```

---

## Troubleshooting

**`bash: $'\377\376[': command not found`**

You pasted UTF-16 text into Git Bash — those bytes are a byte-order mark, not a
command. It is harmless. Retype the command rather than pasting it, or paste
into the terminal with `Shift+Insert`.

**`No module named flask`**

```bash
python -m pip install flask
```

If `python` is not found in Git Bash, try `py -3` or `winpty python` instead.

**`Address already in use` / port 5000 busy**

On Windows, port 5000 is sometimes taken. Use another:

```bash
python app.py --port 8000
```

**"No job data found. Run database_setup.py."**

The table rendered but the database is empty. Run:

```bash
python database_setup.py && python data_scout.py --offline
```

**"Database not found" (503 page)**

Same fix as above — you started the server before creating `jobs.db`.

**`UnicodeEncodeError: 'charmap' codec can't encode character`**

This should no longer happen: `gjter/console.py` switches the console to UTF-8
and transliterates `₹`/`→` when it cannot. If you still hit it, set:

```bash
export PYTHONUTF8=1
```

**Cards show "Details not available."**

You are on an older database. Re-run `python database_setup.py` — the fee and
vacancy columns were added in schema v3 and the migration is additive.

**Page loads but clicking/sorting does nothing**

Hard-refresh to clear the cached old JavaScript: `Ctrl+Shift+R`.
Then check the browser console (`F12`) for errors.

---

## Starting clean

```bash
rm -f jobs.db jobs.db-wal jobs.db-shm
python database_setup.py
python data_scout.py --offline
```

`jobs.db` is gitignored — it is a build artefact and is meant to be regenerated.
