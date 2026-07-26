# Frontend Audit — GJ Terminal dashboard

**Audit date:** 2026-07-27
**Scope:** `templates/index.html`, `templates/details.html`, and the Flask server they require.

---

## 1. Context

The two templates were supplied after the backend audit. Neither they nor their
server were ever committed to the repository — the backend audit therefore
concluded "no frontend exists", which was wrong. This document covers them.

The important consequence: **the templates reference a server that did not
exist in the repo.** Without `app.py`, no route, no template variable and no
endpoint the JavaScript polls was defined. The whole UI was unreachable. This is
the largest single piece of "things sitting there as dead code but not working."

The visual design is unchanged. Every colour, font, spacing rule, animation,
grid placement and breakpoint is preserved byte-for-byte. Only defects were
touched.

---

## 2. Critical

### F1 — JavaScript syntax error kills every interactive feature

**Severity: CRITICAL · Fixed**

`sortTableByColumn` in `index.html` contained four malformed calls:

```js
const aColText = a.querySelector`td:nth-child(${columnIndex + 1})`).textContent.trim();
//                              ^ backtick opens a tagged template     ^ unmatched )
```

`a.querySelector\`...\`` parses as a *tagged template literal*, and the trailing
`)` then has no opening parenthesis. Verified against Node:

```
SyntaxError: Unexpected token ')'
```

A syntax error is thrown at **parse** time, before a single statement executes.
Because all of the page's JavaScript lives in one `<script>` block, this did not
merely break sorting — it broke **everything on the page**:

- column sorting
- `Ctrl+K` search overlay
- arrow-key scrolling
- row-click navigation to `/details/<id>`
- the `/update_status` poller and the flickering indicator

Every one of those features looked implemented and was completely dead.

**Fixed:** rewritten as `a.querySelector('td:nth-child(' + n + ')')` using proper
call syntax, with null guards. The rendered output is now verified with
`node --check` in `tests/test_web.py`.

### F2 — No server: every template variable was undefined

**Severity: CRITICAL · Fixed**

The templates require `jobs`, `is_updating`, `job`, `job_spec`, `exam_pattern`,
`cutoffs`, `url_for('index')`, and a `/update_status` JSON endpoint. None
existed in the repository.

Jinja renders an undefined variable as an empty string rather than raising, so
`let wasUpdating = {{ is_updating | lower }};` would have emitted:

```js
let wasUpdating = ;     // SyntaxError - kills the script again, independently
```

**Fixed:** `app.py` supplies every variable, with `/`, `/details/<int:job_id>`,
`/update_status` and `/healthz`. A test asserts the rendered line is a literal
`true` or `false`.

---

## 3. High

### F3 — Two cards could never display data

**Severity: HIGH · Fixed**

`details.html` reads `job.application_fee`, `job.vacancies` and
`job.vacancies_year`. **None of those columns existed in the schema.** The
Application Fee and Vacancies cards were therefore hardcoded, in effect, to
their fallback text — "Details not available." and "Details announced in
notification." — no matter what was in the database.

**Fixed:** added as nullable columns in schema v3 and populated with verified
figures (UPSC ₹100 with exemptions, RBI ₹850+GST, LIC ₹700+GST, SBI ₹750,
IBPS ₹850, SSC ₹100, NDA ₹100, ESE ₹200, DRDO ₹100, ISRO ₹750 refundable) and
2025 vacancy counts. Sources in `docs/DATA_SOURCES.md`.

### F4 — Numeric sorting produced nonsense

**Severity: HIGH · Fixed**

```js
parseFloat(aColText.replace(/[₹,+-]/g,''))
```

Stripping `-` **concatenates** the parts of a range. Measured against the real
column values:

| Cell value | Old result | Correct |
|---|---|---|
| `21-32 years (unreserved)` | **2132** | 21 |
| `₹56,100 basic pay (7th CPC Level 10)` | 56100 | 56100 |
| `N/A` | `NaN` | sorts last |

So Age Limit sorted by a fabricated four-digit number, and any `NaN` made the
comparator non-transitive, which leaves row order arbitrary.

**Fixed:** extracts the first number with a regex and sorts null values to the
end in both directions. Verified against real column values in Node.

---

## 4. Medium

| # | Issue | Status |
|---|---|---|
| F5 | `target="_blank"` without `rel="noopener noreferrer"` — the opened page gets a `window.opener` handle back to the dashboard | Fixed; asserted by a test |
| F6 | `official_website` rendered unconditionally into `href`. The template filters `'n/a'`/`'tba'` but not `"Information not available"`, which is exactly what the old backend wrote | Fixed at both layers: `validate_url()` server-side, plus `_clean()` mapping sentinels to `None` |
| F7 | No `/healthz`; no way to tell a running-but-empty dashboard from a broken one | Added |
| F8 | Missing database produced an unhandled `sqlite3.OperationalError` traceback | Returns a styled 503 naming `database_setup.py` |
| F9 | `/update_status` had no cache headers, relying solely on a `?timestamp` cache-buster | `Cache-Control: no-store` added |
| F10 | `is_updating` was a bare module global mutated from multiple threads | Guarded by a lock |

---

## 5. Low

- **F11** — `checkUpdateStatus` polls every 2 s forever, including in background
  tabs. Left as-is: it is the intended behaviour and changing it would alter the
  UX you asked me to preserve. Noted as a battery consideration.
- **F12** — `min-width: 1400px` on the table forces horizontal scrolling on
  mobile. Deliberate (the container scrolls, and the scrollbar is hidden), so
  left alone.
- **F13** — Google Fonts `@import` blocks first paint and is a third-party
  request. Left alone; changing it would alter the typography.
- **F14** — No `<meta name="description">` or favicon. Cosmetic; not touched to
  keep the diff to defects only.

---

## 6. What was deliberately NOT changed

Per your instruction that the UI and aesthetics stay identical:

- All CSS is byte-for-byte identical: colours (`#0d0d0f`, `#121212`, `#FFD700`),
  the Manrope font stack, the radial-dot background, the 20 px grid, card
  hover-lift, `flicker` keyframes, sticky blurred header, hidden scrollbars, and
  every `@media` breakpoint including the 1025 px grid placement.
- Markup structure, class names, IDs and column order are unchanged.
- All keyboard shortcuts behave the same.
- The only markup additions are `rel="noopener noreferrer"` on existing
  `target="_blank"` links, and an optional provenance footer on the details page
  that renders only when a source URL exists.

---

## 7. Rating

| Dimension | Score | Reasoning |
|---|---|---|
| **Visual design** | **8.5 / 10** | Genuinely good. Coherent dark theme, restrained palette, considered hover states, a sensible responsive grid. The strongest part of the whole project. |
| **Correctness** | **0 / 10** | A parse error meant literally no JavaScript ran, and no server existed to render the templates. Nothing worked. |
| **Accessibility** | **3 / 10** | Rows are clickable `<tr>` with no `tabindex`, `role` or keyboard handler — unreachable without a mouse. Sortable headers announce nothing to a screen reader. `#888` on `#1e1e1e` is roughly 3.5:1, below the 4.5:1 WCAG AA threshold. Not fixed: would require markup changes beyond the "don't change the UI" boundary. Recommended as a follow-up. |
| **Security** | **5 / 10** | Jinja autoescaping covers XSS; `window.opener` and the unvalidated `href` were real gaps, both now fixed. |
| **Robustness** | **2 / 10** | No null guards, no empty-state handling beyond the one placeholder row, no error states. |
| **Overall** | **4 / 10** | An attractive shell with nothing behind it and a fatal typo in front of it. |

The frontend and backend fail the same way: **both look finished and report
success while doing nothing.** The backend printed `🎉 Mission Complete!` over
corrupt writes; the frontend renders a polished table whose every control is
inert. That symmetry is the defining weakness of this codebase.

---

## 8. Recommended follow-ups (not done — they would change the UI)

1. **Accessibility.** Make rows keyboard-reachable (`tabindex="0"`, `role="link"`,
   Enter handler), add `aria-sort` to headers, and lift muted text from `#888`
   to about `#9e9e9e` for AA contrast.
2. **Server-side sort/filter** if the table ever exceeds a few hundred rows;
   the current approach re-sorts the whole DOM in JavaScript.
3. **Wire the update indicator to real work.** `set_updating()` exists and is
   correct, but nothing calls it yet — connecting it to a background
   `gjter scout` run is the obvious next step, and would make the flickering dot
   mean something.
