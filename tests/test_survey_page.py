"""The Carrier Survey page — detection against the REAL template, and its fill payload."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from studio import seed as S
from studio.template_fill import roles as R
from studio.template_fill.analyze import analyze
from studio.template_fill.sections import Section, section_of
from studio.template_fill.survey import page as P

_TEMPLATE = "template/survey_template.pptx"


@pytest.fixture(scope="module")
def template():
    return analyze(_TEMPLATE)


@pytest.fixture(scope="module")
def result():
    """Injects the seed engine explicitly so the test needs no ``DB_PATH``."""
    from studio.compute import OverallResult
    from studio.data import get_engine

    S.ensure_seed_db()
    return OverallResult(subject=S.SUBJECT, flow="gpr",
                         resolved_filters={"Country": "Singapore"}, engine=get_engine())


def test_the_survey_slide_classifies_as_its_own_section(template):
    assert section_of(template.slides[0]) is Section.SURVEY


def test_other_templates_are_unaffected_by_the_new_section_rule():
    """Every OTHER top-level template, globbed (not hardcoded) so a template added later is
    covered automatically — ``template/old`` is excluded on purpose, non-recursive glob."""
    templates = sorted(Path("template").glob("*.pptx"))
    others = [p for p in templates if p.name != "survey_template.pptx"]
    assert others, "expected at least one other template to guard against"
    for path in others:
        for slide in analyze(str(path)).slides:
            assert section_of(slide) is not Section.SURVEY


def test_page_detection_finds_the_table_axes_and_the_ribbon(template):
    pages = P.pages(template)
    assert len(pages) == 1
    page = pages[0]
    assert [label for _, label in page.rows] == S.SURVEY_SECTIONS
    assert [label for _, label in page.cols] == S.SURVEY_PRACTICES
    assert page.total_row is not None and page.total_col is not None
    assert page.ribbon_id is not None


def test_the_ribbon_is_the_taller_picture_not_the_legend(template):
    page = P.pages(template)[0]
    legend = min((sh for sh in template.slides[0].shapes if sh.kind == "picture"),
                 key=lambda sh: sh.h)
    assert page.ribbon_id != legend.shape_id


def test_augment_binds_every_data_cell_and_both_axis_headers(template):
    bound = P.augment(template, [])
    roles = {b.role for b in bound}
    page = P.pages(template)[0]
    # body + one total per row + one per column + the corner, plus the axis HEADERS: the
    # page reports the carrier's OWN sections and practices, so the labels are filled too.
    data = len(page.rows) * len(page.cols) + len(page.rows) + len(page.cols) + 1
    headers = len(page.rows) + len(page.cols)
    assert len([r for r in roles if r and r.startswith(P.ROLE_PREFIX)]) == data + headers
    assert all(not b.placeholder for b in bound if str(b.role or "").startswith(P.ROLE_PREFIX))


def test_augment_is_idempotent(template):
    once = P.augment(template, [])
    twice = P.augment(template, list(once))
    assert len(twice) == len(once)


def test_values_fills_every_cell_and_emits_band_colours(template, result):
    values = P.values(template, result)
    page = P.pages(template)[0]
    for row, _ in page.rows:
        for col, _ in page.cols:
            assert P._role(page.slide_idx, row, col) in values
    fills = values["cell_fills"][f"{page.slide_idx}:{page.table_id}"]
    assert fills, "no cell colours computed"
    assert {f["hex"] for f in fills} - {None}, "every cell landed in the neutral band"
    assert all(f["hex"] is None or len(f["hex"]) == 6 for f in fills)


def test_values_renders_the_ribbon_picture(template, result):
    from studio.template_fill.survey import ribbon

    if not ribbon.available():
        pytest.skip("kaleido/Chrome not available on this host")
    values = P.values(template, result)
    page = P.pages(template)[0]
    png = values["pictures"][f"{page.slide_idx}:{page.ribbon_id}"]
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_values_survives_a_broken_renderer(template, result, monkeypatch):
    """A dead renderer must cost the CHART only — the table still fills."""
    from studio.template_fill.survey import ribbon

    monkeypatch.setattr(ribbon, "render_ribbon_png",
                        lambda spec: (_ for _ in ()).throw(RuntimeError("no chrome")))
    values = P.values(template, result)
    assert not values.get("pictures")
    assert values.get("cell_fills")


def test_values_is_empty_for_a_country_with_no_survey(template):
    from studio.compute import OverallResult
    from studio.data import get_engine

    result = OverallResult(subject=S.SUBJECT, flow="gpr",
                           resolved_filters={"Country": "Atlantis"}, engine=get_engine())
    assert P.values(template, result) == {}


def test_values_is_empty_for_a_template_without_a_survey_page(result):
    assert P.values(analyze("template/country_template.pptx"), result) == {}


# ── the page's axes belong to the carrier, not to the template ───────────────


def test_the_axes_are_the_practices_and_sections_the_carrier_is_surveyed_on(template, result):
    """A carrier surveyed on three practices gets a three-column page — not seven columns,
    six of them x.x. The authored slots supply the layout; the book supplies the labels."""
    from studio.template_fill.survey import facts

    page = P.pages(template)[0]
    grid = facts.load_grid(result, "Singapore")
    thin = dataclasses.replace(grid, practices=("CE/CM", "Cyber", "Marsh Multinational"))
    axes = P.axes_for(page, thin)
    assert [p for p in axes.practices if p] == ["CE/CM", "Cyber", "Marsh Multinational"]
    assert axes.practices.count(None) == len(page.cols) - 3


def test_a_slot_the_book_cannot_fill_is_blanked_not_left_authored(template, result):
    from studio.template_fill.survey import facts

    page = P.pages(template)[0]
    grid = facts.load_grid(result, "Singapore")
    thin = dataclasses.replace(grid, practices=("CE/CM",))
    texts, _ = P._table_payload(page, thin)
    # The first authored column keeps its label; every other column header is blanked, and
    # so is every cell under it — an authored practice this carrier does not write must not
    # ship over a column of placeholders.
    headers = [texts[P._role(page.slide_idx, 0, c)] for c, _ in page.cols]
    assert headers[0] == "CE/CM" and set(headers[1:]) == {""}
    body = [texts[P._role(page.slide_idx, r, c)] for r, _ in page.rows for c, _ in page.cols[1:]]
    assert set(body) == {""}


def test_a_practice_the_template_never_had_still_reaches_the_page(template, result):
    """The book leads. A practice the author never drew a column for takes one of the
    slots the carrier does not need."""
    from studio.template_fill.survey import facts

    page = P.pages(template)[0]
    grid = facts.load_grid(result, "Singapore")
    thin = dataclasses.replace(grid, practices=("CE/CM", "Political Risk"))
    axes = P.axes_for(page, thin)
    assert [p for p in axes.practices if p] == ["CE/CM", "Political Risk"]


def test_the_authored_order_is_kept_for_labels_the_book_shares(template, result):
    from studio.template_fill.survey import facts

    page = P.pages(template)[0]
    grid = facts.load_grid(result, "Singapore")
    axes = P.axes_for(page, grid)
    assert list(axes.practices) == [label for _, label in page.cols]
    assert list(axes.sections) == [label for _, label in page.rows]


def test_assign_axis_packs_the_book_into_the_slots_from_the_start():
    # Shared labels first, in the AUTHORED order; then the book's extras; then None. The
    # filled part is contiguous — a hole between two scores reads as a rendering fault.
    assert P.assign_axis(["A", "B", "C"], ["c", "A", "Zed"]) == ["A", "c", "Zed"]
    assert P.assign_axis(["A", "B"], ["A"]) == ["A", None]
    assert P.assign_axis(["A", "B"], []) == [None, None]
    # An unchanged carrier gets an unchanged page.
    assert P.assign_axis(["A", "B"], ["B", "A"]) == ["A", "B"]
