"""What's in the deck stays the author's choice, and a build's cost is knowable before it runs.

Two halves of the same complaint. A filter is a DATA choice — "this country's numbers" — and
the page list is a SHAPE choice — "this deck carries the SWOT page and not the ranking one".
Conflating them means a one-country filter silently produces a one-country deck, or (the
version that actually shipped) the panel promises a shape the builder does not make.

The shape choice used to be a four-way scope radio (Entire QBR / Overall / Product-wise /
Country-wise) and is now a tick per template page (:mod:`studio.template_fill.deck_slides`),
so the same guarantees are asserted against the ticks: nothing but the author moves them, an
axis with no pages left is not built, and the panel that describes the deck is read off the
same function the builder plans from.

The second half is the arithmetic the performance work rests on: a six-product, one-country
Entire QBR asks for 27 commentary fields, and if that number cannot be computed before the
build, nothing downstream of it can be measured either.
"""
from __future__ import annotations

import pytest

from studio.page.authoring.setup import deck_axes, registered_axes, template_sections_panel
from studio.template_fill import commentary_fields as F
from studio.template_fill.deck_slides import DeckSlides, catalog


def _all_of(axis: str) -> list:
    """Every slide index of ``axis`` — how a test unticks a whole sub-deck."""
    return [e.index for e in catalog(axis)]


# ── the page selection is never mutated by a filter ─────────────────────────


def test_only_the_page_ticks_write_the_page_selection():
    """The acceptance criterion, asserted where it can actually be broken.

    ``qs-slides`` is what the deck's shape is read from. If any callback other than the one
    reading the checkboxes declares it as an Output, some other control can move it — which
    is precisely the "picking a country switched me to country-only" behaviour the plan
    rules out. Everywhere else it may be read as State/Input only.
    """
    from pathlib import Path

    sources = list(Path("studio").rglob("*.py"))
    offenders = [
        f"{path}:{i}" for path in sources
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if 'Output("qs-slides"' in line
    ]
    assert len(offenders) == 1, (
        f"exactly one callback may write the page selection, found: {offenders}")


def test_the_default_deck_is_every_page():
    slides = DeckSlides.everything()
    assert slides.empty
    for axis in registered_axes():
        assert len(slides.kept(axis)) == len(catalog(axis))


def test_the_deck_still_ends_on_the_back_cover():
    assert deck_axes()[-1] == "end"


def test_unticking_a_page_takes_it_out_of_the_deck_and_nothing_else():
    slides = DeckSlides({"overall": [4]})
    kept = [e.index for e in slides.kept("overall")]

    assert 4 not in kept
    assert len(kept) == len(catalog("overall")) - 1
    assert slides.wants("overall")                       # a shorter block, not no block
    assert "overall" in deck_axes()


def test_unticking_every_page_of_an_axis_drops_the_sub_deck():
    """This is what replaced "Overall only": the product and country pages come off, and
    the builder is told by the same value the panel shows."""
    slides = DeckSlides({"product": _all_of("product"), "country": _all_of("country")})

    assert not slides.wants("product") and not slides.wants("country")
    assert deck_axes(slides=slides) == ("overall", "end")


def test_the_panel_lists_every_axis_even_the_ones_ticked_off():
    """An axis unticked in full still has to be on screen, or there is no way back."""
    import json

    slides = DeckSlides({"product": _all_of("product")})
    panel = json.dumps(template_sections_panel(slides=slides),
                       default=lambda o: getattr(o, "__dict__", str(o)))

    assert "Product" in panel
    assert "qs-slide-row is-off" in panel


def test_the_preview_and_the_builder_agree_on_a_selection():
    """The panel and the plan read one function, so they cannot drift."""
    from studio.compute import compute_overall
    from studio.template_fill.assemble import deck_shape

    slides = DeckSlides({"product": _all_of("product")})
    result = compute_overall(filters={"carrier": "Zurich"})

    assert deck_shape(result, slides=slides).axes == deck_axes(slides=slides)


def test_a_deck_with_no_pages_is_refused_rather_than_built_empty():
    """Every page unticked is a request for no deck. The check reads what will be BUILT,
    not the ticks: the survey block is gated by the data basis and is never unticked on a
    premium run (its rows are not on screen), so a selection with everything else off used
    to still look like a deck and produce an empty file.
    """
    from studio.compute import DATA_BASIS_PREMIUM, DATA_BASIS_WITH_SURVEY

    nothing = DeckSlides({axis: _all_of(axis) for axis in registered_axes()
                          if axis != "survey"})

    assert not deck_axes(DATA_BASIS_PREMIUM, nothing)
    assert not deck_axes(DATA_BASIS_WITH_SURVEY, nothing)
    assert deck_axes(DATA_BASIS_PREMIUM, DeckSlides.everything())


# ── the commentary-field arithmetic ─────────────────────────────────────────


def test_the_shipped_templates_carry_the_field_counts_the_plan_assumes():
    """5 overall, 3 per product, 4 per country — the numbers the whole latency budget
    is derived from. Counted off the templates, so re-authoring one moves the number."""
    assert F.fields_for_axis("overall") == 5
    assert F.fields_for_axis("product") == 3
    assert F.fields_for_axis("country") == 4


def test_a_six_product_one_country_entire_qbr_asks_for_27_fields():
    assert F.deck_fields({"overall": 1, "product": 6, "country": 1}) == 27


def test_a_page_left_out_is_a_page_nobody_pays_to_write():
    """The whole point of the tick: the estimate — and the build — drop the work.

    Counted over the SWOT/trading-summary pages of the overall block, which are the ones
    that carry commentary; unticking them has to move the number Setup shows.
    """
    every = F.fields_for_axis("overall")
    fewer = F.fields_for_axis("overall", hidden=_all_of("overall"))

    assert fewer == 0
    assert F.deck_fields({"overall": 1}, hidden={"overall": _all_of("overall")}) == 0
    assert every > 0


def test_fields_are_counted_per_ANSWER_not_per_textbox():
    """A topic heading a column on two pages is one question asked twice and is answered
    once (``commentary.values`` caches by topic). Counting boxes reported 24 written fields
    for a product template that makes three calls."""
    from studio.template_fill.analyze import analyze
    from studio.template_fill.binding_map import template_path

    from studio.template_fill import feedback

    template = analyze(template_path("product"))

    written_kinds = set(feedback._COMPOSERS) - {"highlights"}
    raw_targets = [t for t in feedback._targets(template) if t["kind"] in written_kinds]
    assert len(raw_targets) > F.fields(template), "the count must collapse repeated rows"


def test_a_broken_axis_counts_zero_rather_than_raising():
    assert F.fields_for_axis("no-such-axis") == 0
    assert catalog("no-such-axis") == ()


# ── the deck shape one selection produces ───────────────────────────────────


def _result():
    """A real result over the seed book — ``deck_shape`` runs vocabulary queries on it."""
    from studio.compute import compute_overall

    return compute_overall(filters={"carrier": "Zurich"})


def test_deck_shape_blocks_match_the_pages_that_are_ticked():
    from studio.template_fill.assemble import deck_shape

    slides = DeckSlides({"product": _all_of("product"), "country": _all_of("country")})
    shape = deck_shape(_result(), slides=slides)

    assert set(shape.blocks()) <= {"overall", "end"}
    assert shape.blocks()["overall"] == 1
    assert not shape.products and not shape.countries


def test_deck_shape_is_what_the_builder_builds():
    """The preview and the plan read one function, so they cannot drift."""
    from studio.template_fill.assemble import SubDeckPlanBuilder, deck_shape

    result = _result()
    shape = deck_shape(result)
    builder = SubDeckPlanBuilder(result)
    assert builder._products == shape.products
    assert builder._countries == shape.countries
    assert builder._wants_survey == shape.with_survey
    assert builder._axes == shape.axes


def test_a_selection_can_be_costed_before_it_is_built():
    from studio.template_fill.assemble import deck_shape

    shape = deck_shape(_result())
    assert shape.commentary_fields() > 0
    assert shape.pages() > 0
    assert sum(shape.blocks().values()) >= 1


def test_removing_pages_lowers_the_quoted_cost_of_the_same_selection():
    from studio.template_fill.assemble import deck_shape

    result = _result()
    whole = deck_shape(result)
    trimmed = deck_shape(result, slides=DeckSlides({"country": _all_of("country")}))

    assert trimmed.pages() < whole.pages()
    assert trimmed.commentary_fields() < whole.commentary_fields()


def test_an_unticked_page_costs_no_model_calls():
    """The promise behind the tick: a page left out is not composed, so it is not written.

    Dropping the slide at fill time alone would have left the deck paying for commentary
    nobody would read — the providers read the template to find the boxes they fill, so the
    excluded pages have to be out of the template they are shown.
    """
    from studio.compute import OverallResult
    from studio.template_fill import rewrites
    from studio.template_fill.assemble import SubDeckPlanBuilder

    def composed(slides) -> int:
        builder = SubDeckPlanBuilder(OverallResult(subject="Zurich"), slides=slides)
        return sum(len(list(rewrites.pending_items(deck.values)))
                   for deck in builder.add_overall().build())

    others = {"product": _all_of("product"), "country": _all_of("country")}
    whole = composed(DeckSlides(others))
    # The overall block's trading-summary page is where its prose columns live.
    trimmed = composed(DeckSlides({**others, "overall": [3]}))

    assert whole > trimmed, "excluding a commentary page must remove its columns"


def test_an_unticked_page_reaches_the_sub_deck_as_a_dropped_slide():
    """End of the chain: the tick becomes a slide the fill engine is told to leave out."""
    from studio.template_fill.assemble import SubDeckPlanBuilder

    builder = SubDeckPlanBuilder(_result(), slides=DeckSlides({"end": [0]}))
    assert not builder._wants("end") or builder._slides.hidden("end") == (0,)
