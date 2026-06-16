"""Phase 3.5 lens→primitive bridge.

Verifies the real `whitespace.md` lens parses its `primitives:` block, the library
extracts orchestrator-ready calls, and `collect_evidence` runs a lens bundle into a
deterministic `EvidenceSet` over an in-memory DB.

Run:  pytest tests/analytics/test_lens_bridge.py -q
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from core.analysis.evidence import collect_evidence
from core.analysis.planner import LensLibrary, get_lens_library


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text(
            'CREATE TABLE GPR (Carrier_Group TEXT, Country TEXT, Product_Line TEXT, '
            'Year INTEGER, Premium REAL)'
        ))
        conn.execute(
            text('INSERT INTO GPR (Carrier_Group, Country, Product_Line, Year, Premium) '
                 'VALUES (:cg, :co, :pl, :yr, :pr)'),
            [
                {"cg": "Zurich", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 150.0},
                {"cg": "AIG", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 100.0},
                {"cg": "AIG", "co": "Canada", "pl": "Marine", "yr": 2024, "pr": 200.0},
            ],
        )
    return eng


# ── real whitespace.md frontmatter (the concrete first wiring) ─────────────

def test_whitespace_lens_parses_primitives():
    lens = get_lens_library().lens("whitespace")
    assert lens is not None
    calls = [(p.call, list(p.group_by)) for p in lens.primitives]
    assert calls == [
        ("find_whitespace", ["Product_Line", "SIC_Major_Class"]),
        ("compute_market_presence", ["SIC_Major_Class"]),
    ]


def test_primitive_calls_extraction_for_selected_lenses():
    calls = get_lens_library().primitive_calls(["whitespace"])
    assert [c["name"] for c in calls] == ["find_whitespace", "compute_market_presence"]
    assert calls[0]["group_by"] == ["Product_Line", "SIC_Major_Class"]


def test_lens_without_primitives_contributes_nothing():
    # peer_benchmark has no primitives: block yet -> prompt-only, no calls.
    assert get_lens_library().primitive_calls(["peer_benchmark"]) == []


# ── collect_evidence end-to-end (temp lens dir + real DB) ──────────────────

def test_collect_evidence_runs_lens_bundle(tmp_path, engine):
    (tmp_path / "tgap.md").write_text(
        "---\n"
        "name: tgap\n"
        "description: test whitespace lens\n"
        "applies_when: test\n"
        "requires: [GPR]\n"
        "primitives:\n"
        "  - call: find_whitespace\n"
        "    group_by: [Product_Line]\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    library = LensLibrary(lenses_dir=tmp_path)
    evidence = collect_evidence(
        ["tgap"],
        flow="gpr",
        scope={"Country": "Canada", "Carrier_Group": "Zurich", "Year": 2024},
        engine=engine,
        library=library,
    )
    # Zurich has Property but not Marine; the market has Marine -> whitespace.
    gaps = evidence.by_call["find_whitespace"]
    assert [g.dims["Product_Line"] for g in gaps] == ["Marine"]
    assert evidence.skipped == []
