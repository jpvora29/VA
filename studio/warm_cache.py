"""Pre-build the Studio filter cache so app launch is instant.

The first time the Studio page loads for a given DB it must run a DISTINCT scan
per filter column. On a large table that is slow — so run this once offline and
every subsequent app launch reads a tiny JSON cache instead of scanning.

    python -m studio.warm_cache             # warm the on-disk filter cache
    python -m studio.warm_cache --indexes   # ALSO create filter-column indexes
                                            #   (writes to the DB; speeds the scan)

Point it at the real DB the same way the app does:
    STUDIO_DB_PATH=/path/to/app.db  python -m studio.warm_cache --indexes
"""
from __future__ import annotations

import sys
import time

from studio.data import ensure_filter_indexes, warm_filter_cache

FLOW = "gpr"


def main(argv: list[str]) -> None:
    if "--indexes" in argv:
        print("creating filter-column indexes (one-time; may take a while on a big DB)…")
        t0 = time.time()
        made = ensure_filter_indexes(FLOW)
        print(f"  indexes ensured: {len(made)} in {time.time() - t0:.1f}s")

    print("warming filter cache…")
    t0 = time.time()
    path = warm_filter_cache(FLOW)
    print(f"  done in {time.time() - t0:.1f}s → {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
