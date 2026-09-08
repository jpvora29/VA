"""A turn's evidence: one panel, one view per result set, always a table.

The reported defects this pins:

  * a rail turn reported "Chart can not be generated as the data is scalar" over
    result sets that were nothing of the kind;
  * a two-lens turn stacked a chart block per lens down the transcript;
  * an answer whose result set had no chart showed no evidence at all.

The flow covered is the real one:

    turn state -> evidence specs -> views (rows + figure) -> rendered panel

Run:  pytest tests/test_evidence_panel.py -q -o pythonpath=.
"""
from __future__ import annotations

import pandas as pd
import pytest
from dash.development.base_component import Component

from core.agents.common.chart_spec import stamp_intent
from ui.chart_functions import generate_chart
from ui.components.evidence import evidence_panel
from ui.evidence import build_view, build_views, label_for

PRODUCT_ROWS = [
    {"Product_Line": "Property", "Premium": 8_200_000},
    {"Product_Line": "Cyber", "Premium": 1_800_000},
    {"Product_Line": "Marine", "Premium": 900_000},
]
SURVEY_ROWS = [
    {"Carrier": "Subject", "Score": 7.1},
    {"Carrier": "Peer set", "Score": 6.4},
]
BAR = {"chart_type": "bar", "x": "Product_Line", "y": ["Premium"], "title": "Premium by line"}


def walk(node):
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)


def classes(node) -> list:
    return [(getattr(n, "className", "") or "") for n in walk(node)]


def texts(node) -> str:
    out = []
    for n in walk(node):
        children = getattr(n, "children", None)
        if isinstance(children, str):
            out.append(children)
    return " ".join(out)


def of_type(node, name) -> list:
    return [n for n in walk(node) if type(n).__name__ == name]


# ── the false "scalar" claim ────────────────────────────────────────────────


def test_an_empty_spec_is_not_turned_into_a_spec_by_stamping_intent():
    """`{}` means "no chart here"; stamping made it a truthy spec with no type."""
    assert stamp_intent({}, "premium by product line") == {}
    assert stamp_intent({"chart_type": "bar"}, "q")["intent"] == "q"


def test_a_real_result_set_is_never_reported_as_scalar():
    frame = pd.DataFrame(PRODUCT_ROWS)
    _fig, message = generate_chart(df=frame, chart_outputs={"chart_type": "none"})
    assert "scalar" not in message.lower()


def test_a_single_value_is_still_reported_as_scalar():
    _fig, message = generate_chart(
        df=pd.DataFrame([{"Premium": 8_200_000}]), chart_outputs={"chart_type": "none"}
    )
    assert "scalar" in message.lower()


# ── views ───────────────────────────────────────────────────────────────────


def test_a_view_carries_its_rows_whether_or_not_it_has_a_chart():
    charted = build_view(PRODUCT_ROWS, BAR, label="Premium")
    bare = build_view(PRODUCT_ROWS, {}, label="Premium")
    assert charted.has_chart and not bare.has_chart
    for view in (charted, bare):
        assert view.columns == ["Product_Line", "Premium"]
        assert len(view.records) == 3


def test_an_empty_result_set_is_not_a_view():
    assert build_view([], BAR, label="Premium") is None
    assert build_view(None, BAR, label="Premium") is None


def test_a_scalar_result_set_still_becomes_a_readable_view():
    """A bare value comes back as `[3]`, not `[{...}]`, and still has a table."""
    view = build_view([3], {}, label="Premium")
    assert view is not None and view.records == [{"value": 3}]


def test_an_error_string_is_not_mistaken_for_rows():
    """On a SQL error the rails leave a string where the rows go."""
    assert build_view("Please try again later !", {}, label="Premium") is None


def test_a_broken_chart_spec_costs_the_chart_not_the_table():
    view = build_view(PRODUCT_ROWS, {"chart_type": "bar", "x": "Nope", "y": ["Nope"]}, label="P")
    assert view is not None
    assert len(view.records) == 3


def test_a_view_is_named_for_its_chart_then_its_lens_then_its_position():
    assert label_for("premium", 0, {"title": "Premium by line"}) == "Premium by line"
    assert label_for("survey", 1, {}) == "Broker survey"
    assert label_for("", 2, {}) == "View 3"


# ── the panel ───────────────────────────────────────────────────────────────


def specs():
    return [
        {"rows": PRODUCT_ROWS, "chart_data": dict(BAR), "lens": "premium"},
        {"rows": SURVEY_ROWS, "chart_data": {}, "lens": "survey"},
    ]


def test_two_lenses_render_as_one_panel_with_two_tabs():
    views = build_views(specs())
    panel = evidence_panel(views, idx=4, pane_ids=[0, 1])
    assert len([c for c in classes(panel) if "ev-panel" in c]) == 1
    tabs = [n for n in walk(panel) if (getattr(n, "className", "") or "").split(" ")[0] == "ev-tab"]
    assert len(tabs) == 2
    assert [("active" in (t.className or "")) for t in tabs] == [True, False]
    assert "Broker survey" in texts(panel)


def test_only_the_first_view_is_visible():
    panel = evidence_panel(build_views(specs()), idx=4, pane_ids=[0, 1])
    panes = [n for n in walk(panel) if (getattr(n, "className", "") or "") == "ev-pane"]
    assert [n.style for n in panes] == [{}, {"display": "none"}]


def test_a_single_view_gets_no_tabs():
    views = build_views(specs()[:1])
    panel = evidence_panel(views, idx=4, pane_ids=[0])
    assert not any(c == "ev-tabs" for c in classes(panel))


def test_every_view_renders_a_data_table():
    """The rows are the evidence — an answer that produced numbers shows them."""
    panel = evidence_panel(build_views(specs()), idx=4, pane_ids=[0, 1])
    assert len(of_type(panel, "DataTable")) == 2


def test_a_view_without_a_chart_shows_its_table_with_no_chart_switch():
    panel = evidence_panel(build_views(specs()[1:]), idx=4, pane_ids=[0])
    assert of_type(panel, "DataTable")
    assert not of_type(panel, "Graph")
    assert not any(c == "chart-view-switch" for c in classes(panel))


def test_a_view_with_a_chart_keeps_its_chart_data_switch():
    panel = evidence_panel(build_views(specs()[:1]), idx=4, pane_ids=[0])
    assert of_type(panel, "Graph") and of_type(panel, "DataTable")
    assert any(c == "chart-view-switch" for c in classes(panel))


def test_nothing_to_show_renders_nothing():
    assert evidence_panel([], idx=4, pane_ids=[]) is None
    assert build_views([{"rows": [], "chart_data": BAR}]) == []


# ── the turn that produces them ─────────────────────────────────────────────


@pytest.fixture()
def commit():
    from ui.callbacks import _evidence_specs

    return _evidence_specs


def test_both_lenses_become_two_views_of_one_turn(commit):
    state = {
        "gpr_query_result": PRODUCT_ROWS,
        "gpr_chart": dict(BAR),
        "survey_query_result": SURVEY_ROWS,
        "survey_chart": {},
    }
    got = commit(state, "both")
    assert [s["lens"] for s in got] == ["premium", "survey"]


def test_a_lens_with_no_rows_is_not_a_view(commit):
    state = {"gpr_query_result": PRODUCT_ROWS, "gpr_chart": dict(BAR), "survey_query_result": []}
    assert [s["lens"] for s in commit(state, "both")] == ["premium"]


def test_analyst_charts_replace_the_per_lens_views(commit):
    state = {
        "analyst_charts": [{"rows": PRODUCT_ROWS, "chart_data": dict(BAR), "lens": "premium"}],
        "gpr_query_result": SURVEY_ROWS,
        "gpr_chart": {},
    }
    got = commit(state, "premium")
    assert len(got) == 1 and got[0]["rows"] == PRODUCT_ROWS
