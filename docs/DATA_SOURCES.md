# Data Sources

Every fact in the seed and in the curated dataset was checked against the
conducting body's own published material. This file records where each came
from so any claim can be re-verified independently.

**Verification date: 2026-07-27.**

---

## Primary sources

| Exam | Conducting body | Official source |
|---|---|---|
| UPSC CSE | Union Public Service Commission | <https://upsc.gov.in> |
| UPSC ESE | Union Public Service Commission | <https://upsc.gov.in> |
| NDA | Union Public Service Commission | <https://upsc.gov.in> |
| SSC CGL | Staff Selection Commission | <https://ssc.gov.in> |
| RBI Grade B | Reserve Bank of India | <https://opportunities.rbi.org.in> |
| SBI PO | State Bank of India | <https://sbi.co.in/web/careers> |
| IBPS PO | Institute of Banking Personnel Selection | <https://www.ibps.in> |
| LIC AAO | Life Insurance Corporation of India | <https://licindia.in/web/guest/careers> |
| ISRO ICRB | Indian Space Research Organisation | <https://www.isro.gov.in/CareerOpportunities.html> |
| DRDO | DRDO Recruitment & Assessment Centre | <https://rac.gov.in> |

Pay figures follow the 7th Central Pay Commission matrix for central government
posts. Bank and corporation posts use their own negotiated scales and are
**not** on the CPC matrix — `pay_level` is NULL for those by design.

---

## Verified values

### Pay (entry basic pay)

| Post | Basic pay | Basis |
|---|---|---|
| IAS / IPS / IFS | ₹56,100 | 7th CPC Level 10, Junior Time Scale |
| UPSC ESE officer | ₹56,100 | 7th CPC Level 10 |
| ISRO Scientist/Engineer SC | ₹56,100 | 7th CPC Level 10 (₹56,100–1,77,500) |
| DRDO Scientist B | ₹56,100 | 7th CPC Level 10 |
| SSC CGL AAO | ₹47,600 | 7th CPC Level 8 (₹47,600–1,51,100) |
| SBI PO | ₹48,480 | JMGS-I bank scale |
| IBPS PO | ₹48,480 | JMGS-I (₹48,480–85,920) |
| RBI Grade B | ₹55,200 | RBI officer scale ₹55200-2850(9)-80850-EB-2850(2)-86550-3300(4)-99750 |
| LIC AAO | ₹88,635 | LIC scale ₹88635-4385(14)-150025-4750(4)-169025 |

These are **basic pay**, not gross. Gross is substantially higher once DA, HRA
and other allowances apply, and varies by city classification and DA cycle.
Conflating the two was one of the errors in the original seed.

### Age limits (unreserved category)

| Exam | Limit | Reckoning date |
|---|---|---|
| UPSC CSE | 21–32 | 1 August of the exam year |
| UPSC ESE | 21–30 | 1 January of the exam year |
| NDA | ~16.5–19.5 | Exact DOB window per notification |
| SSC CGL (AAO) | 18–30 | Per notification |
| RBI Grade B | 21–30 | Per notification (32 with M.Phil, 34 with Ph.D.) |
| SBI PO | 21–30 | Per advertisement |
| IBPS PO | 20–30 | Per notification |
| LIC AAO (Generalist) | 21–30 | Per notification |
| ISRO Scientist SC | up to 28 | Per advertisement (30 for ME/M.Tech entry) |
| DRDO Scientist B | up to 35 | Closing date, GATE-based advertisement |

An age band without its reckoning date is unusable, which is why every value
carries one.

### Cutoffs held

Only UPSC CSE. Prelims 2025, marks out of 200:

| Category | Cutoff |
|---|---|
| General | 92.66 |
| EWS | 89.34 |
| OBC | 92.00 |
| SC | 84.00 |
| ST | 82.66 |

Source: UPSC cut-off marks publications, <https://upsc.gov.in/examinations/previous-question-papers/cut-off-marks>.

**No other exam in this dataset has cutoff rows.** SSC, IBPS, SBI, LIC, ISRO and
DRDO either do not publish category-wise cutoffs in a comparable form, or publish
them per-cycle in PDFs that have not been transcribed here. Zero rows is the
correct representation — an LLM asked for these will readily invent them, which
is precisely why the prompt forbids it and the curated dataset leaves them empty.

---

## Corrections applied to the original seed

The original `database_setup.py` seed was unsourced and contained material
errors. The full table of corrections — 15 fields across 8 posts — is in
[`../reports/CODE_AUDIT.md`](../reports/CODE_AUDIT.md) §5. Summary of the most
consequential:

- **LIC AAO salary** understated as `₹40,000+` against an actual ₹88,635 basic
- **ISRO and DRDO age limits inverted** (ISRO listed 21–35 vs actual ≤28; DRDO listed 21–28 vs actual ≤35)
- **SSC CGL AAO** marked Non-Gazetted; it is Group B **Gazetted**
- **`pay_level` populated for four posts not on the CPC matrix** (RBI, SBI, IBPS, LIC)

---

## Re-verification

Eligibility rules, pay and vacancy counts change with every notification cycle.

```bash
# What is oldest?
python -m gjter export | python -c "
import json,sys
for j in sorted(json.load(sys.stdin), key=lambda r: r.get('verified_on') or ''):
    print(j.get('verified_on'), j['post_name'])
"
```

To refresh a single exam after checking the official site, update
`gjter/seed.py` and `gjter/data/curated_exams.json`, bump `verified_on`, then:

```bash
python database_setup.py                      # idempotent; updates in place
python data_scout.py --offline --only "UPSC CSE"
```

**A note on model-sourced rows:** anything with `data_source = 'gemini'` has not
been human-verified. The prompt instructs the model to return
`"Information not available"` rather than guess, and `temperature` is 0, but
neither is a guarantee. Check `source_url` before relying on such a row.
