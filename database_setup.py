#!/usr/bin/env python3
"""Create or migrate ``jobs.db`` and insert the base job rows.

Backwards-compatible entry point. Running it with no arguments does what it
always did - leaves you with a ready-to-use ``jobs.db`` - but it is now
**non-destructive**: the schema is migrated in place and the seed rows are
upserted, so running it twice no longer wipes enriched data.

    python database_setup.py                 # create or migrate, then seed
    python database_setup.py --force-reset   # the old destructive behaviour
    python database_setup.py --no-seed       # schema only

The old version executed ``DROP TABLE`` at import time, which meant simply
importing this module destroyed the database.
"""

from __future__ import annotations

import sys

from gjter.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    # Forward global flags that must precede the subcommand.
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
    raise SystemExit(main([*leading, "init", *rest]))
