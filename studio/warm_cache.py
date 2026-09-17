"""Pre-build the Studio filter cube so app launch is instant.

The first time the Studio page loads for a given DB it must scan the fact table
once to build the filter cube (the distinct combinations of the filter columns,
with premium rolled up to them). On an 80M-row warehouse that scan is minutes —
so run this once offline, and every subsequent app launch memory-maps the built
cube instead of scanning for it.

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

    print("building the filter cube (one-time for this database)…")
    t0 = time.time()
    report = warm_filter_cache(FLOW)
    print(f"  done in {time.time() - t0:.1f}s")
    for line in report:
        print(f"  {line}")


if __name__ == "__main__":
    main(sys.argv[1:])
