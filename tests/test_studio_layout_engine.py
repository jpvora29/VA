"""Dense layout engine — composer fills every content slide; archetype tuning is safe."""
from __future__ import annotations

from studio.compute import compute_overall
from studio.deck import build_deck
from studio.deck.archetypes import ARCHETYPES
from studio.deck.compose import apply_archetype, compose
from studio.deck.model import ChartBlock, KpiBlock, SlideSpec

_FILTERS = {"carrier": "Zurich", "country": ["Singapore", "Hong Kong"], "year": 2025}


def _deck():
    res = compute_overall(filters=_FILTERS, engine=None)
    return build_deck(res, carrier="Zurich", country="Singapore", year=2025, report="qbr",
                      cuts=("country_breakdown", "country_swot", "rank_similar", "peer_average"))


def test_every_content_slide_is_full():
    """No content slide composes to a half-empty frame: each has a stat band AND a visual."""
    deck = _deck()
    thin = []
    for s in deck.slides:
        if s.layout in ("insight", "decision"):
            p = compose(s)
            if not (p.stat_band and p.primary is not None):
                thin.append(s.eyebrow)
    assert thin == []


def test_compose_classifies_kpis_and_visuals():
    s = SlideSpec(
        layout="insight", title="t", eyebrow="E",
        blocks=(KpiBlock([{"label": "GWP", "value": "USD 1M"}]),
                ChartBlock("bar", ["a"], [1], "p"),
                ChartBlock("line", ["a", "b"], [1, 2], "s")),
    )
    p = compose(s)
    assert p.archetype == "stat_dual"
    assert p.stat_band and p.primary.kind == "chart" and p.secondary is not None
    assert p.stat_from_evidence is False


def test_stat_band_synthesised_from_evidence_when_no_kpis():
    s = SlideSpec(layout="insight", title="t", evidence=({"label": "Rank", "value": "#5"},),
                  blocks=(ChartBlock("bar", ["a"], [1]),))
    p = compose(s)
    assert p.stat_from_evidence is True
    assert any(it["value"] == "#5" for it in p.stat_band)


def test_apply_archetype_ignores_impossible_hint():
    s = SlideSpec(layout="insight", title="t", evidence=({"label": "Rank", "value": "#5"},),
                  blocks=(ChartBlock("bar", ["a"], [1]),))
    p = compose(s)  # single visual → no secondary
    # asking for a dual archetype must NOT take effect (slide has no secondary)
    forced = apply_archetype(p, "stat_dual")
    assert forced.archetype == p.archetype
    # a valid id is honoured
    assert apply_archetype(p, "rail_single").archetype == "rail_single"
    assert set(ARCHETYPES) >= {"stat_dual", "stat_single", "rail_single"}
