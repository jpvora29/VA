"""Scope stays the author's choice, and the cost of a build is knowable before it runs.

Two halves of the same complaint. A filter is a DATA choice — "this country's numbers" —
and the scope is a SHAPE choice — "the whole QBR, or just the country blocks". Conflating
them means a one-country filter silently produces a one-country deck, or (the version that
actually shipped) the panel promises a shape the builder does not make.

The second half is the arithmetic the performance work rests on: a six-product, one-country
Entire QBR asks for 27 commentary fields, and if that number cannot be computed before the
build, nothing downstream of it can be measured either.
"""
from __future__ import annotations

import pytest

from studio.page.authoring.setup import _SCOPE_LABELS, deck_axes, scope_axes
from studio.template_fill import commentary_fields as F


# ── scope is never mutated by a filter ──────────────────────────────────────


def test_no_callback_writes_the_scope_control():
    """The acceptance criterion, asserted where it can actually be broken.

    ``studio-template`` is the Scope radio. If any callback ever declares it as an Output,
    some other control can move it — which is precisely the "picking a country switched me
    to country-only" behaviour the plan rules out. It may only be read as State/Input.
    """
    from pathlib import Path

    sources = list(Path("studio").rglob("*.py"))
    offenders = [
        f"{path}:{i}" for path in sources
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if 'Output("studio-template"' in line
    ]
    assert not offenders, f"the scope control must never be written by a callback: {offenders}"


def test_the_default_scope_is_the_entire_qbr():
    from studio.page.authoring.setup import _template_control

    radio = _template_control().children[1]
    assert radio.value == "all"
    assert radio.options[0]["value"] == "all"


def test_the_scope_labels_describe_what_the_deck_contains():
    """"Country only" described a deck that has never been built: the country scope also
    assembles the overall block."""
    assert _SCOPE_LABELS["all"] == "Entire QBR"
    assert _SCOPE_LABELS["country"] == "Country-wise"
    assert _SCOPE_LABELS["product"] == "Product-wise"
    assert "only" not in " ".join(_SCOPE_LABELS.values()).lower()


@pytest.mark.parametrize("scope", ["all", "overall", "product", "country"])
def test_every_scope_ends_on_the_back_cover(scope):
    assert scope_axes(scope)[-1] == "end"


def test_the_preview_and_the_builder_agree_on_every_scope():
    from studio.template_fill.assemble import _SCOPE_AXES as BUILT
    from studio.page.authoring.setup import _SCOPE_AXES as PREVIEWED

    assert PREVIEWED == BUILT


# ── the commentary-field arithmetic ─────────────────────────────────────────


def test_the_shipped_templates_carry_the_field_counts_the_plan_assumes():
    """5 overall, 3 per product, 4 per country — the numbers the whole latency budget
    is derived from. Counted off the templates, so re-authoring one moves the number."""
    assert F.fields_for_axis("overall") == 5
    assert F.fields_for_axis("product") == 3
    assert F.fields_for_axis("country") == 4


def test_a_six_product_one_country_entire_qbr_asks_for_27_fields():
    assert F.deck_fields({"overall": 1, "product": 6, "country": 1}) == 27


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


# ── the deck shape one selection produces ───────────────────────────────────


def _result():
    """A real result over the seed book — ``deck_shape`` runs vocabulary queries on it."""
    from studio.compute import compute_overall

    return compute_overall(filters={"carrier": "Zurich"})


def test_deck_shape_blocks_match_the_axes_in_scope():
    from studio.template_fill.assemble import deck_shape

    shape = deck_shape(_result(), scope="overall")
    assert set(shape.blocks()) <= {"overall", "end"}
    assert shape.blocks()["overall"] == 1
    assert not shape.products and not shape.countries


def test_deck_shape_is_what_the_builder_builds():
    """The preview and the plan read one function, so they cannot drift."""
    from studio.template_fill.assemble import SubDeckPlanBuilder, deck_shape

    result = _result()
    shape = deck_shape(result, scope="all")
    builder = SubDeckPlanBuilder(result, scope="all")
    assert builder._products == shape.products
    assert builder._countries == shape.countries
    assert builder._wants_survey == shape.with_survey


def test_a_selection_can_be_costed_before_it_is_built():
    from studio.template_fill.assemble import deck_shape

    shape = deck_shape(_result(), scope="all")
    assert shape.commentary_fields() > 0
    assert sum(shape.blocks().values()) >= 1
