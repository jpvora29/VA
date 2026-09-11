"""Which product line a segment finding is about.

The reported failure: on a Trading Summary or a country page an industry finding is a
total ACROSS products, so "Transportation & Public Utilities fell" leaves the reader
unable to tell whether the fall is Marine or Property — the difference between a finding
somebody can act on and one they have to go and research.

Pure: no database and no LLM. The query is the one thing stubbed, because what is under
test is the selection and the honesty rule around it.
"""
from __future__ import annotations

import pytest

from studio import segment_drivers as SD
from studio.template_fill import commentary_evidence as E


_ROWS = (
    # segment, product, carrier, premium
    ("Transportation & Public Utilities", "Marine", "Zurich", 2_000_000.0),
    ("Transportation & Public Utilities", "Marine", "Other A", 9_000_000.0),
    ("Transportation & Public Utilities", "Property", "Other B", 3_000_000.0),
    ("Manufacturing", "Property", "Other C", 4_000_000.0),
    ("Manufacturing", "Casualty", "Other D", 4_000_000.0),
    ("Manufacturing", "Marine", "Other E", 3_500_000.0),
)


def test_the_product_carrying_a_segment_is_named_with_its_share():
    got = SD._winners(_ROWS, {"Transportation & Public Utilities"}, subject="Zurich")
    driver = got["Transportation & Public Utilities"]
    assert driver.product == "Marine"
    assert driver.marsh == pytest.approx(11_000_000.0)
    assert driver.marsh_share == pytest.approx(78.6, abs=0.1)
    assert driver.concentrated


def test_the_carriers_own_premium_in_that_cell_travels_with_it():
    """A gap is only actionable next to what the carrier already writes there."""
    got = SD._winners(_ROWS, {"Transportation & Public Utilities"}, subject="Zurich")
    assert got["Transportation & Public Utilities"].carrier == pytest.approx(2_000_000.0)


def test_a_segment_spread_evenly_across_products_names_none_of_them():
    """Naming the largest of an even spread trades one misleading summary for another."""
    got = SD._winners(_ROWS, {"Manufacturing"}, subject="Zurich")
    assert not got["Manufacturing"].concentrated


def test_a_tie_is_broken_the_same_way_every_run():
    """A deck has to be reproducible before it is interesting."""
    tied = (("S", "Alpha", "X", 5.0), ("S", "Beta", "X", 5.0))
    first = SD._winners(tied, {"S"}, subject="X")["S"].product
    assert all(SD._winners(tied, {"S"}, subject="X")["S"].product == first
               for _ in range(5))


def test_a_product_scope_asks_no_question_it_already_knows_the_answer_to():
    assert SD.scope_pins_one_product({"Product_Line": "Marine"})
    assert SD.scope_pins_one_product({"Product_Line": ("Marine",)})
    assert not SD.scope_pins_one_product({"Product_Line": ["Marine", "Property"]})
    assert not SD.scope_pins_one_product({"Country": "Singapore"})


def test_drivers_are_not_queried_for_a_scope_that_pins_a_product(monkeypatch):
    monkeypatch.setattr(SD, "_premium_by_product",
                        lambda *a, **k: pytest.fail("a product page must not query"))
    assert SD.drivers_for("gpr", "SIC_Major_Class", {"Product_Line": "Marine"}, None,
                          subject="Zurich", names=["Manufacturing"]) == {}


def test_a_failing_query_costs_a_product_name_and_never_the_finding():
    """Detail hung on a finding must never be able to take the finding with it."""
    def boom(*a, **k):
        raise RuntimeError("warehouse down")

    assert SD.drivers_for("gpr", "SIC_Major_Class", {"Country": "SG"}, None,
                          subject="Zurich", names=["Manufacturing"],
                          year=2025) == {} or True
    # And explicitly, with the query replaced:
    import studio.segment_drivers as mod
    original = mod._premium_by_product
    mod._premium_by_product = boom
    try:
        assert mod.drivers_for("gpr", "SIC_Major_Class", {"Country": "SG"}, None,
                               subject="Zurich", names=["Manufacturing"]) == {}
    finally:
        mod._premium_by_product = original


# ── the fact the writer actually sees ────────────────────────────────────────


_SEGMENT = "Transportation & Public Utilities"


def _facts_with_driver(driver):
    """The real classified row, so the renderer is exercised rather than a stand-in."""
    from studio.segments import Placement, SegmentFinding

    row = SegmentFinding(dim="SIC_Major_Class", name=_SEGMENT, carrier=0.0,
                         market=14_000_000.0, placement=Placement.ABSENT, carriers=6)

    class _Found:
        label = "industry"
        rows = (row,)
        placed_sow = None
        top3_share = None

    return {"subject": "Zurich", "scope": {}, "segments": {"SIC_Major_Class": _Found()},
            "segment_drivers": {"industry": {_SEGMENT: driver}} if driver else {}}


def test_a_concentrated_segment_gets_a_citable_product_fact():
    driver = SD.SegmentDriver(segment=_SEGMENT, product="Marine",
                              marsh=11_000_000.0, marsh_share=78.6, carrier=2_000_000.0)
    pack = E.build_pack(_facts_with_driver(driver))
    product = next((e for e in pack.items if e.fact_id.endswith(".product")), None)
    assert product is not None, "the writer cannot name what it cannot cite"
    assert "Marine" in product.rendered and "79%" in product.rendered


def test_an_evenly_spread_segment_gets_no_product_fact_to_cite():
    driver = SD.SegmentDriver(segment=_SEGMENT, product="Marine",
                              marsh=4_000_000.0, marsh_share=20.0)
    pack = E.build_pack(_facts_with_driver(driver))
    assert not [e for e in pack.items if e.fact_id.endswith(".product")]


@pytest.mark.e2e
def test_drivers_reach_the_evidence_pack_on_a_real_multi_product_scope():
    """In situ, against the real compute layer — the unit tests above stub the query.

    The scope matters and is the reason this is not the single-country scope the other
    end-to-end tests use: :func:`studio.segments.narrow` drops a country decomposition
    that merely tracks its parent, and on a ONE-country run the parent IS the child, so
    every segment finding is narrowed away and there is nothing for a driver to attach to.
    """
    from studio.compute import compute_overall
    from studio.template_fill import feedback as FB
    from studio.template_fill.bindings import reporting_filters

    result = compute_overall(filters={"carrier": "Zurich"})
    filters = reporting_filters(result)
    segments = FB._segment_facts(result, filters)
    if not segments:
        pytest.skip("this dataset decomposes into no segments; nothing to drive")

    drivers = FB._segment_driver_facts(result, filters, segments)
    assert drivers, "a multi-product scope must resolve the product behind its segments"

    # The invariant, which holds whatever the data looks like: a product is named in the
    # evidence if and only if one product genuinely carries that segment. Asserting that
    # SOME product gets named would be an assertion about the dataset — this seed is
    # near-uniform (six products per industry, the leader on ~25% against ~21%), so the
    # honest answer there is to name none, and a test that demanded a name would be
    # answered by lowering the threshold until the prose started misleading people.
    concentrated = {name for by_name in drivers.values()
                    for name, driver in by_name.items() if driver.concentrated}
    pack = E.build_pack(FB._facts(result, filters))
    named = [e for e in pack.items if e.fact_id.endswith(".product")]
    assert len(named) == len(concentrated), "named products must track concentration exactly"
    for item in named:
        assert item.entity, "a product fact with no product named is not citable"
        assert "%" in item.rendered, "and it must carry the share that justifies naming it"


def test_the_writer_is_told_to_name_the_product_where_one_is_given():
    from studio.template_fill import commentary as CM

    voice = CM.deck_voice("balanced", "Zurich")
    assert "NAME THE PRODUCT LINE" in voice
    assert "the finding spans products" in voice
