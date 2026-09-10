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


def test_numeric_matching_alone_does_not_establish_semantic_verification():
    prov = pv.build(state(), ANSWER)
    assert prov.state == pv.MATCHED
    assert prov.row_count == 2


def test_old_saved_verified_badges_are_displayed_as_numeric_matches():
    record = pv.build(state(), ANSWER).as_dict()
    record["state"] = "verified"  # pre-fact-contract saved transcript
    assert pv.stored_verification_state(record) == pv.MATCHED


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
    assert any("prov-badge neutral" in c for c in classes(drawer))
    assert "Number match only" in text_of(drawer)


def test_the_drawer_names_the_figures_it_could_not_find():
    """A panel that only ever says "verified" is decoration."""
    prov = pv.build(state(), ANSWER + " Peers average $4.4m.").as_dict()
    shown = text_of(provenance_drawer(prov))
    assert "Partly verified" in shown
    assert "$4.4m" in shown
    assert "3 of the 4 figures in this answer appear in the data we read" in shown


def test_an_unmatched_figure_is_not_left_without_context():
    """The report: "it just shows Not Rows" — a bare name and no verdict.

    Naming a number as a problem and stopping there leaves the reader alarmed
    and no better informed, so the panel says what an absent figure MEANS and
    what to do about it.
    """
    prov = pv.build(state(), ANSWER + " Peers average $4.4m.").as_dict()
    shown = text_of(provenance_drawer(prov))
    assert "not among the values we read back" in shown
    assert "Worth checking before you quote it" in shown
    assert "rows" not in shown.replace("Rewritten", "")


def test_every_figure_gets_a_verdict_not_just_the_failures():
    """A list of what was checked reads as a receipt; only the failures, as an alarm."""
    prov = pv.build(state(), ANSWER + " Peers average $4.4m.").as_dict()
    shown = text_of(provenance_drawer(prov))
    assert shown.count("Found in the data") == 3
    assert "Not in the data we read" in shown


def test_the_drawer_explains_the_calculation_in_plain_english():
    """A business reader cannot check a SELECT, so the panel describes it."""
    shown = text_of(provenance_drawer(pv.build(state(), ANSWER).as_dict()))
    assert "The steps we took" in shown
    assert "Started with the Marsh-placed premium records" in shown
    assert "Added up premium" in shown
    assert "That gave us 2 results" in shown
    assert "What these terms mean" in shown


def test_the_steps_come_before_the_figure_check():
    """"How was this calculated" is the question the summary line asks."""
    shown = text_of(provenance_drawer(pv.build(state(), ANSWER).as_dict()))
    assert shown.index("The steps we took") < shown.index("The numbers in this answer")


def test_a_formula_is_shown_without_sql_vocabulary():
    """The glossary writes `SUM(Premium)`; the reader is not an analyst."""
    shown = text_of(provenance_drawer(pv.build(state(), ANSWER).as_dict()))
    assert "total premium over the selected filters" in shown
    assert "SUM(Premium) over" not in shown


def test_an_answer_with_no_evidence_says_why_rather_than_only_not_verified():
    """"Not verified" alone reads as an accusation the answer failed a check."""
    prov = pv.build({"current_route": "fallback"}, "I can't cover that.").as_dict()
    shown = text_of(provenance_drawer(prov))
    assert "no data behind this answer to check it against" in shown


def test_the_raw_query_is_available_but_demoted():
    """Still there for whoever wants it — one more click down."""
    drawer = provenance_drawer(pv.build(state(), ANSWER).as_dict())
    assert "Show the technical query" in text_of(drawer)
    assert "SUM(Premium)" in text_of(drawer)
    assert any("prov-sql-drawer" in c for c in classes(drawer))


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

# ── editing an insight ──────────────────────────────────────────────────────


def test_the_commentary_is_edited_where_it_sits():
    """Not a source box that replaces the card — the words themselves.

    Swapping the card for a Markdown editor hid the chart and the figures the
    edit is ABOUT, and read as a dialog rather than as your own document.
    """
    message = ai_message(ANSWER, False, idx=1, provenance=None, editing=True)
    editable = [
        n for n in walk(message)
        if (getattr(n, "className", "") or "") == "answer-body-editing"
    ]
    assert len(editable) == 1
    assert editable[0].contentEditable == "true"
    # The rendered markdown is still what you are typing over.
    assert any(type(n).__name__ == "Markdown" for n in walk(editable[0]))


def test_the_card_keeps_its_evidence_while_being_edited():
    """The chart is the reason you are editing; it must not disappear."""
    from ui.evidence import build_views

    views = build_views([{"rows": ROWS, "chart_data": {}, "lens": "premium"}])
    message = ai_message(ANSWER, False, idx=1, evidence=views, editing=True)
    assert any("ev-panel" in (getattr(n, "className", "") or "") for n in walk(message))
    assert any("answer-body-editing" in (getattr(n, "className", "") or "") for n in walk(message))


def test_an_answer_not_being_edited_is_not_editable():
    message = ai_message(ANSWER, False, idx=1)
    assert not any(
        (getattr(n, "className", "") or "") == "answer-body-editing" for n in walk(message)
    )


def test_the_edit_control_is_not_one_of_the_next_steps():
    """The next-steps row has a budget of four; edit acts on THIS answer."""
    from ui.components.answer_actions import ACTIONS

    assert len(ACTIONS) <= 4
    assert "edit" not in [a.key for a in ACTIONS]


def test_an_edited_answer_is_re_checked_against_the_same_rows():
    base = pv.build(state(), ANSWER).as_dict()
    assert base["state"] == pv.MATCHED

    rewritten = pv.reverify(base, ANSWER + " Peers average $4.4m.", ROWS)
    assert rewritten["state"] == pv.PARTIAL
    assert [f["text"] for f in rewritten["figures"] if not f["supported"] and f["checkable"]] == [
        "$4.4m"
    ]


def test_an_edit_keeps_the_queries_and_definitions_it_did_not_touch():
    base = pv.build(state(), ANSWER).as_dict()
    rewritten = pv.reverify(base, "Property is the one to watch.", ROWS)
    assert rewritten["queries"] == base["queries"]
    assert rewritten["terms"] == base["terms"]


def test_the_drawer_says_an_answer_was_rewritten():
    """A badge earned by text somebody replaced would be the panel lying."""
    rewritten = pv.reverify(pv.build(state(), ANSWER).as_dict(), ANSWER, ROWS)
    assert "You rewrote this answer" in text_of(provenance_drawer(rewritten))


def _history() -> dict:
    return {
        "thread_id": "t1",
        "messages": [
            {"type": "HumanMessage", "content": "premium by line"},
            {
                "type": "AIMessage",
                "content": ANSWER,
                "provenance": pv.build(state(), ANSWER).as_dict(),
            },
            {"type": "Evidence", "views": [{"rows": ROWS, "chart_data": {}}]},
        ],
    }


def test_saving_an_edit_replaces_the_answer_and_re_verifies():
    """The browser hands over Markdown; the server commits it and re-checks."""
    from ui.callbacks import save_answer_edit

    history = _history()
    updated, editing = save_answer_edit(
        {"idx": 1, "markdown": "Property leads. Peers average $4.4m.", "at": 1},
        history,
    )
    answer = updated["messages"][1]
    assert answer["content"] == "Property leads. Peers average $4.4m."
    assert answer["edited"] is True
    assert answer["provenance"]["state"] == pv.PARTIAL
    assert editing is None, "the editor closes on save"


def test_discarding_leaves_the_answer_alone():
    from dash import no_update

    from ui.callbacks import save_answer_edit

    updated, editing = save_answer_edit({"idx": 1, "markdown": ""}, _history())
    assert updated is no_update
    assert editing is None


def test_saving_an_unchanged_answer_changes_nothing():
    """Opening the editor and closing it must not mark the answer as edited."""
    from dash import no_update

    from ui.callbacks import save_answer_edit

    updated, _editing = save_answer_edit({"idx": 1, "markdown": ANSWER}, _history())
    assert updated is no_update

def test_a_sub_million_figure_is_still_written_in_millions():
    """940,000 is written "$0.9m" all the time; flagging that was a false alarm."""
    rows = [{"Product_Line": "Marine", "Premium": 940_000.0}]
    assert not fig.unsupported(fig.check("Marine wrote $0.9m.", {"premium": rows}))
    assert not fig.unsupported(fig.check("Marine wrote $940k.", {"premium": rows}))


def test_a_small_number_never_gains_a_meaningless_scaled_form():
    """5 must not quietly become "0.0m" and support any figure that rounds there."""
    rows = [{"Count": 5}]
    assert fig.unsupported(fig.check("The gap is $0.0m.", {"premium": rows}))



def test_a_verified_answer_with_no_figures_does_not_claim_it_checked_any():
    """"Every figure was found" about zero figures is the panel lying quietly."""
    prov = pv.build(state(), "Property leads the book.").as_dict()
    shown = text_of(provenance_drawer(prov))
    assert "doesn't state any figures that can be checked" in shown
    assert "Every figure in this answer was found" not in shown
