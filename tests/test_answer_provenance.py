"""Can a reader check this answer?

The trust layer (roadmap §7). An answer is a paragraph until you can see the
scope it ran under, the definition of every term it used, the queries behind it,
and — the part that earns the panel — which figures in the prose the rows do NOT
contain.

The flow covered is the real one:

    finished turn state -> provenance record -> the drawer under the answer

Run:  pytest tests/test_answer_provenance.py -q -o pythonpath=.
"""
from __future__ import annotations

from dash.development.base_component import Component

from core.answers import figures as fig
from core.answers import provenance as pv
from ui.components.chatbot import ai_message
from ui.components.provenance import provenance_drawer

ROWS = [
    {"Product_Line": "Property", "Premium": 8_237_411.0, "Share_of_Wallet": 0.195},
    {"Product_Line": "Cyber", "Premium": 1_800_000.0, "Share_of_Wallet": 0.30},
]

ANSWER = (
    "Property leads at **$8.2m**, a **19.5%** share of wallet. "
    "Cyber follows at $1.8m."
)


def state(**kwargs) -> dict:
    base = {
        "current_route": "premium",
        "rephrased_user_query": "Zurich premium by product line in Canada, 2024",
        "analyst_evidence": [
            {
                "flow": "gpr",
                "lens": "premium",
                "sql": "SELECT Product_Line, SUM(Premium) AS Premium FROM gpr",
                "rows": ROWS,
            }
        ],
    }
    base.update(kwargs)
    return base


def walk(node):
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)


def text_of(node) -> str:
    out = []
    for n in walk(node):
        children = getattr(n, "children", None)
        if isinstance(children, str):
            out.append(children)
    return " ".join(out)


def classes(node) -> list:
    return [(getattr(n, "className", "") or "") for n in walk(node)]


# ── the figure check ────────────────────────────────────────────────────────


def test_a_scaled_figure_matches_the_raw_value_in_the_row():
    """The writer says "$8.2m"; the row holds 8237411.0. Same claim."""
    checked = fig.check("Property wrote $8.2m.", {"premium": ROWS})
    assert [f.supported for f in checked] == [True]


def test_a_percentage_matches_a_ratio_in_the_row():
    checked = fig.check("A 19.5% share of wallet.", {"premium": ROWS})
    assert [f.supported for f in checked] == [True]


def test_a_figure_the_rows_do_not_contain_is_caught():
    checked = fig.check("Peers average $4.4m.", {"premium": ROWS})
    assert [f.text for f in fig.unsupported(checked)] == ["$4.4m"]


def test_a_year_is_scope_not_a_measure():
    """Years are filters, so they rarely appear as VALUES — checking them is noise."""
    checked = fig.check("Premium in 2024 was $8.2m.", {"premium": ROWS})
    years = [f for f in checked if f.value == "2024"]
    assert years and not years[0].is_checkable
    assert not fig.unsupported(checked)


def test_small_ordinals_are_not_treated_as_measures():
    checked = fig.check("The top 3 lines carry the book.", {"premium": ROWS})
    assert not fig.unsupported(checked)


def test_a_display_string_in_a_row_still_counts_as_evidence():
    rows = [{"Product_Line": "Property", "Premium_Display": "£8.2m"}]
    checked = fig.check("Property wrote £8.2m.", {"premium": rows})
    assert [f.supported for f in checked] == [True]


def test_coverage_counts_only_what_could_be_checked():
    checked = fig.check("In 2024, Property wrote $8.2m and peers $4.4m.", {"premium": ROWS})
    assert fig.coverage(checked) == {"checkable": 2, "supported": 1}


# ── the record ──────────────────────────────────────────────────────────────


def test_an_answer_whose_figures_are_all_present_is_verified():
    prov = pv.build(state(), ANSWER)
    assert prov.state == pv.VERIFIED
    assert prov.row_count == 2


def test_one_invented_figure_makes_it_partly_verified():
    prov = pv.build(state(), ANSWER + " Peers average $4.4m.")
    assert prov.state == pv.PARTIAL
    assert [f.text for f in prov.unsupported] == ["$4.4m"]


def test_an_answer_with_no_evidence_is_not_verified_by_default():
    """"Nothing to check against" and "checked and correct" must not look alike."""
    prov = pv.build({"current_route": "fallback"}, "I can't cover that.")
    assert prov.state == pv.UNVERIFIED


def test_the_record_carries_every_query_that_ran():
    prov = pv.build(state(), ANSWER)
    assert [(q.lens, q.row_count) for q in prov.queries] == [("premium", 2)]
    assert prov.queries[0].columns == ["Product_Line", "Premium", "Share_of_Wallet"]
    assert "SUM(Premium)" in prov.queries[0].sql


def test_the_rails_record_their_queries_too():
    """A deterministic-rail turn has one SQL per lens, not `analyst_evidence`."""
    prov = pv.build(
        {
            "current_route": "premium",
            "gpr_sql_query": "SELECT SUM(Premium) FROM gpr",
            "gpr_query_result": ROWS,
        },
        ANSWER,
    )
    assert [(q.lens, q.row_count) for q in prov.queries] == [("premium", 2)]


def test_the_terms_the_answer_used_arrive_with_their_definitions():
    prov = pv.build(state(), ANSWER)
    labels = [t.label for t in prov.terms]
    assert "Share of wallet" in labels and "Premium" in labels
    wallet = next(t for t in prov.terms if t.label == "Share of wallet")
    assert wallet.definition and wallet.formula


def test_a_term_used_only_in_the_data_is_still_defined():
    """An answer can compute a share of wallet without writing the phrase."""
    prov = pv.build(state(), "Property leads the book.")
    assert "Share of wallet" in [t.label for t in prov.terms]


def test_the_record_survives_the_trip_through_the_store():
    payload = pv.build(state(), ANSWER + " Peers average $4.4m.").as_dict()
    import json

    assert json.loads(json.dumps(payload))["state"] == pv.PARTIAL


# ── the drawer ──────────────────────────────────────────────────────────────


def test_the_drawer_states_the_verification_without_being_opened():
    drawer = provenance_drawer(pv.build(state(), ANSWER).as_dict())
    assert any("prov-badge good" in c for c in classes(drawer))
    assert "Verified against the data" in text_of(drawer)


def test_the_drawer_names_the_figures_it_could_not_find():
    """A panel that only ever says "verified" is decoration."""
    prov = pv.build(state(), ANSWER + " Peers average $4.4m.").as_dict()
    shown = text_of(provenance_drawer(prov))
    assert "Partly verified" in shown
    assert "$4.4m" in shown
    assert "3 of 4 found in the result rows" in shown


def test_the_drawer_shows_the_query_its_rows_and_its_definitions():
    shown = text_of(provenance_drawer(pv.build(state(), ANSWER).as_dict()))
    assert "SUM(Premium)" in shown
    assert "2 rows" in shown
    assert "Where the numbers came from" in shown
    assert "What these terms mean" in shown


def test_the_drawer_is_absent_when_there_is_nothing_to_show():
    assert provenance_drawer(None) is None
    assert provenance_drawer({}) is None


def test_an_answer_renders_its_drawer_between_the_prose_and_the_actions():
    prov = pv.build(state(), ANSWER).as_dict()
    message = ai_message(ANSWER, False, idx=1, provenance=prov)
    rendered = classes(message)
    assert any("prov-drawer" in c for c in rendered)
    assert rendered.index("message gpt-message") < len(rendered)


def test_an_answer_without_provenance_renders_unchanged():
    message = ai_message(ANSWER, False, idx=1)
    assert not any("prov-drawer" in c for c in classes(message))
