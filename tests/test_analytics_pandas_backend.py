"""The pandas executor: parity with SQL, and the degradation SQL cannot do.

Why this exists: an uploaded dataset carries only the columns the user's spreadsheet
had. Every primitive cutting by one they did not upload (industry, cover line, billing
date) failed with "no such column", was swallowed by a caller's ``_safe``, and the deck
came out a shell. The pandas executor treats an absent column as an absent CUT and
keeps the rest of the deck.

Three layers:
  * parity — the SAME data through both executors must produce the SAME facts, fact
    for fact, in the same order. This is the contract: two executors, one library;
  * degradation — the behaviours that only the pandas side can have, and the one it
    must NOT have (inventing a zero where there is no data to speak of);
  * end to end — an uploaded dataset drives the real deck plan.

Deterministic: an in-memory frame and its SQLite twin, no LLM.
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine

from core.analytics import library as L
from core.analytics.frames import FrameSource, as_frame_source, frame_source
from core.analytics.types import PrimitiveArgs


# ── the fixture: one book, two executors ─────────────────────────────────────


def _book() -> pd.DataFrame:
    """A small premium book with two years, two countries, three carriers, two lines."""
    rows = []
    money = {("Zurich", "Cyber"): 100, ("Zurich", "Marine"): 60,
             ("AIG", "Cyber"): 80, ("AIG", "Marine"): 90,
             ("Chubb", "Cyber"): 40, ("Chubb", "Marine"): 20}
    for year, factor in ((2024, 1.0), (2025, 1.2)):
        for month in (3, 9):
            for country, weight in (("Singapore", 1.0), ("Japan", 0.5)):
                for (carrier, line), base in money.items():
                    rows.append({
                        "Carrier_Group": carrier, "Country": country, "Product_Line": line,
                        "Year": year, "Billing_Date": f"{year}-{month:02d}-15",
                        "SIC_Major_Class": "Manufacturing" if line == "Marine" else "Technology",
                        "Premium": round(base * factor * weight * 1000, 2),
                    })
    return pd.DataFrame(rows)


def _peers() -> pd.DataFrame:
    return pd.DataFrame([
        {"Carrier_Group": "Zurich", "Overall_Peer_Group": "AIG", "Country": "Singapore"},
        {"Carrier_Group": "Zurich", "Overall_Peer_Group": "Chubb", "Country": "Singapore"},
    ])


@pytest.fixture(scope="module")
def executors(tmp_path_factory):
    """``(sql engine, frame source)`` over identical data."""
    book, peers = _book(), _peers()
    path = tmp_path_factory.mktemp("pandas_backend") / "book.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    book.to_sql("GPR", engine, index=False, if_exists="replace")
    peers.to_sql("Peers", engine, index=False, if_exists="replace")
    return engine, frame_source({"GPR": book, "Peers": peers}, label="test")


def _keys(facts):
    """Facts reduced to what the contract promises: name, cut and value, in order."""
    return [(f.name, tuple(sorted((str(k), str(v)) for k, v in f.dims.items())),
             round(float(f.value), 6)) for f in facts]


ZURICH = {"Carrier_Group": "Zurich", "Country": ("Singapore",), "Year": 2025}
MARKET = {"Country": ("Singapore",), "Year": 2025}

# (label, primitive, args, tuning kwargs) — every leaf primitive plus the composites
# that ride on them.
CASES = [
    ("total", L.compute_breakdown, PrimitiveArgs(flow="gpr", metric="premium", filters=ZURICH), {}),
    ("by product", L.compute_breakdown,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",), filters=ZURICH), {}),
    ("by carrier", L.compute_breakdown,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("Carrier_Group",), filters=MARKET), {}),
    ("two cuts", L.compute_breakdown,
     PrimitiveArgs(flow="gpr", metric="premium",
                   group_by=("Product_Line", "Carrier_Group"), filters=MARKET), {}),
    ("no rows", L.compute_breakdown,
     PrimitiveArgs(flow="gpr", metric="premium", filters={"Carrier_Group": "Nobody"}), {}),
    ("rank", L.compute_rank, PrimitiveArgs(flow="gpr", metric="premium", filters=MARKET), {}),
    ("rank by product", L.compute_rank,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",), filters=MARKET), {}),
    ("yoy", L.compute_yoy,
     PrimitiveArgs(flow="gpr", metric="premium", filters={"Carrier_Group": "Zurich"}), {}),
    ("yoy by product", L.compute_yoy,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                   filters={"Carrier_Group": "Zurich"}), {}),
    ("sow", L.compute_share_of_wallet,
     PrimitiveArgs(flow="gpr", metric="premium", filters=ZURICH, subject="Zurich"), {}),
    ("sow by product", L.compute_share_of_wallet,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                   filters=ZURICH, subject="Zurich"), {}),
    ("share of portfolio", L.compute_share_of_portfolio,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",), filters=ZURICH), {}),
    ("market presence", L.compute_market_presence,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",), filters=ZURICH), {}),
    ("peer average total", L.compute_peer_average_total,
     PrimitiveArgs(flow="gpr", metric="premium", filters=ZURICH, subject="Zurich"), {}),
    # Grouped: both executors must sum each peer's total WITHIN the cut and then
    # average across peers, giving one fact per product line rather than one
    # portfolio-wide number repeated against every line.
    ("peer average total by product", L.compute_peer_average_total,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                   filters=ZURICH, subject="Zurich"), {}),
    ("peer average total pinned", L.compute_peer_average_total,
     PrimitiveArgs(flow="gpr", metric="premium", filters=ZURICH, subject="Zurich",
                   peers=("AIG",)), {}),
    ("peer average per row", L.compute_peer_average,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                   filters=ZURICH, subject="Zurich"), {}),
    ("period series", L.compute_period_series,
     PrimitiveArgs(flow="gpr", metric="premium", filters={"Carrier_Group": "Zurich"}), {}),
    ("period series quarterly", L.compute_period_series,
     PrimitiveArgs(flow="gpr", metric="premium", filters={"Carrier_Group": "Zurich"}),
     {"grain": "quarter"}),
    ("period change", L.compute_period_change,
     PrimitiveArgs(flow="gpr", metric="premium", filters={"Carrier_Group": "Zurich"}),
     {"grain": "quarter"}),
    ("whitespace", L.find_whitespace,
     PrimitiveArgs(flow="gpr", metric="premium", group_by=("SIC_Major_Class",),
                   filters={"Carrier_Group": "Zurich", "Year": 2025}), {}),
]


@pytest.mark.parametrize("label,fn,args,kwargs", CASES, ids=[c[0] for c in CASES])
def test_pandas_matches_sql_fact_for_fact(executors, label, fn, args, kwargs):
    engine, source = executors
    assert _keys(fn(args, engine=source, **kwargs)) == _keys(fn(args, engine=engine, **kwargs))


def test_the_parity_suite_actually_computes_something(executors):
    """Guard the guard: a suite of empty results would pass every comparison above."""
    engine, _source = executors
    produced = sum(len(fn(args, engine=engine, **kw)) for _l, fn, args, kw in CASES)
    assert produced > 40


def test_a_composite_follows_the_same_executor(executors):
    """``find_whitespace`` has no executor of its own — it threads the source down."""
    _engine, source = executors
    facts = L.find_whitespace(
        PrimitiveArgs(flow="gpr", metric="premium", group_by=("SIC_Major_Class",),
                      filters={"Carrier_Group": "Chubb", "Year": 2025}),
        engine=source, near_zero=1e9, material=0.0,
    )
    assert facts and all(f.name == "whitespace" for f in facts)


# ── the dispatch seam ────────────────────────────────────────────────────────


def test_a_real_engine_still_takes_the_sql_path(executors):
    engine, source = executors
    assert as_frame_source(engine) is None
    assert as_frame_source(source) is source
    assert as_frame_source(None) is None


def test_every_routed_primitive_keeps_its_sql_body():
    """The decorator must WRAP the SQL, never replace it — the governed DB still runs it."""
    from core.analytics.pandas_library import PANDAS_LIBRARY

    for name in PANDAS_LIBRARY:
        primitive = L.LIBRARY[name]
        assert hasattr(primitive, "on_sql"), name
        assert primitive.__doc__, name          # @wraps kept the identity


def test_the_library_routes_every_primitive_it_can():
    """Any leaf primitive without a pandas twin would silently fail on uploaded data."""
    from core.analytics.pandas_library import PANDAS_LIBRARY

    # The composites are Python over other primitives, so they need no twin.
    composites = {"compute_ttm", "compute_attribute_breakdown",
                  "find_whitespace", "find_service_gaps"}
    assert set(L.LIBRARY) - composites == set(PANDAS_LIBRARY)


# ── degradation: what a thin upload does ─────────────────────────────────────


@pytest.fixture()
def thin() -> FrameSource:
    """The required trio and nothing else — the shape of a real first upload."""
    book = _book()[["Carrier_Group", "Year", "Premium"]]
    return frame_source({"GPR": book}, label="thin")


def test_a_cut_by_a_column_the_upload_lacks_yields_no_facts(thin):
    """Not an exception, and not a fabricated row: the section is simply absent."""
    facts = L.compute_breakdown(
        PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                      filters={"Carrier_Group": "Zurich"}),
        engine=thin,
    )
    assert facts == []


def test_the_numbers_that_CAN_be_computed_still_are(thin):
    """The whole point — a thin upload keeps its totals, rank and share of wallet."""
    args = PrimitiveArgs(flow="gpr", metric="premium",
                         filters={"Carrier_Group": "Zurich", "Year": 2025}, subject="Zurich")
    assert L.compute_breakdown(args, engine=thin)[0].value > 0
    assert L.compute_rank(
        PrimitiveArgs(flow="gpr", metric="premium", filters={"Year": 2025}), engine=thin)
    assert L.compute_share_of_wallet(args, engine=thin)[0].value > 0


def test_a_filter_on_an_absent_column_matches_nothing(thin):
    """An AND constraint that cannot be evaluated cannot be satisfied — widening the
    scope instead would answer a different question from the one that was asked."""
    facts = L.compute_breakdown(
        PrimitiveArgs(flow="gpr", metric="premium",
                      filters={"Carrier_Group": "Zurich", "Country": "Singapore"}),
        engine=thin,
    )
    assert [f.value for f in facts] == [0.0]


def test_a_table_the_source_does_not_have_yields_no_fact_at_all():
    """A premium upload has no survey book. The tile must keep the template's own
    placeholder — a 0.0 here would put an invented score on a client-facing slide."""
    source = frame_source({"GPR": _book()}, label="premium-only")
    facts = L.compute_breakdown(
        PrimitiveArgs(flow="gpr", metric="premium", filters={}), engine=source)
    assert facts and facts[0].value > 0          # the book it DOES have still answers

    survey = L.compute_breakdown(
        PrimitiveArgs(flow="survey", metric="score", filters={"Carrier": "Zurich"}),
        engine=source)
    assert survey == []


def test_an_empty_source_answers_nothing_rather_than_zero():
    assert L.compute_breakdown(
        PrimitiveArgs(flow="gpr", metric="premium", filters={}),
        engine=FrameSource()) == []


def test_no_rows_in_scope_is_a_real_zero(executors):
    """Distinct from "cannot compute": the data exists, the slice is genuinely empty."""
    _engine, source = executors
    facts = L.compute_breakdown(
        PrimitiveArgs(flow="gpr", metric="premium", filters={"Year": 1999}), engine=source)
    assert [f.value for f in facts] == [0.0]


def test_a_hallucinated_column_is_still_rejected(executors):
    """Degradation is for columns the upload lacks, never for ones the schema lacks."""
    _engine, source = executors
    with pytest.raises(ValueError, match="unknown column"):
        L.compute_breakdown(
            PrimitiveArgs(flow="gpr", metric="premium", group_by=("Nonsense",), filters={}),
            engine=source)


def test_peers_resolve_from_the_frame_not_a_join(executors):
    _engine, source = executors
    facts = L.compute_peer_average_total(
        PrimitiveArgs(flow="gpr", metric="premium", filters=ZURICH, subject="Zurich"),
        engine=source)
    assert facts and facts[0].dims["peers"] == 2      # AIG + Chubb, never named
    assert "Overall_Peer_Group" not in str(facts[0].dims)
