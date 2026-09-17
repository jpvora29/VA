"""Pre-build the Studio filter cube so app launch is instant.

The first time the Studio page loads for a given DB it must scan the fact table
once to build the filter cube (the distinct combinations of the filter columns,
with premium rolled up to them). On an 80M-row warehouse that scan is minutes —
so run this once offline, and every subsequent app launch memory-maps the built
cube instead of scanning for it.

    python -m studio.warm_cache             # warm the on-disk filter cache
    python -m studio.warm_cache --indexes   # ALSO create filter-column indexes
                                            #   (writes to the DB; speeds the scan)

Reads the same ``.env`` the app does, so pointing the app at a database is enough. To
override for one run:
    STUDIO_DB_PATH=/path/to/app.db  python -m studio.warm_cache
"""
from __future__ import annotations

import os
import sys
import threading
import time

from logger import get_logger
from studio.data import ensure_filter_indexes, warm_filter_cache

logger = get_logger(__name__)

FLOW = "gpr"


def main(argv: list[str]) -> None:
    # The app reads ``.env`` before it imports anything from studio (``app.py``), so this CLI
    # has to as well: a warm-up that resolved a different STUDIO_DB_PATH, STUDIO_CACHE_DIR or
    # STUDIO_CUBE_KEY than the app would build a cube the app then ignores.
    from dotenv import load_dotenv

    load_dotenv()
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


def warm_in_background(flow: str = FLOW):
    """Start building the cube now, in a daemon thread. Returns the thread (or None).

    Called at app startup so that STARTUP is what pays for a cold cube, not the first filter
    change. The build is minutes on a large warehouse, and inside a callback those minutes are
    a spinner on the Setup form with no explanation; the store's build lock means a callback
    that arrives meanwhile waits for THIS build rather than starting a second one.

    ``STUDIO_WARM_CUBE=off`` skips it — for a launch that must not touch the warehouse.
    """
    if os.getenv("STUDIO_WARM_CUBE", "on").strip().lower() == "off":
        logger.info("studio: STUDIO_WARM_CUBE=off — not pre-building the filter cube")
        return None

    def build() -> None:
        started = time.time()
        try:
            for line in warm_filter_cache(flow):
                logger.info("studio: cube warm-up — %s", line)
            logger.info("studio: filter cube ready in %.1fs", time.time() - started)
        except Exception as exc:  # noqa: BLE001 — a failed warm-up must never stop the app
            logger.warning("studio: cube warm-up failed (%s) — the Setup page will build it "
                           "on demand", exc)

    thread = threading.Thread(target=build, name="studio-cube-warm", daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    main(sys.argv[1:])
