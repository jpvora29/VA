"""One pipeline for every data turn (Phase 2, step 3), behind a switch.

With `UNIFIED_PIPELINE=on`, a lookup on the premium, survey or combined route
takes the analyst pipeline as a one-step plan instead of its own subgraph. The
step tries the analytics primitives first and falls back to the solver (which
can write SQL), and the answer passes the same writer and verify gate as an
analytical turn.

Default `off`. The old GPR, survey and combiner subgraphs stay wired until a
golden-set run shows the unified path answers at least as well; only then are
they removed.

GIMMI questions (market / benchmark / region wording on the premium route) stay
on the old rail for now: the GIMMI tables are not yet behind a primitive or the
analyst's solver, so sending them here would silently drop that evidence.
"""

from __future__ import annotations

import os

#: Routes whose turns are answered from data (as opposed to `fallback`).
DATA_ROUTES = frozenset({"premium", "survey", "both"})


def unified_pipeline_enabled() -> bool:
    return os.getenv("UNIFIED_PIPELINE", "off").strip().lower() == "on"


def takes_unified_pipeline(route: str, *, needs_gimmi: bool) -> bool:
    """Whether this turn goes to the analyst pipeline whatever its depth."""
    return unified_pipeline_enabled() and route in DATA_ROUTES and not needs_gimmi
