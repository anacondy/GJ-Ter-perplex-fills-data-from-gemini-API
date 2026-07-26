#!/usr/bin/env python3
"""Fill the exam detail tables from a data provider.

Backwards-compatible entry point.

    export GEMINI_API_KEY='...'
    python data_scout.py                # live Gemini run
    python data_scout.py --offline      # curated dataset, no key, no network
    python data_scout.py --dry-run      # fetch and match, write nothing
    python data_scout.py --only "UPSC CSE"

The previous version hardcoded the API key in source (one real key was committed
and is now burned), trusted ``response.text`` blindly, and fuzzy-matched exam
names loosely enough to write one exam's rules onto another. See
``reports/CODE_AUDIT.md`` for the full list.
"""

from __future__ import annotations

import sys

from gjter.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    leading: list[str] = []
    rest: list[str] = []
    iterator = iter(argv)
    for token in iterator:
        if token in {"--db", "-v", "--verbose"}:
            leading.append(token)
            if token == "--db":
                leading.append(next(iterator, ""))
        else:
            rest.append(token)
    raise SystemExit(main([*leading, "scout", *rest]))
