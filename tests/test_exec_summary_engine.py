"""The executive summary's deterministic core — formulas, peers, gates, selection.

Pure and synthetic: a hand-built premium cube whose figures are the design document's own
worked examples (Sections 14, 15 and 21), so every assertion is checkable by hand. No DB,
no LLM.
"""
from __future__ import annotations

import pandas as pd
import pytest

from studio.exec_summary import classify as K
from studio.exec_summary.config import load_config
from studio.exec_summary.metrics import (
    GROWTH_NA,
    GROWTH_NEW,
    GROWTH_UNAVAILABLE,
    Scope,
    dense_rank,
    growth,
    share,
    slice_metrics,
)
from studio.exec_summary.peers import PeerSet, resolve_peer_set
from studio.exec_summary.selection import select_industries
from studio.exec_summary.context import AnalysisContext
from studio.exec_summary.survey import ScoreLine
from studio.exec_summary.whitespace import (
    CONDITIONAL,
    EXCLUDED,
    NEW_BOOK,
    VIEW_INDUSTRY,
    qualify,
    ranked,
)

M = 1_000_000.0
CUR, PRIOR = 2026, 2025
CFG = load_config()


def _row(country, product, industry, carrier, year, premium, segment="Corporate"):
    return {"country": country, "product": product, "industry": industry,
            "segment": segment, "carrier": carrier, "year": year, "premium": premium}


def _cube(rows) -> pd.DataFrame:
    return pd.DataFrame(rows)


@pytest.fixture
def scenario_cube() -> pd.DataFrame:
    """Singapore, FY2026 vs FY2025 — the design's Scenario 1 (Property) and 2 (Casualty)."""
    rows = [
        # Property: carrier 36 -> 40; Marsh 180 -> 200 (the rest split across P1, P2, X).
        _row("SG", "Property", "Manufacturing", "Focal", PRIOR, 35.9 * M),
        _row("SG", "Property", "Manufacturing", "Focal", CUR, 39.9 * M),
        _row("SG", "Property", "Chemicals", "Focal", PRIOR, 0.1 * M),
        _row("SG", "Property", "Chemicals", "Focal", CUR, 0.1 * M),
        _row("SG", "Property", "Chemicals", "P1", PRIOR, 24.9 * M),
        _row("SG", "Property", "Chemicals", "P1", CUR, 29.9 * M),
        _row("SG", "Property", "Manufacturing", "P1", PRIOR, 60.0 * M),
        _row("SG", "Property", "Manufacturing", "P1", CUR, 60.0 * M),
        _row("SG", "Property", "Manufacturing", "P2", PRIOR, 59.1 * M),
        _row("SG", "Property", "Manufacturing", "P2", CUR, 70.1 * M),
        # Casualty: carrier 15 -> 12; Marsh 150 -> 180.
        _row("SG", "Casualty", "Wholesale", "Focal", PRIOR, 15.0 * M),
        _row("SG", "Casualty", "Wholesale", "Focal", CUR, 12.0 * M),
        _row("SG", "Casualty", "Wholesale", "P1", PRIOR, 135.0 * M),
        _row("SG", "Casualty", "Wholesale", "P1", CUR, 168.0 * M),
    ]
    return _cube(rows)


PEERS = {"SG": PeerSet("SG", ("P1", "P2"), "setup_pin")}


# ── formulas (design Section 5) ──────────────────────────────────────────────


def test_growth_names_every_special_case():
    assert growth(110.0, 100.0).pct == pytest.approx(10.0)
    assert growth(5.0, 0.0).status == GROWTH_NEW
    assert growth(0.0, 0.0).status == GROWTH_NA
    assert growth(5.0, None).status == GROWTH_UNAVAILABLE
    assert growth(-5.0, 0.0).status == GROWTH_UNAVAILABLE       # nonpositive base
    assert growth(5.0, -2.0).status == GROWTH_UNAVAILABLE


def test_share_is_suppressed_on_a_nonpositive_denominator():
    assert share(40.0, 200.0) == pytest.approx(20.0)
    assert share(1.0, 0.0) is None
    assert share(1.0, -5.0) is None


def test_dense_rank_shares_a_rank_on_ties_and_does_not_rank_a_non_writer():
    per = pd.Series({"A": 10.0, "B": 10.0, "C": 5.0, "D": 0.0})
    assert dense_rank(per, "C") == (2, 3)                       # A and B share #1
    assert dense_rank(per, "D") == (None, 3)


def test_scenario_1_property_position(scenario_cube):
    m = slice_metrics(scenario_cube, Scope("SG", "Property"), "Focal", CUR, PRIOR, PEERS,
                      parent_carrier_cur=100 * M)
    assert m.carrier_cur == pytest.approx(40 * M)
    assert m.marsh_cur == pytest.approx(200 * M)
    assert m.carrier_growth.pct == pytest.approx(11.111, abs=1e-3)
    assert m.sow_cur == pytest.approx(20.0)
    assert m.mix_pct == pytest.approx(40.0)


def test_scenario_1_chemicals_is_a_conditional_whitespace_candidate(scenario_cube):
    m = slice_metrics(scenario_cube, Scope("SG", "Property", industry="Chemicals"), "Focal",
                      CUR, PRIOR, PEERS)
    assert m.sow_cur == pytest.approx(0.3333, abs=1e-3)
    assert m.marsh_growth.pct == pytest.approx(20.0)
    cand = qualify(m, country="SG", product="Property", view=VIEW_INDUSTRY, name="Chemicals",
                   path="expand_strength", gates=CFG.whitespace)
    assert cand.eligibility == CONDITIONAL
    assert all(g.passed for g in cand.gates)
    assert any("not yet validated" in q for q in cand.qualifications)


def test_scenario_2_casualty_needs_attention(scenario_cube):
    m = slice_metrics(scenario_cube, Scope("SG", "Casualty"), "Focal", CUR, PRIOR, PEERS)
    assert m.carrier_growth.pct == pytest.approx(-20.0)
    assert m.marsh_growth.pct == pytest.approx(20.0)
    assert m.sow_cur == pytest.approx(6.6667, abs=1e-3)
    assert m.sow_change_pp == pytest.approx(-3.3333, abs=1e-3)
    c = K.classify(m, CFG.materiality)
    assert K.ATTENTION in c.labels
    assert c.pattern == K.RULE_REL_UNDERPERF
    assert any("40.0 percentage points below the Marsh book" in r for r in c.reasons)


def test_rank_movement_is_positive_for_an_improvement():
    cube = _cube([
        _row("SG", "P", "I", "Focal", PRIOR, 5.0), _row("SG", "P", "I", "X", PRIOR, 10.0),
        _row("SG", "P", "I", "Focal", CUR, 20.0), _row("SG", "P", "I", "X", CUR, 10.0),
    ])
    m = slice_metrics(cube, Scope("SG"), "Focal", CUR, PRIOR, {})
    assert (m.rank_prior, m.rank_cur, m.rank_movement) == (2, 1, 1)


# ── peers (design Sections 3 and 6) ──────────────────────────────────────────


def test_each_country_uses_its_own_peer_set_and_multi_country_sums_their_means():
    cube = _cube([
        _row("SG", "P", "I", "Focal", CUR, 10.0), _row("SG", "P", "I", "A", CUR, 20.0),
        _row("SG", "P", "I", "B", CUR, 40.0),
        _row("HK", "P", "I", "Focal", CUR, 10.0), _row("HK", "P", "I", "A", CUR, 100.0),
        _row("HK", "P", "I", "C", CUR, 6.0),
        *[_row(c, "P", "I", w, PRIOR, 1.0) for c in ("SG", "HK") for w in ("Focal", "A", "B", "C")],
    ])
    peers = {"SG": PeerSet("SG", ("A", "B"), "pin"), "HK": PeerSet("HK", ("C",), "pin")}
    sg = slice_metrics(cube, Scope("SG"), "Focal", CUR, PRIOR, peers)
    hk = slice_metrics(cube, Scope("HK"), "Focal", CUR, PRIOR, peers)
    both = slice_metrics(cube, Scope(), "Focal", CUR, PRIOR, peers)
    assert sg.peer.mean_cur == pytest.approx(30.0)              # mean of A, B in SG
    assert hk.peer.mean_cur == pytest.approx(6.0)               # C only — A is not a HK peer
    assert both.peer.mean_cur == pytest.approx(36.0)            # 30 + 6, never a union
    assert both.peer.counts == {"SG": 2, "HK": 1}


def test_multi_country_share_is_recomputed_from_sums_not_averaged():
    cube = _cube([
        _row("SG", "P", "I", "Focal", CUR, 10.0), _row("SG", "P", "I", "X", CUR, 10.0),
        _row("HK", "P", "I", "Focal", CUR, 10.0), _row("HK", "P", "I", "X", CUR, 90.0),
    ])
    both = slice_metrics(cube, Scope(), "Focal", CUR, PRIOR, {})
    assert both.sow_cur == pytest.approx(100 * 20 / 120)        # not (50% + 10%) / 2


def test_a_pinned_peer_set_wins_and_excludes_the_focal_carrier():
    ctx = AnalysisContext(carrier="Focal", countries=("SG",), current_year=CUR,
                          prior_year=PRIOR, current_label="FY2026", prior_label="FY2025",
                          currency="USD", symbol="$", peer_pins={"SG": ("Focal", "A", "a")})
    peers = resolve_peer_set(ctx, "SG", None, lookup=lambda *a: ["Z"])
    assert peers.members == ("A",) and peers.source == "setup_pin"
    unpinned = resolve_peer_set(ctx, "HK", None, lookup=lambda *a: ["Z", "Focal"])
    assert unpinned.members == ("Z",) and unpinned.source == "peers_table"


def test_a_missing_peer_group_is_an_unavailable_reference_not_zero(scenario_cube):
    m = slice_metrics(scenario_cube, Scope("SG", "Property"), "Focal", CUR, PRIOR, {})
    assert not m.peer.available and m.peer.mean_cur is None and m.growth_gap_peer_pp is None


# ── whitespace gates and ranking (design Sections 11 and 12) ─────────────────


def _cand(cube, industry, **kw):
    m = slice_metrics(cube, Scope("SG", "P", industry=industry), "Focal", CUR, PRIOR, {})
    return qualify(m, country="SG", product="P", view=VIEW_INDUSTRY, name=industry,
                   path="develop", gates=CFG.whitespace)


def test_gates_exclude_unmapped_small_and_participating_slices_and_route_new_books():
    rows = []
    for name, marsh_prior, marsh_cur, focal in (
            ("Big", 20 * M, 30 * M, 0.0), ("Small", 1 * M, 2 * M, 0.0),
            ("Unmapped", 20 * M, 30 * M, 0.0), ("Owned", 20 * M, 30 * M, 5 * M),
            ("Fresh", 0.0, 30 * M, 0.0)):
        rows += [_row("SG", "P", name, "X", PRIOR, marsh_prior), _row("SG", "P", name, "X", CUR, marsh_cur)]
        if focal:
            rows.append(_row("SG", "P", name, "Focal", CUR, focal))
    cube = _cube(rows)
    assert _cand(cube, "Big").eligibility == CONDITIONAL          # confirmed zero qualifies
    assert _cand(cube, "Small").eligibility == EXCLUDED
    assert _cand(cube, "Unmapped").eligibility == EXCLUDED
    assert _cand(cube, "Owned").eligibility == EXCLUDED
    assert _cand(cube, "Fresh").eligibility == NEW_BOOK


def test_ranking_is_marsh_premium_then_growth_then_low_share():
    rows = []
    for name, prior, cur in (("A", 20 * M, 25 * M), ("B", 30 * M, 40 * M), ("C", 20 * M, 25 * M)):
        rows += [_row("SG", "P", name, "X", PRIOR, prior), _row("SG", "P", name, "X", CUR, cur)]
    cube = _cube(rows)
    order = [c.name for c in ranked([_cand(cube, n) for n in ("A", "C", "B")])]
    assert order == ["B", "A", "C"]                                # ties broken by slice id


# ── bounded selection (design Section 19) ────────────────────────────────────


def test_selection_keeps_at_most_six_unique_industries_with_both_labels():
    rows = []
    for i in range(10):
        rows += [_row("SG", "P", f"I{i}", "X", PRIOR, 20 * M), _row("SG", "P", f"I{i}", "X", CUR, 30 * M),
                 _row("SG", "P", f"I{i}", "Focal", CUR, (10 - i) * M)]
    cube = _cube(rows)
    metrics = [slice_metrics(cube, Scope("SG", "P", industry=f"I{i}"), "Focal", CUR, PRIOR, {})
               for i in range(10)]
    sel = select_industries(metrics, top_n=3, bottom_n=3, material_marsh=10 * M,
                            rule_version="v")
    assert sel.top == ("I0", "I1", "I2")
    assert sel.bottom == ("I9", "I8", "I7")
    assert len(sel.rows) == 6 and sel.omitted == 4
    small = select_industries(metrics[:2], top_n=3, bottom_n=3, material_marsh=10 * M,
                              rule_version="v")
    assert len(small.rows) == 2                                    # no padding, no duplicates
    assert set(small.labels["I0"]) == {"top", "bottom"}


# ── classification read against the survey (design Section 9) ────────────────


def test_commercial_weakness_with_a_weak_survey_is_flagged_both_ways(scenario_cube):
    m = slice_metrics(scenario_cube, Scope("SG", "Casualty"), "Focal", CUR, PRIOR, PEERS)
    weak = ScoreLine("Overall", score=3.2, prior=3.8, peer_mean=3.7)
    strong = ScoreLine("Overall", score=4.2, prior=4.1, peer_mean=3.7)
    assert K.classify(m, CFG.materiality, survey_line=weak).survey_rule == K.RULE_SURVEY_WEAK_TOO
    assert K.classify(m, CFG.materiality, survey_line=strong).survey_rule == K.RULE_SURVEY_STRONG


def test_survey_gap_moves_with_the_reference():
    line = ScoreLine("Overall", score=3.2, prior=3.8, peer_mean=3.7, peer_prior=3.6)
    assert line.movement == pytest.approx(-0.6)
    assert line.peer_gap == pytest.approx(-0.5)
    assert line.prior_peer_gap == pytest.approx(0.2)
    assert line.gap_change == pytest.approx(-0.7)
