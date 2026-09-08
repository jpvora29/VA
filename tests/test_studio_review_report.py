"""Review: why the deck is not finished, in terms an author can act on.

The old Review tab listed validation errors. It could tell you that ten boxes were
blank; it could not tell you that all ten were blank for ONE reason, that the reason was
"this scope has no prior year", or that the same fact is why the commentary reads thin.
That is what these tests pin down:

  * every unfilled slot is attributed to a cause, and causes that share a fact are ONE
    row rather than ten;
  * the attribution is the right one when two capabilities could claim the same role;
  * a capability the template never uses is reported without being alarmed about;
  * an unwritten commentary box is an ERROR, because the box then ships the template's
    example prose about a different carrier;
  * the report describes the document on screen — no engine, no LLM, no re-run.
"""
from __future__ import annotations

import pytest

from studio.review import build_review_report
from studio.review import causes as K
from studio.review.capability import cause_for_role, probe
from studio.review.commentary import lost_claim_families


# ── documents ────────────────────────────────────────────────────────────────


def _slot(slide, shape, token, kind, context, role, where=None):
    return {
        "slot": {
            "slide_idx": slide, "shape_id": shape, "where": where or ["para", 0],
            "token": token, "value_kind": kind, "context": context,
        },
        "role": role,
        "placeholder": role is None,
    }


def _doc(values, manifest, *, hidden=(), overrides=None, n_slides=6):
    return {
        "template_path": "x.pptx", "width_emu": 1, "height_emu": 1, "n_slides": n_slides,
        "manifest": list(manifest), "values": dict(values),
        "overrides": dict(overrides or {}), "map_overrides": {}, "added": {},
        "hidden": list(hidden), "order": list(range(n_slides)),
    }


#: A run with a current year and no prior one — the commonest real gap.
def _no_prior_year_doc():
    return _doc(
        {"subject_name": "AIG", "period_year": 2024, "carrier_gwp": 120.0,
         "marsh_gwp": 900.0, "rank": 3, "sow_pct": 12.5, "peer_gwp": 80.0,
         "spotlight_name": "Spain", "country_name[0]": "Spain"},
        [
            _slot(0, 1, "$xxM", "money", "Carrier premium with Marsh", "carrier_gwp"),
            _slot(0, 2, "xx.x%", "pct", "YoY change premium with Marsh", "carrier_gwp_yoy"),
            _slot(1, 3, "xx.x%", "pct", "Marsh GWP YoY", "marsh_gwp_yoy"),
            _slot(1, 4, "x", "rank", "PY overall rank", "rank_yoy"),
            _slot(2, 5, "xx.x%", "pct", "Peer SoW YoY", "peer_sow_yoy"),
        ],
    )


# ── grouping: many blanks, one fact ──────────────────────────────────────────


def test_every_year_on_year_blank_is_one_row_not_five():
    """The whole point of the rewrite: ten blanks with one cause read as one finding."""
    report = build_review_report(_no_prior_year_doc())

    [group] = [g for g in report.groups if g.cause.id == K.NO_PRIOR_YEAR]
    assert group.count == 4
    assert group.slides() == (1, 2, 3)          # 1-based, the numbers on screen
    assert report.slots_open == 4


def test_the_reason_names_the_mechanism_and_the_fix():
    """"Unfilled" is not a reason. The author needs what was tried and what to change."""
    report = build_review_report(_no_prior_year_doc())
    [group] = [g for g in report.groups if g.cause.id == K.NO_PRIOR_YEAR]

    assert "prior year" in group.cause.why.lower()
    assert group.cause.fix, "a data gap the author can widen must say so"
    assert group.cause.severity == "warn", "a real data gap is not a bug"


def test_the_filled_values_are_not_reported_as_problems():
    report = build_review_report(_no_prior_year_doc())
    assert report.slots_filled == 1              # carrier_gwp resolved
    assert all(f.role != "carrier_gwp" for g in report.groups for f in g.findings)


# ── attribution when two capabilities could claim the same role ──────────────


def test_a_peer_yoy_blames_the_peers_when_there_are_no_peers_at_all():
    """`peer_gwp_yoy` belongs to both families. With no peer benchmark, widening the
    period would not help — so the peer gap has to win."""
    values = {"period_year": 2024, "carrier_gwp": 1.0}
    caps = probe(values)
    assert cause_for_role("peer_gwp_yoy", caps) == K.NO_PEER_BENCHMARK


def test_a_peer_yoy_blames_the_period_once_the_peers_resolve():
    values = {"period_year": 2024, "carrier_gwp": 1.0, "peer_gwp": 50.0}
    caps = probe(values)
    assert cause_for_role("peer_gwp_yoy", caps) == K.NO_PRIOR_YEAR


def test_with_no_year_at_all_one_cause_owns_everything():
    """Nothing resolves without a reporting year, so reporting a dozen separate gaps
    would bury the single fact that fixes them all."""
    report = build_review_report(_doc(
        {"subject_name": "AIG"},
        [_slot(0, 1, "$xxM", "money", "Carrier premium", "carrier_gwp"),
         _slot(0, 2, "xx.x%", "pct", "Peer SoW", "peer_sow"),
         _slot(1, 3, "x", "rank", "Overall rank", "rank")],
    ))
    assert [g.cause.id for g in report.groups] == [K.NO_REPORTING_YEAR]
    assert report.groups[0].count == 3
    assert report.groups[0].cause.severity == "error"


def test_an_indexed_country_role_is_attributed_to_the_country_breakdown():
    caps = probe({"period_year": 2024})
    assert cause_for_role("country_name[2]", caps) == K.NO_COUNTRY_BREAKDOWN


# ── unmapped: the template never said what belongs in the box ────────────────


def test_an_unmapped_figure_is_a_different_finding_from_an_unresolved_one():
    """Two blanks, two fixes: one wants a label in the template, the other wants a
    different selection. One "unfilled" bucket hid that."""
    report = build_review_report(_doc(
        {"subject_name": "AIG", "period_year": 2024, "carrier_gwp": 1.0},
        [_slot(0, 1, "xx.x", "int", "some unlabelled heading", None),
         _slot(0, 2, "xx.x%", "pct", "YoY change", "carrier_gwp_yoy")],
    ))
    kinds = {g.cause.id for g in report.groups}
    assert kinds == {K.UNMAPPED_FIGURE, K.NO_PRIOR_YEAR}


def test_an_unmapped_slot_keeps_the_words_the_mapper_had_to_work_with():
    """For an unmapped slot those words ARE the finding — they are the thing to change."""
    report = build_review_report(_doc(
        {"period_year": 2024},
        [_slot(0, 1, "xx.x", "int", "Total for the quarter", None)],
    ))
    [finding] = report.groups[0].findings
    assert finding.context == "Total for the quarter"
    assert finding.token == "xx.x"


def test_unmapped_text_and_unmapped_charts_are_not_figure_gaps():
    report = build_review_report(_doc(
        {"period_year": 2024},
        [_slot(0, 1, "Carrier", "text", "", None),
         _slot(0, 2, "", "series", "", None, where=["chart"])],
    ))
    assert {g.cause.id for g in report.groups} == {K.UNMAPPED_TEXT, K.UNMAPPED_CHART}
    # A chart the engine was never meant to drive has no fix, and says so.
    [chart] = [g for g in report.groups if g.cause.id == K.UNMAPPED_CHART]
    assert chart.cause.fix == ""


# ── edits and stale placeholders are errors, not data gaps ───────────────────


def test_a_cleared_value_is_an_error_the_author_can_undo():
    key = "0:1:para-0"
    report = build_review_report(_doc(
        {"period_year": 2024, "carrier_gwp": 120.0},
        [_slot(0, 1, "$xxM", "money", "Carrier premium", "carrier_gwp")],
        overrides={key: "   "},
    ))
    assert [g.cause.id for g in report.groups] == [K.BLANKED]
    assert report.errors()


def test_a_surviving_placeholder_token_is_an_error():
    """The failure mode the whole layer exists to prevent: a client-visible 'xx.x'."""
    key = "0:1:para-0"
    report = build_review_report(_doc(
        {"period_year": 2024},
        [_slot(0, 1, "$xxM", "money", "Carrier premium", "carrier_gwp")],
        overrides={key: "xx.x"},
    ))
    assert [g.cause.id for g in report.groups] == [K.STALE]


def test_errors_are_listed_before_data_gaps():
    report = build_review_report(_doc(
        {"period_year": 2024, "carrier_gwp": 1.0},
        [_slot(0, 1, "xx.x%", "pct", "YoY change", "carrier_gwp_yoy"),
         _slot(0, 2, "$xxM", "money", "Carrier premium", "carrier_gwp")],
        overrides={"0:2:para-0": "xx.x"},
    ))
    assert [g.cause.id for g in report.groups] == [K.STALE, K.NO_PRIOR_YEAR]


# ── hidden pages ─────────────────────────────────────────────────────────────


def test_a_page_the_deck_does_not_ship_is_not_a_reason_to_hold_it_back():
    report = build_review_report(_doc(
        {"period_year": 2024, "carrier_gwp": 1.0},
        [_slot(0, 1, "$xxM", "money", "Carrier premium", "carrier_gwp"),
         _slot(3, 9, "xx.x%", "pct", "YoY change", "carrier_gwp_yoy")],
        hidden=[3],
    ))
    assert report.clean
    assert report.coverage_pct() == 100, "coverage counts only the pages that ship"


# ── capabilities ─────────────────────────────────────────────────────────────


def test_a_capability_this_template_never_uses_is_not_a_gap():
    """A premium-only run is not a broken deck when the template has no survey tile."""
    report = build_review_report(_no_prior_year_doc())
    missing = {c.id for c in report.missing_capabilities()}
    blocking = {c.id for c in report.blocking_capabilities()}

    assert "survey_score" in missing, "the absence is still reported as context"
    assert "survey_score" not in blocking, "…but it costs this deck nothing"
    assert "prior_year" in blocking


def test_the_year_travels_into_the_explanation():
    """"No rows for the prior year" is guesswork; "no rows for 2023" is a fact to check."""
    report = build_review_report(_no_prior_year_doc())
    [prior] = [c for c in report.capabilities if c.id == "prior_year"]
    assert "2023" in prior.detail


# ── commentary ───────────────────────────────────────────────────────────────


def _commentary_doc(*, written: bool):
    values = {"period_year": 2024, "carrier_gwp": 1.0}
    if written:
        values["note:2:7:0"] = "The book grew. It grew in Spain."
    return _doc(values, [_slot(2, 7, "…", "text", "", "note:2:7:0")])


def test_an_unwritten_commentary_box_is_an_error_not_a_blank():
    """Prose boxes are replaced wholesale, so an unwritten one still carries the
    template's example commentary — about a different carrier."""
    report = build_review_report(_commentary_doc(written=False))
    assert [g.cause.id for g in report.groups] == [K.COMMENTARY_EMPTY]
    assert report.groups[0].cause.severity == "error"
    assert report.commentary_written() == 0


def test_a_written_commentary_box_counts_its_lines():
    report = build_review_report(_commentary_doc(written=True))
    assert report.clean
    [box] = report.commentary
    assert box.filled and box.lines == 1


def test_commentary_boxes_are_never_reported_as_unmapped_figures():
    """They are diagnosed on their own terms; 'this column has no prose' is not
    'this cell has no number'."""
    report = build_review_report(_commentary_doc(written=True))
    assert all(not str(f.role or "").startswith("note:")
               for g in report.groups for f in g.findings)


def test_the_commentary_reports_what_it_could_not_argue():
    """The answer to "why does the commentary read thin?" — it is the same fact that
    left the figures blank, not a lazy writer."""
    lost = lost_claim_families(probe({"period_year": 2024, "carrier_gwp": 1.0}))
    assert any("year-on-year" in family for family in lost)
    assert any("peer" in family for family in lost)


def test_a_run_with_everything_loses_no_claim_family():
    complete = {
        "period_year": 2024, "carrier_gwp": 1.0, "carrier_gwp_yoy": 2.0,
        "peer_gwp": 1.0, "rank": 2, "survey_score": 7.1, "spotlight_name": "Spain",
        "country_name[0]": "Spain",
    }
    assert lost_claim_families(probe(complete)) == ()


# ── the report is a description, not a re-run ────────────────────────────────


def test_the_report_is_pure_over_the_document_on_screen():
    """It is recomputed on every render, so it must not touch an engine or a model —
    and it must never describe a different deck from the one being previewed."""
    doc = _no_prior_year_doc()
    before = repr(doc)
    first = build_review_report(doc)
    second = build_review_report(doc)

    assert repr(doc) == before, "the report must not mutate the document"
    assert [g.cause.id for g in first.groups] == [g.cause.id for g in second.groups]
    assert first.coverage_pct() == second.coverage_pct()


def test_no_document_yet_is_an_empty_report_not_a_crash():
    for empty in (None, {}):
        report = build_review_report(empty)
        assert report.clean and report.slots_total == 0 and report.coverage_pct() == 0


@pytest.mark.parametrize("cause_id", sorted(K.CAUSES))
def test_every_cause_explains_itself(cause_id):
    """A cause with no mechanism is the old Review tab with extra steps."""
    cause = K.CAUSES[cause_id]
    assert cause.title and cause.why
    assert len(cause.why.split()) >= 12, f"{cause_id} does not explain anything"
    assert cause.severity in {"warn", "error"}


# ── the page renders it ──────────────────────────────────────────────────────


def test_the_review_tab_shows_the_reasons_and_still_offers_export():
    from studio.page.template_preview import template_review_body

    body = str(template_review_body(_no_prior_year_doc()))
    assert "No prior year in scope" in body
    assert "qs-export" in body, "Export is not gated on the report; it is described by it"
    assert "qs-tf-autofix" in body, "the repairable checks keep their buttons"


# ── the assembled deck: the file the author is actually about to send ────────
#
# Studio holds two documents and they are not the same thing. The editable template doc
# is a PLAN — every slot with the value it resolved to — so coverage is a real
# percentage. The assembled deck is the OUTCOME: overall plus a sub-deck per product and
# per country, already written into one .pptx. Nothing in it is a plan any more, and the
# old Review tab described it as "0 filled · 0 mapped · no validation errors" — a clean
# bill of health for a deck it had not looked at.


def _assembled_doc(manifest, values=None, **kw):
    return _doc(values or {"subject_name": "AIG", "period_year": 2024, "carrier_gwp": 1.0},
                manifest, **kw) | {"assembled": True}


def test_the_assembled_deck_reports_what_is_still_a_placeholder():
    """Slot detection over the DELIVERED file finds only the boxes that stayed a
    placeholder — anything that filled is a number by then and is not a slot at all."""
    report = build_review_report(_assembled_doc([
        _slot(2, 1, "xx.x%", "pct", "YoY change premium", "carrier_gwp_yoy"),
        _slot(4, 2, "xx.x%", "pct", "YoY change premium", "carrier_gwp_yoy"),
    ]))
    assert report.source == "assembled"
    assert [g.cause.id for g in report.groups] == [K.NO_PRIOR_YEAR]
    assert report.groups[0].count == 2
    assert report.slots_open == 2


def test_the_assembled_deck_does_not_pretend_to_measure_coverage():
    """There is no denominator: what filled is a number in a file, not a slot. A "%
    filled" computed from the leftovers alone would read 0% on a finished deck."""
    report = build_review_report(_assembled_doc([
        _slot(2, 1, "xx.x%", "pct", "YoY change", "carrier_gwp_yoy"),
    ]))
    assert report.measures_coverage is False


def test_a_clean_assembled_deck_says_so():
    report = build_review_report(_assembled_doc([]))
    assert report.clean and report.slots_open == 0


def test_a_surviving_ellipsis_is_an_unwritten_commentary_box():
    """The most dangerous thing in a delivered deck: prose boxes are replaced wholesale,
    so one still showing its "fill me" mark is shipping the template's example narrative
    about a different carrier."""
    report = build_review_report(_assembled_doc([
        _slot(5, 3, "………", "text", "", None),
    ]))
    assert [g.cause.id for g in report.groups] == [K.COMMENTARY_EMPTY]
    assert report.groups[0].cause.severity == "error"
    assert [c.slide_no for c in report.commentary] == [6]
    assert report.commentary_written() == 0


def test_the_assembled_deck_still_explains_what_the_commentary_could_not_argue():
    """The capabilities come from the run's resolved values, so this half of the answer
    is the same whichever document is being described."""
    report = build_review_report(_assembled_doc([]))
    lost = lost_claim_families(report.capabilities)
    assert any("year-on-year" in family for family in lost)


def test_the_assembled_review_renders_with_no_denominator():
    from studio.page.authoring.review_report import review_report_view

    body = str(review_report_view(build_review_report(_assembled_doc([
        _slot(2, 1, "xx.x%", "pct", "YoY change", "carrier_gwp_yoy"),
    ]))))
    assert "placeholder" in body
    assert "% of values filled" not in body, "a percentage here would be meaningless"


def test_the_generator_hands_review_the_leftovers_and_the_run_s_values():
    """Both halves have to travel on the assembled doc, or Review is describing a deck
    it cannot see. The preview and the fill engine ignore them — this document is
    already filled."""
    import inspect

    from studio.authoring import generate as G

    src = inspect.getsource(G._assembled_review)
    assert "detect(analyze(path))" in src, "the leftovers come from the DELIVERED file"
    assert "resolve_roles" in src, "the reasons come from the run's resolved roles"
    # Best-effort: a description that cannot be computed must not cost anybody the deck.
    assert src.count("except Exception") == 2


def test_a_chart_in_a_delivered_deck_is_only_reported_when_its_data_is_missing():
    """"A placeholder survived" does not hold for charts: a chart is detected because it
    is a chart, filled or not. Measured on a real deck, reporting them anyway listed the
    two growth quadrants of a finished deck as open items."""
    good = build_review_report(_assembled_doc(
        [_slot(5, 1, "BUBBLE (15)", "series", "growth rates", "growth_bubble", where=["chart"])],
        {"period_year": 2024, "carrier_gwp": 1.0, "carrier_gwp_yoy": 2.0,
         "growth_bubble": {"points": [{"x": 1, "y": 2}]}},
    ))
    assert good.clean, "a chart whose series resolved is not an open item"

    broken = build_review_report(_assembled_doc(
        [_slot(5, 1, "BUBBLE (15)", "series", "growth rates", "growth_bubble", where=["chart"])],
        {"period_year": 2024, "carrier_gwp": 1.0, "carrier_gwp_yoy": 2.0,
         "growth_bubble": {"points": []}},
    ))
    assert [g.cause.id for g in broken.groups] == [K.NO_CHART_SERIES]
