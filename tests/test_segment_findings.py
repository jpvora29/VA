"""Industry / client-segment decomposition — the classifiers, the baselines, the altitude.

The pure tests use the seed book's REAL figures as literals (Zurich / Singapore / Financial
Lines / 2025), so a threshold is argued against data somebody could be shown rather than
against a hypothetical. The integration tests run the real primitives over the seed DB.

Deterministic: seed DB, no LLM.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from studio import segments as S
from studio.data import get_engine

GPR = "gpr"
ENG = get_engine()
CFG = S.Thresholds()

# The scope every number in this file comes from.
_LINE = {"Country": "Singapore", "Product_Line": "Financial Lines"}
_YEAR = 2025

# The line's own benchmarks, measured: 12.9% across the industries it writes, 10.7% across
# the whole scope. The 2.2 points between them are the three industries it does not write.
_PLACED_SOW = 12.9
_SCOPE_SOW = 10.7


def _row(**kw) -> S.SegmentFinding:
    """A finding with the line's baselines already set — only the row's own figures vary."""
    base = dict(dim="SIC_Major_Class", name="Test", placed_sow=_PLACED_SOW)
    base.update(kw)
    return S.SegmentFinding(**base)


def _classified(row: S.SegmentFinding) -> S.SegmentFinding:
    """The same row with the class its figures earn."""
    return replace(row, placement=S.classify(row, CFG))


# ── the five classes, on the figures that produced them ─────────────────────


@pytest.mark.parametrize(
    "name, carrier, market, sow, peer_sow, sow_delta, expected",
    [
        # Marsh places $30.7M of it and the book writes none — the whole pool is at stake.
        ("Renewable Energy", 0.0, 30_704_325, 0.0, 12.3, None, S.Placement.ABSENT),
        # Written at 9.6% against the book's own 12.9% — below its own standard.
        ("Technology & Telecom", 3_879_208, 40_383_528, 9.6, 10.5, -0.2, S.Placement.THIN),
        # Written at 17.0% — the proof the class can be placed above the house average.
        ("Healthcare & Life Sciences", 5_895_936, 34_635_502, 17.0, 10.1, 0.4,
         S.Placement.STRONG),
        # Share collapsed 7.8 points in a year: the live event, whatever the level.
        ("Commercial", 3_967_107, 146_892_852, 2.7, 13.7, -7.78, S.Placement.LOSING),
        # Sits within a point of its own average and the benchmark — nothing to say.
        ("Manufacturing", 7_911_092, 63_760_935, 12.4, 10.7, 0.1, S.Placement.TRACKING),
    ],
)
def test_each_class_falls_out_of_the_seed_books_own_figures(
    name, carrier, market, sow, peer_sow, sow_delta, expected
):
    row = _row(name=name, carrier=carrier, market=market, sow=sow,
               peer_sow=peer_sow, sow_delta=sow_delta, carriers=12)
    assert S.classify(row, CFG) is expected


def test_absence_outranks_every_other_reading():
    """A book at zero cannot be thin, behind or losing — ABSENT is tested first."""
    row = _row(name="Pharmaceuticals", carrier=0.0, market=22_688_965, sow=0.0,
               peer_sow=11.9, sow_delta=-3.0, carriers=11)
    assert all(test(row, CFG) for _, test in S._TESTS[:1])
    assert S.is_losing(row, CFG)          # it would also pass the later tests...
    assert S.classify(row, CFG) is S.Placement.ABSENT   # ...but absence is the reading


def test_a_thin_row_is_measured_against_the_placed_average_not_the_scope_average():
    """The distinction the whole module turns on.

    Technology & Telecom is 3.3 points below the 12.9% the book achieves where it writes,
    and only 1.1 below the 10.7% it averages across a scope that includes what it does not
    write. Against the scope average it would not clear the 2.0-point bar at all, and the
    line's one genuine under-penetration would go unsaid.
    """
    thin = _row(name="Technology & Telecom", carrier=3_879_208, market=40_383_528, sow=9.6,
                peer_sow=10.5, carriers=12)
    assert S.is_thin(thin, CFG)

    against_scope = _row(name="Technology & Telecom", carrier=3_879_208, market=40_383_528,
                         sow=9.6, peer_sow=10.5, carriers=12, placed_sow=_SCOPE_SOW)
    assert not S.is_thin(against_scope, CFG)


# ── the confidentiality floor ───────────────────────────────────────────────


def test_a_thin_peer_set_never_produces_a_peer_comparison():
    """With two carriers in a segment, a "top-5 average" IS one peer's number.

    ``peer.aggregate_only`` forbids the deck from disclosing that, so BEHIND needs a
    minimum field. This is a confidentiality rule, not a statistical one.
    """
    row = _row(name="Aviation & Aerospace", carrier=1_000_000, market=16_106_083, sow=6.2,
               peer_sow=12.9, carriers=2)
    assert not S.is_behind(row, CFG)
    assert S.classify(row, CFG) is not S.Placement.BEHIND

    assert S.is_behind(_row(name="x", carrier=1_000_000, market=16_106_083, sow=6.2,
                            peer_sow=12.9, carriers=3), CFG)


def test_an_immaterial_segment_is_never_worth_a_sentence():
    """Below the materiality floor nothing classifies — a $2M pool is not a finding."""
    for kw in (dict(carrier=0.0, sow=0.0),                       # would be ABSENT
               dict(carrier=100_000, sow=5.0, sow_delta=-4.0)):  # would be LOSING/THIN
        row = _row(name="Education", market=2_000_000, peer_sow=12.0, carriers=12, **kw)
        assert S.classify(row, CFG) is S.Placement.TRACKING


# ── stake: the one key three kinds of opportunity rank on ───────────────────


def test_stake_ranks_absence_shortfall_and_decline_on_one_comparable_number():
    """Three different kinds of opportunity, ranked against each other by premium.

    Without one comparable key the Growth column can only list opportunities by type,
    which is how "closing the 0.1pp gap would add $349K" ended up above $69M of absence.
    """
    absent = _classified(_row(name="Renewable Energy", carrier=0.0, market=30_704_325,
                              sow=0.0, peer_sow=12.3, carriers=11))
    thin = _classified(_row(name="Technology & Telecom", carrier=3_879_208,
                            market=40_383_528, sow=9.6, peer_sow=10.5, carriers=12))

    found = S.SegmentFindings(dim="SIC_Major_Class", rows=(thin, absent))
    ranked = found.of(*S.OPPORTUNITY_KINDS)

    assert [r.name for r in ranked] == ["Renewable Energy", "Technology & Telecom"]
    # absence stakes the whole pool; a shortfall stakes only the premium to the benchmark
    assert ranked[0].stake == pytest.approx(30_704_325)
    assert ranked[1].stake == pytest.approx(40_383_528 * (_PLACED_SOW - 9.6) / 100)


# ── rules plumbing ──────────────────────────────────────────────────────────


def test_thresholds_come_from_the_rules_file():
    cfg = S.thresholds()
    assert cfg.min_market == 5_000_000.0        # materiality.min_premium_for_industry_commentary
    assert cfg.material_market_gwp == 5_000_000.0   # whitespace.material_market_gwp
    assert cfg.carrier_ceiling == 0.0               # whitespace.carrier_ceiling
    assert cfg.min_carriers == 3


def test_the_configured_dimensions_are_industry_and_client_segment():
    assert S.configured_dims() == ("SIC_Major_Class", "Client_Segment")


def test_an_empty_dims_list_falls_back_rather_than_silencing_every_finding(monkeypatch):
    """An empty allowlist would turn segment commentary off with no error anywhere."""
    from studio.rules import engine as E

    assert E._strs({"dims": []}, "dims", ("SIC_Major_Class",)) == ("SIC_Major_Class",)
    assert E._strs({"dims": "nonsense"}, "dims", ("SIC_Major_Class",)) == ("SIC_Major_Class",)
    assert E._strs({"dims": ["A", " B "]}, "dims", ()) == ("A", "B")


# ── integration: the real primitives over the seed DB ───────────────────────


@pytest.fixture(scope="module")
def line():
    S.reset_cache()
    return S.find_segments(flow=GPR, filters=_LINE, engine=ENG, subject="Zurich",
                           dim="SIC_Major_Class", year=_YEAR)


def test_the_line_reports_both_baselines(line):
    assert line.placed_sow == pytest.approx(_PLACED_SOW, abs=0.05)
    assert line.scope_sow == pytest.approx(_SCOPE_SOW, abs=0.05)
    assert line.placed_sow > line.scope_sow   # the gap between them IS the absence


def test_the_lines_real_findings_are_found(line):
    absent = {r.name for r in line.of(S.Placement.ABSENT)}
    assert absent == {"Renewable Energy", "Pharmaceuticals", "Aviation & Aerospace"}
    assert line.absent_total == pytest.approx(69_499_373, rel=0.01)

    assert line.best(S.Placement.THIN).name == "Technology & Telecom"
    assert line.proof().name == "Healthcare & Life Sciences"


def test_findings_are_ranked_by_premium_at_stake(line):
    stakes = [r.stake for r in line.of(*S.OPPORTUNITY_KINDS)]
    assert stakes == sorted(stakes, reverse=True)


def test_client_segment_decomposes_the_same_scope(line):
    found = S.find_all(flow=GPR, filters=_LINE, engine=ENG, subject="Zurich", year=_YEAR)
    assert set(found) == {"SIC_Major_Class", "Client_Segment"}
    seg = found["Client_Segment"]
    assert seg.named("Corporate").placement is S.Placement.STRONG      # 20.9% of wallet
    assert seg.named("Commercial").placement is S.Placement.LOSING     # 2.7%, down 7.8pp


def test_one_scope_costs_two_queries_per_dimension(monkeypatch):
    """Market, the carrier's own premium, the peer average and the carrier count all fall
    out of ONE grouped breakdown, so a dimension costs this year and last — not one query
    per figure. This runs per product per country, so the budget is the design."""
    calls = {"n": 0}
    real = S.compute_breakdown

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(S, "compute_breakdown", counting)
    S.reset_cache()

    S.find_all(flow=GPR, filters=_LINE, engine=ENG, subject="Zurich", year=_YEAR)
    assert calls["n"] == 4      # two dimensions x (this year, prior year)

    calls["n"] = 0
    S.find_all(flow=GPR, filters=_LINE, engine=ENG, subject="Zurich", year=_YEAR)
    assert calls["n"] == 0      # the same scope again costs nothing


def test_an_empty_scope_yields_no_findings_rather_than_raising():
    found = S.find_segments(flow=GPR, filters={"Country": "Nowhere"}, engine=ENG,
                            subject="Zurich", dim="SIC_Major_Class", year=_YEAR)
    assert not found
    assert found.rows == ()


def test_a_failing_decomposition_is_dropped_not_raised(monkeypatch):
    """A decomposition sharpens a column; it never gates one."""
    def boom(*a, **k):
        raise RuntimeError("warehouse down")

    monkeypatch.setattr(S, "compute_breakdown", boom)
    S.reset_cache()
    assert S.find_all(flow=GPR, filters=_LINE, engine=ENG, subject="Zurich", year=_YEAR) == {}
    S.reset_cache()


def test_without_a_year_nothing_can_be_losing():
    """No period, no movement — correct rather than silently wrong."""
    found = S.find_segments(flow=GPR, filters=_LINE, engine=ENG, subject="Zurich",
                            dim="SIC_Major_Class", year=None)
    assert found
    assert not found.of(S.Placement.LOSING)
    assert all(r.sow_delta is None for r in found.rows)


# ── altitude: which scope a finding belongs to ──────────────────────────────


@pytest.fixture(scope="module")
def portfolio():
    return S.find_segments(flow=GPR, filters={}, engine=ENG, subject="Zurich",
                           dim="SIC_Major_Class", year=_YEAR)


def test_the_portfolio_owns_the_absence_every_market_shares(portfolio):
    """The same three industries are unwritten in all four markets, so the finding belongs
    to the deck's overall page. Left to each page it would be printed eleven times."""
    assert portfolio.absent_count == 3
    assert portfolio.absent_total > 1_000_000_000

    for country in ("Singapore", "Japan", "Australia"):
        child = S.find_segments(flow=GPR, filters={"Country": country}, engine=ENG,
                                subject="Zurich", dim="SIC_Major_Class", year=_YEAR)
        assert S.tracks(child, portfolio), f"{country} should track the portfolio"
        assert S.distinguish(child, portfolio) == ()


def test_a_market_that_differs_keeps_its_own_finding(portfolio):
    """Hong Kong is the one market whose shape departs from the book's own pattern."""
    child = S.find_segments(flow=GPR, filters={"Country": "Hong Kong"}, engine=ENG,
                            subject="Zurich", dim="SIC_Major_Class", year=_YEAR)
    assert not S.tracks(child, portfolio)
    assert "Financial Services" in {r.name for r in S.distinguish(child, portfolio)}


def test_a_scope_with_no_parent_keeps_everything(portfolio):
    assert S.distinguish(portfolio, None) == portfolio.rows
    assert not S.tracks(portfolio, None)


def test_pick_cut_returns_nothing_when_a_scope_tracks_its_parent():
    """The honest answer, and the signal to say so on the slide rather than invent a
    difference. With no parent to compare against, the richest cut wins instead."""
    cuts = S.find_all(flow=GPR, filters={"Country": "Singapore"}, engine=ENG,
                      subject="Zurich", year=_YEAR)
    parents = S.find_all(flow=GPR, filters={}, engine=ENG, subject="Zurich", year=_YEAR)

    assert S.pick_cut(cuts, parents) is None
    assert S.pick_cut(cuts) == "SIC_Major_Class"
