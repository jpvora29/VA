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


def test_augment_binds_every_data_cell(template):
    bound = P.augment(template, [])
    roles = {b.role for b in bound}
    page = P.pages(template)[0]
    # body + one total per row + one per column + the corner
    expected = len(page.rows) * len(page.cols) + len(page.rows) + len(page.cols) + 1
    assert len([r for r in roles if r and r.startswith(P.ROLE_PREFIX)]) == expected
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


# ── when an axis genuinely does not match ────────────────────────────────────


def test_an_authored_label_the_book_does_not_have_is_named_in_the_log(template, result, caplog):
    """A template that says "FINPRO" against a book that says "Financial Lines" fills
    nothing on that column and looks, on the slide, exactly like a warehouse with no survey.
    Only a log carrying BOTH vocabularies tells the two apart, so it prints them."""
    import logging

    from studio.template_fill.survey import facts

    page = P.pages(template)[0]
    grid = facts.load_grid(result, "Singapore")
    thin = dataclasses.replace(grid, sections=("Underwriting",), practices=("CE/CM",))
    with caplog.at_level(logging.WARNING, logger="studio.template_fill.survey.page"):
        P._report_unmatched(page, thin)
    logged = caplog.text
    assert "column label" in logged and "row label" in logged
    assert "FINPRO" in logged and "CE/CM" in logged        # authored, and the book's own


def test_nothing_is_logged_when_every_axis_matches(template, result, caplog):
    import logging

    from studio.template_fill.survey import facts

    with caplog.at_level(logging.WARNING, logger="studio.template_fill.survey.page"):
        P._report_unmatched(P.pages(template)[0], facts.load_grid(result, "Singapore"))
    assert "not in the survey book" not in caplog.text
