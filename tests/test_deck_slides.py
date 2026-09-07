"""The page selection: what "What's in your QBR" writes, and what the builder reads.

The deck's shape used to be a four-way scope radio. It is now a tick per template page, and
the value behind those ticks (:class:`studio.template_fill.deck_slides.DeckSlides`) is read
by the panel, the cost estimate, the assembler and the fill engine. These tests hold it to
the three promises the rest of the change rests on:

* what the CATALOG lists comes from the templates themselves, so a re-authored template
  changes the form with no code change;
* a selection is stored as EXCLUSIONS, so a page added to a template later joins the deck
  instead of vanishing from every saved selection;
* an unreadable stored value degrades to "build it all" rather than failing a build.

The preview thumbnails are held to one promise: reading them never renders anything, because
the panel reads them on every repaint and rendering means opening PowerPoint.
"""
from __future__ import annotations

import pytest

from studio.template_fill import slide_previews
from studio.template_fill.deck_slides import (
    DECK_AXES,
    DeckSlides,
    catalog,
    from_selection,
    slide_count,
)


# ── the catalog comes from the templates ────────────────────────────────────


def test_the_catalog_lists_every_slide_of_a_registered_template():
    entries = catalog("overall")

    assert entries, "the overall template must be registered for these tests"
    assert [e.index for e in entries] == list(range(len(entries)))
    assert all(e.axis == "overall" for e in entries)
    assert slide_count("overall") == len(entries)


def test_every_slide_carries_the_section_the_classifier_gave_it():
    """The row's label is the page's SECTION, so a renamed slide still reads correctly."""
    from studio.template_fill.analyze import analyze
    from studio.template_fill.binding_map import template_path
    from studio.template_fill.sections import classify_sections

    sections = classify_sections(analyze(template_path("overall")))
    assert {e.index: e.section for e in catalog("overall")} == {
        i: s.value for i, s in sections.items()}


def test_an_unregistered_axis_has_no_pages_rather_than_an_exception():
    assert catalog("no-such-axis") == ()
    assert slide_count("no-such-axis") == 0


# ── the selection ───────────────────────────────────────────────────────────


def test_nothing_excluded_is_the_whole_deck():
    slides = DeckSlides.everything()

    assert slides.empty
    assert slides.includes("overall", 0)
    assert slides.hidden("overall") == ()
    assert slides.wants("overall")


def test_the_selection_is_normalised_so_two_ways_of_saying_it_compare_equal():
    assert DeckSlides({"overall": [2, 1, 1]}) == DeckSlides({"overall": (1, 2)})
    assert DeckSlides({"overall": []}) == DeckSlides.everything()
    assert hash(DeckSlides({"overall": [1]})) == hash(DeckSlides({"overall": [1]}))


def test_an_excluded_page_is_hidden_and_the_rest_are_kept():
    slides = DeckSlides({"overall": [1]})

    assert not slides.includes("overall", 1)
    assert slides.hidden("overall") == (1,)
    assert 1 not in [e.index for e in slides.kept("overall")]
    assert len(slides.kept("overall")) == slide_count("overall") - 1


def test_an_axis_with_every_page_excluded_is_not_built():
    every = [e.index for e in catalog("product")]
    slides = DeckSlides({"product": every})

    assert not slides.wants("product")
    assert "product" not in slides.axes(("overall", "product"))
    assert slides.wants("overall")


def test_only_keeps_the_named_axes_and_always_the_back_cover():
    """The old scope choices, said in the new vocabulary: every one of them closed on the
    back cover, so a deck built from ``only`` does too."""
    slides = DeckSlides.only("overall")

    assert slides.wants("overall") and slides.wants("end")
    assert not slides.wants("product") and not slides.wants("country")


def test_the_axes_come_back_in_deck_order_however_they_were_given():
    slides = DeckSlides.everything()
    assert slides.axes(("end", "country", "overall")) == ("overall", "country", "end")
    assert list(DECK_AXES).index("survey") == list(DECK_AXES).index("country") + 1


# ── what crosses the wire ───────────────────────────────────────────────────


def test_the_store_round_trips():
    slides = DeckSlides({"country": [1, 3]})
    assert DeckSlides.from_store(slides.as_store()) == slides
    assert slides.as_store() == {"country": [1, 3]}


def test_nothing_stored_means_the_whole_deck():
    for stored in (None, {}, ""):
        assert DeckSlides.from_store(stored).empty


def test_an_unreadable_stored_value_builds_everything_rather_than_failing():
    """``qs-slides`` lives in local storage, so it outlives the release that wrote it."""
    for junk in ("nonsense", 7, [1, 2, 3], {"overall": "all of them"}):
        assert DeckSlides.from_store(junk).empty


def test_a_selection_carries_its_pages_to_the_build():
    assert from_selection({"slides": {"end": [0]}}).hidden("end") == (0,)
    assert from_selection({}).empty
    assert from_selection(None).empty


# ── the hover thumbnails ────────────────────────────────────────────────────


def test_reading_the_thumbnails_never_renders_anything(monkeypatch):
    """The panel reads these on every repaint. Rendering means opening PowerPoint, which
    is seconds — so a cache MISS has to answer ``None``, not start a render."""
    from studio.template_fill import preview_assets

    def explode(*_a, **_kw):  # pragma: no cover - the point is that it is not called
        raise AssertionError("reading thumbnails must not render")

    monkeypatch.setattr(preview_assets, "_render_slides", explode)
    monkeypatch.setattr(preview_assets, "ensure_rendered_slide_backgrounds", explode)

    urls = slide_previews.urls("overall")
    assert len(urls) == slide_count("overall")
    assert all(u is None or u.startswith("/assets/") for u in urls)


def test_an_unknown_axis_has_no_thumbnails():
    assert slide_previews.urls("no-such-axis") == ()


def test_warming_an_axis_happens_once_per_process(monkeypatch):
    """The templates are fixed and the PNGs are cached on disk; a second pass would open
    PowerPoint to discover it has nothing to do."""
    rendered = []
    monkeypatch.setattr(slide_previews, "_warmed", set())
    monkeypatch.setattr(slide_previews, "_render", lambda axis: rendered.append(axis))

    slide_previews.warm(("overall",))
    slide_previews.warm(("overall",))

    assert rendered == ["overall"]
