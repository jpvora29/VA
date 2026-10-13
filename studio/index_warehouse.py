"""Build the indexes on a warehouse file before it is published.

The app opens the warehouse read-only (``core.readonly_sqlite``), so it can no longer
index the file itself. Run this once per data release, on a copy OUTSIDE OneDrive,
with no app open on it, then publish the indexed file:

    python -m studio.index_warehouse C:\\data\\warehouse.db
    python -m studio.index_warehouse C:\\data\\warehouse.db --filter-indexes

The analytics indexes are always built. ``--filter-indexes`` adds the opt-in
single-column filter indexes (see ``studio.indexes.filter_index_plan``) — worth it only
on a warehouse too wide for the filter cube, and minutes each on a huge table.

Exits 1 when an index is still missing afterwards, so a script can stop before
publishing a file that would build slowly for everyone.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Sequence

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from core.registry import get_flow_registry
from studio.indexes import (
    ensure_filter_indexes,
    ensure_indexes,
    missing_filter_indexes,
    missing_index_names,
)

FLOWS = ("gpr", "survey")
FILTER_FLOWS = ("gpr",)
FILTER_FLAG = "--filter-indexes"


def open_writable(path: Path) -> Engine:
    """The one writable engine on a warehouse — this command's alone."""
    if not path.is_file():
        raise SystemExit(f"No database at {path}")
    return create_engine(f"sqlite:///{path}")


def present_flows(engine: Engine, flows: Sequence[str]) -> List[str]:
    """The flows whose table this file actually holds."""
    tables = set(inspect(engine).get_table_names())
    registry = get_flow_registry()
    return [flow for flow in flows
            if (spec := registry.get(flow)) is not None and spec.primary_table in tables]


def build_indexes(engine: Engine, flows: Sequence[str]) -> List[str]:
    """Create every missing analytics index, over the flows whose table the file holds."""
    return [name for flow in present_flows(engine, flows) for name in ensure_indexes(flow, engine)]


def build_filter_indexes(engine: Engine, flows: Sequence[str]) -> List[str]:
    """Create every missing opt-in filter-column index."""
    return [name for flow in present_flows(engine, flows)
            for name in ensure_filter_indexes(flow, engine)]


def still_missing(engine: Engine, with_filters: bool) -> List[str]:
    missing = missing_index_names(FLOWS, engine)
    if with_filters:
        missing += [spec.name for flow in present_flows(engine, FILTER_FLOWS)
                    for spec in missing_filter_indexes(flow, engine)]
    return missing


def main(argv: Sequence[str]) -> int:
    with_filters = FILTER_FLAG in argv
    paths = [arg for arg in argv if arg != FILTER_FLAG]
    if len(paths) != 1:
        print(__doc__)
        return 2
    path = Path(paths[0])
    engine = open_writable(path)
    print(f"Indexing {path} (large files take minutes per index)...")
    made = build_indexes(engine, FLOWS)
    if with_filters:
        made += build_filter_indexes(engine, FILTER_FLOWS)
    missing = still_missing(engine, with_filters)
    engine.dispose()
    print(f"Created {len(made)} index(es): {', '.join(made) or 'none needed'}")
    if missing:
        print(f"STILL MISSING {len(missing)}: {', '.join(missing)}")
        return 1
    print("All indexes present. Safe to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
