"""Which commentary fields the delivered deck populated — recorded at build, shown in Review."""
from __future__ import annotations

import json

from studio.page.authoring.review_report import review_report_view
from studio.review.commentary import field_reason
from studio.review.report import build_review_report
from studio.template_fill import commentary_ledger as L
from studio.template_fill.rewrites import PendingRewrite

PAGES = {
    "overall": L.TemplatePages(titles=("Cover", "Summary", "Spare", "SWOT"),
                               sections=("cover", "summary", "other", "swot"),
                               headers={(1, 5): "Key Messages", (3, 9): "Opportunities"}),
    "product": L.TemplatePages(titles=("Marine Feedback",), sections=("feedback",)),
}


def _outcomes():
    before = [
        {"note:1:5:0": PendingRewrite(draft="rule line", node="key_messages"),
         "note:3:9:0": PendingRewrite(draft="rule line", node="swot-opportunities"),
         "kpi:premium": "$10M"},
        {"fbnote:0:4:p:0": ""},
    ]
    after = [
        {"note:1:5:0": "Model line one\nModel line two", "note:3:9:0": ""},
        {"fbnote:0:4:p:0": ""},
    ]
    return L.ledger(before, after, pages=PAGES,
                    blocks=[("Overall", "overall", (2,)), ("Marine", "product", ())])


def test_every_prose_field_is_recorded_and_nothing_else():
    outcomes = _outcomes()
    assert [o.role for o in outcomes] == ["note:1:5:0", "note:3:9:0", "fbnote:0:4:p:0"]


def test_a_field_is_named_by_the_header_above_it():
    written, opportunities, feedback = _outcomes()
    assert (written.field, opportunities.field, feedback.field) == (
        "Key Messages", "Opportunities", "Commentary")


def test_status_says_written_draft_or_empty():
    before = [{"note:1:5:0": PendingRewrite(draft="rule line", node="n")}]
    same = L.ledger(before, [{"note:1:5:0": "rule line"}], pages=PAGES,
                    blocks=[("Overall", "overall", ())])
    assert same[0].status == L.DRAFT
    written, empty, _ = _outcomes()
    assert (written.status, written.lines, empty.status) == (L.WRITTEN, 2, L.EMPTY)


def test_pages_are_numbered_in_the_merged_deck_skipping_hidden_ones():
    written, opportunities, feedback = _outcomes()
    # overall keeps 3 of 4 pages (page 3 is hidden), so SWOT is merged page 3 and the
    # product block starts on page 4.
    assert (written.slide_no, opportunities.slide_no, feedback.slide_no) == (2, 3, 4)


def test_the_reason_tells_the_three_kinds_of_empty_apart():
    _, dropped, qualitative = _outcomes()
    assert "traced to a fact" in field_reason(dropped)
    assert "written by hand" in field_reason(qualitative)
    nothing = L.FieldOutcome(block="b", template="t", slide_no=1, page="p", field="f",
                             role="note:0:1:0", status=L.EMPTY, had_draft=False)
    assert "nothing to say" in field_reason(nothing)


def test_the_ledger_round_trips_through_the_sidecar(tmp_path):
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"")
    L.write_sidecar(str(deck), _outcomes())
    rows = L.read_sidecar(str(deck))
    assert json.loads(L.sidecar_path(str(deck)).read_text(encoding="utf-8")) == rows
    assert L.from_dicts(rows) == _outcomes()
    assert L.read_sidecar(str(tmp_path / "older.pptx")) is None


def _assembled_doc(rows):
    return {"assembled": True, "n_slides": 4, "manifest": [], "values": {},
            "commentary_fields": rows}


def test_review_lists_the_fields_that_were_not_populated_first():
    from dataclasses import asdict

    report = build_review_report(_assembled_doc([asdict(o) for o in _outcomes()]))
    assert len(report.commentary_fields) == 3
    view = json.dumps(review_report_view(report), default=lambda o: getattr(o, "__dict__", str(o)))
    assert "1 of 3 fields populated" in view
    assert view.index("Not populated (2)") < view.index("Populated fields (1)")
    assert '"qs-rv-open"' in view                    # each row opens its page


def test_a_deck_built_before_the_ledger_says_so_instead_of_claiming_zero():
    report = build_review_report(_assembled_doc(None))
    assert report.commentary_fields is None
    view = json.dumps(review_report_view(report), default=lambda o: getattr(o, "__dict__", str(o)))
    assert "Generate it again" in view


def test_review_opens_the_box_on_the_canvas():
    from studio.authoring.navigation import review_box_key

    assert review_box_key(13, "note:3:9:0") == "13:9"
    assert review_box_key(13, "fbnote:0:4:p:0") == "13:4"
    assert review_box_key(13, "kpi") is None
