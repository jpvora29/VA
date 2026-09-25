"""The Decision Board as a review agenda: what is due, what is late, and why.

Every check here is one of the reported defects from the board's own UX review,
pinned so it cannot come back:

  * the one overdue record wore the same ordinary date chip as everything else,
    so urgency was invisible;
  * the archive took a column of width from the work actually in flight;
  * reading a decision opened a drawer over the queue it was launched from, so a
    review was open-read-close-find-your-place, once per record;
  * a status change needed a drag;
  * there was no owner filter and no way to ask "what is due this week";
  * a decision raised from a chat answer arrived with the prose and nothing
    about the scope, the dataset or the figure it was concluded from.

Structural facts, so they are checked against the rendered tree, the store and
the stylesheet rather than by eye.

Run:  pytest tests/test_decision_review_agenda.py -q -o pythonpath=.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from dash.development.base_component import Component

from core.store import decisions as store
from ui.decisions import agenda as ag
from ui.decisions import board, brief, evidence, model, queue, render
from ui.decisions.callbacks import seed_from_answer

TODAY = date(2026, 9, 9)  # a Wednesday, as in the design concept


# ── helpers ──────────────────────────────────────────────────────────────────


def _text(node: Any) -> str:
    """Every string in a rendered tree, flattened."""
    if isinstance(node, str):
        return node
    if isinstance(node, (list, tuple)):
        return " ".join(_text(n) for n in node)
    if isinstance(node, Component):
        return _text(getattr(node, "children", None) or [])
    return ""


def _classes(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, Component):
        out += str(getattr(node, "className", "") or "").split()
        out += _classes(getattr(node, "children", None))
    elif isinstance(node, (list, tuple)):
        for n in node:
            out += _classes(n)
    return out


def _decision(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "x",
        "title": "A decision",
        "statement": "",
        "rationale": "",
        "discussion": "",
        "owner": "",
        "stakeholders": [],
        "status": "planned",
        "priority": "med",
        "decision_date": None,
        "due_date": None,
        "pinned": 0,
        "evidence": [],
        "links": {},
    }
    base.update(over)
    return base


# ── 1. urgency is stated in words, not in colour ─────────────────────────────


@pytest.mark.parametrize(
    "due,expected",
    [
        ("2026-09-08", "1 day overdue"),
        ("2026-09-05", "4 days overdue"),
        ("2026-09-09", "Due today"),
        ("2026-09-10", "Due tomorrow"),
        ("2026-09-12", "in 3 days"),
        (None, "No due date"),
    ],
)
def test_every_due_date_carries_a_sentence(due, expected):
    """"8 Sep" is not urgency — the reader should not have to do the subtraction."""
    assert ag.due_state(due, TODAY).label == expected


def test_a_far_off_date_says_nothing_rather_than_counting_days():
    """"in 87 days" is a number to parse, not a warning."""
    assert ag.due_state("2026-12-05", TODAY).label == ""
    assert ag.due_state("2026-12-05", TODAY).date_text == "5 Dec"


def test_an_unparseable_due_date_is_an_ordinary_no_due_date():
    """A hand-edited row must not throw while the board is being painted."""
    assert ag.due_state("not-a-date", TODAY).tone == ag.NONE


def test_the_overdue_row_says_so_in_text():
    """The reported defect: the overdue record was distinguishable only by hue."""
    row = queue.decision_row(_decision(due_date="2026-09-08"), TODAY, None)
    assert "1 day overdue" in _text(row)


def test_a_row_with_no_owner_says_unassigned_rather_than_nothing():
    assert "Unassigned" in _text(queue.decision_row(_decision(), TODAY, None))


# ── 2. the week ribbon ───────────────────────────────────────────────────────


def test_the_week_is_named_and_spanned_like_the_concept():
    assert ag.week_for(TODAY, 0).label == "This week · 7–13 Sep 2026"
    assert ag.week_for(TODAY, 1).label == "Next week · 14–20 Sep 2026"
    assert ag.week_for(TODAY, -1).label == "Last week · 31 Aug – 6 Sep 2026"


def test_the_ribbon_marks_today_and_counts_what_falls_on_each_day():
    week = ag.week_for(TODAY, 0, [_decision(due_date="2026-09-08"), _decision(due_date="2026-09-08")])
    by_day = {d.number: d for d in week.days}
    assert by_day[9].is_today and not by_day[8].is_today
    assert by_day[8].due_count == 2
    assert by_day[10].due_count == 0


def test_the_ribbons_controls_are_mounted_with_the_page_not_painted_into_it():
    """A callback Input that does not exist yet cannot fire, so the step buttons
    are static and only the label and the day cells are repainted."""
    ids = _ids(render.decision_board_view())
    for control in ("decision-week-prev", "decision-week-next", "decision-week-today",
                    "decision-week-label", "decision-week-days"):
        assert control in ids


def _ids(node: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(node, Component):
        cid = getattr(node, "id", None)
        if isinstance(cid, str):
            out.add(cid)
        out |= _ids(getattr(node, "children", None))
    elif isinstance(node, (list, tuple)):
        for n in node:
            out |= _ids(n)
    return out


# ── 3. the agenda bands ──────────────────────────────────────────────────────


def _sample() -> list[dict[str, Any]]:
    return [
        _decision(id="late", title="Review Cyber retention", due_date="2026-09-08"),
        _decision(id="now", title="Align renewal approach", due_date="2026-09-12"),
        _decision(id="next", title="Prepare peer review", due_date="2026-09-16"),
        _decision(id="far", title="Annual reset", due_date="2026-11-02"),
        _decision(id="none", title="Unscheduled"),
    ]


def test_the_agenda_bands_read_overdue_then_this_week_then_next_week():
    week = ag.week_for(TODAY, 0)
    labels = [g.label for g in ag.agenda_groups(_sample(), TODAY, week)]
    assert labels == ["Overdue", "This week", "Next week", "Later", "No due date"]


def test_an_empty_band_is_not_rendered_as_an_empty_heading():
    week = ag.week_for(TODAY, 0)
    groups = ag.agenda_groups([_decision(due_date="2026-09-08")], TODAY, week)
    assert [g.label for g in groups] == ["Overdue"]


def test_paging_the_ribbon_never_pages_an_overdue_decision_away():
    """Overdue is measured against today, not against the week being browsed: a
    late decision is late whichever week the reader happens to be looking at."""
    week = ag.week_for(TODAY, 3)
    groups = {g.label: g for g in ag.agenda_groups(_sample(), TODAY, week)}
    assert "Overdue" in groups
    assert [d["id"] for d in groups["Overdue"].items] == ["late"]


def test_the_two_named_bands_slide_with_the_ribbon():
    """A week out, "this week" would be a lie, so each band is named for the week
    it actually covers."""
    items = _sample() + [_decision(id="later-still", due_date="2026-09-23")]
    labels = [g.label for g in ag.agenda_groups(items, TODAY, ag.week_for(TODAY, 1))]
    assert labels == ["Overdue", "Next week", "In 2 weeks", "Later", "No due date"]
    assert "This week" not in labels


def test_a_band_lists_its_nearest_deadline_first():
    items = ag.sort_by_due([_decision(id="b", due_date="2026-09-20"),
                            _decision(id="a", due_date="2026-09-11")])
    assert [d["id"] for d in items] == ["a", "b"]


def test_an_undated_decision_sorts_last_rather_than_first():
    items = ag.sort_by_due([_decision(id="none"), _decision(id="dated", due_date="2026-09-11")])
    assert [d["id"] for d in items] == ["dated", "none"]


def test_the_lede_counts_overdue_separately_and_says_nothing_when_there_is_none():
    assert "1 overdue" in _text(render.counts_line(5, 1))
    assert "overdue" not in _text(render.counts_line(5, 0))
    assert "1 active decision" in _text(render.counts_line(1, 0)), "singular"


# ── 4. the archive is a view, not a column ───────────────────────────────────


def test_the_board_columns_are_the_active_statuses_only():
    """Approved is active — agreed is not delivered — but archived is not, and it
    used to take a quarter of the board's width."""
    assert "archived" not in store.ACTIVE_STATUSES
    assert set(store.ACTIVE_STATUSES) == {"planned", "under_review", "approved"}
    painted = render.board_columns(_sample(), TODAY, None)
    assert "Archived" not in _text(painted)


def test_the_archive_link_states_the_count_and_the_way_back():
    assert "Archived (3)" in _text(render.archive_label(False, 3))
    assert "Active decisions" in _text(render.archive_label(True, 3))


def test_the_scope_filter_is_applied_before_an_explicit_status_filter():
    """Otherwise ticking "Archived" in the status dropdown would smuggle the
    archive back into the active queue."""
    items = [_decision(id="a", status="planned"), _decision(id="z", status="archived")]
    assert [d["id"] for d in store.in_scope(items, "active")] == ["a"]
    assert [d["id"] for d in store.in_scope(items, "archived")] == ["z"]
    assert len(store.in_scope(items, "all")) == 2


# ── 5. evidence captured from the answer that raised the decision ────────────


def _answer(**over: Any) -> dict[str, Any]:
    base = {
        "type": "AIMessage",
        "question": "Why did Cyber share of wallet fall?",
        "content": "Cyber's share of this carrier's wallet fell to 7.0% in Q2. "
                   "That is down 1.2 points on Q1.\n\nThe decline is concentrated in two accounts.",
        "route": "premium",
        "ts": "2026-09-09 11:04",
        "scope": [
            {"key": "carrier", "label": "Carrier", "value": "Example Carrier"},
            {"key": "country", "label": "Country", "value": "Canada"},
        ],
        "provenance": {"figures": [
            {"text": "7.0%", "value": "7.0%", "supported": True, "checkable": True}
        ]},
    }
    base.update(over)
    return base


def test_an_answer_hands_over_its_scope_its_source_and_its_checked_figure():
    """The reported defect: a decision raised from an answer carried the prose and
    nothing about what it was concluded from."""
    snap = evidence.snapshot_from_answer(_answer())
    assert snap is not None
    assert snap.value == "7.0%"
    assert snap.label.startswith("Cyber's share")
    assert "Canada" in snap.scope and "Example Carrier" in snap.scope
    assert "2026-09-09" in snap.source


def test_an_unverified_figure_is_not_promoted_to_the_headline_number():
    """The big number on a decision brief reads as settled fact. A figure the
    verifier could not find in the rows is exactly the one that must not."""
    unchecked = _answer(provenance={"figures": [
        {"text": "7.0%", "value": "7.0%", "supported": False, "checkable": True}
    ]})
    assert evidence.snapshot_from_answer(unchecked).value == ""


def test_an_answer_with_nothing_to_offer_produces_no_evidence_block_at_all():
    """A blank card would imply the evidence was lost rather than never captured."""
    assert evidence.snapshot_from_answer({"content": "", "scope": []}) is None
    assert evidence.snapshot_from_answer(None) is None


def test_the_answers_own_sentence_is_not_filed_as_its_evidence():
    """It is already the rationale. Repeating it under an "Evidence" heading
    would dress a restatement up as a source."""
    restatement = {"content": "Cyber grew $4.2M, concentrated in Manufacturing."}
    assert evidence.snapshot_from_answer(restatement) is None
    with_scope = dict(restatement, scope=[{"key": "country", "label": "Country",
                                           "value": "Canada"}])
    assert evidence.snapshot_from_answer(with_scope) is not None


def test_a_legacy_attachment_still_renders_as_the_attachment_it_is():
    """Records written before the snapshot existed hold only {label, url}."""
    items = evidence.snapshots([{"label": "Q2 pack", "url": "https://example.test/q2"}])
    assert [i.label for i in items] == ["Q2 pack"]
    assert "Q2 pack" in _text(brief.evidence_card(items[0]))


def test_the_seed_carries_evidence_but_still_invents_no_owner_or_date():
    seed = seed_from_answer({"messages": [_answer()]}, 0)
    assert seed["title"] == "Why did Cyber share of wallet fall"
    assert seed["evidence"] and seed["evidence"][0]["value"] == "7.0%"
    values = dict(zip(render.FORM_VALUE_ORDER, render.form_values(seed)))
    assert values["owner"] == "" and values["due_date"] == ""


def test_a_stale_index_seeds_a_blank_decision_rather_than_failing():
    assert seed_from_answer({"messages": []}, 4) is None


# ── 6. the brief, read beside the queue ──────────────────────────────────────


def _full_decision() -> dict[str, Any]:
    return _decision(
        id="late",
        title="Review Cyber retention",
        statement="Review the wallet decline and agree a retention response.",
        owner="Priya Shah",
        status="under_review",
        priority="high",
        due_date="2026-09-08",
        evidence=[evidence.snapshot_from_answer(_answer()).as_dict()],
    )


def test_the_brief_states_the_evidence_the_decision_was_taken_on():
    """"Evidence (latest)" would promise the block tracks the dataset. It does not:
    replacing it under an approved decision rewrites the basis it was approved on."""
    text = _text(brief.decision_brief(_full_decision(), [], TODAY))
    assert "Evidence used for this decision" in text
    assert "latest" not in text.lower()


def test_the_brief_states_owner_status_priority_and_how_late_it_is():
    text = _text(brief.decision_brief(_full_decision(), [], TODAY))
    for fact in ("Priya Shah", "Under review", "High priority", "8 Sep", "1 day overdue"):
        assert fact in text, fact


def test_the_brief_keeps_every_field_the_drawer_used_to_show():
    d = _full_decision()
    d.update(rationale="Because the wallet moved.", discussion="Placement to confirm.",
             stakeholders=["Placement"], decision_date="2026-09-02")
    text = _text(brief.decision_brief(d, [{"action": "created", "created_at": "2026-09-01"}], TODAY))
    for field in ("Decision statement", "Business rationale", "Discussion points",
                  "Stakeholders", "Decision date", "Placement", "History (1)"):
        assert field in text, field


def test_the_history_names_the_status_rather_than_printing_its_key():
    revisions = [{"action": "status_changed", "new_value": "under_review", "created_at": "2026-09-03"}]
    assert "Under review" in _text(brief.decision_brief(_full_decision(), revisions, TODAY))


def test_reopen_only_applies_to_an_archived_decision():
    assert brief.reopen_disabled("under_review") is True
    assert brief.reopen_disabled("archived") is False


def test_a_status_change_is_a_labelled_control_not_a_drag():
    """The reported defect: moving a decision meant dragging a card."""
    actions = brief.brief_actions()
    assert "Move to" in _text(actions)
    assert "decision-move" in _ids(actions)


def test_the_brief_is_mounted_beside_the_queue_and_not_over_it():
    """The drawer hid the list it was launched from; the brief is a column."""
    page = render.decision_board_view()
    assert {"decision-board", "decision-brief", "decision-brief-content"} <= _ids(page)
    assert "Offcanvas" not in str(type(page))
    assert "decision-workspace" in _classes(page)


# ── 7. the three views ───────────────────────────────────────────────────────


def test_the_view_switch_states_the_active_view_without_relying_on_colour():
    switch = render.view_switch("agenda")
    pressed = {btn.id["view"]: getattr(btn, "aria-pressed") for btn in switch.children}
    assert pressed == {"board": "false", "list": "false", "agenda": "true"}
    assert [v.key for v in model.VIEWS] == ["board", "list", "agenda"]


def test_switching_view_changes_the_grouping_and_not_the_records():
    agenda = queue.agenda_body(_sample(), TODAY, ag.week_for(TODAY, 0), None)
    flat = queue.list_body(_sample(), TODAY, None)
    for d in _sample():
        assert d["title"] in _text(agenda)
        assert d["title"] in _text(flat)


def test_the_selected_row_is_marked_so_the_queue_says_what_the_brief_is_showing():
    row = queue.decision_row(_decision(id="late"), TODAY, "late")
    assert "decision-row-selected" in _classes(row)


def test_an_empty_queue_says_what_to_do_about_it():
    assert "Create decision" in _text(queue.empty_queue())


# ── 8. persistence: the filters the review actually uses ─────────────────────


SCRATCH_UID = 987654321  # no real account has this id


@pytest.fixture
def scratch_board():
    """A disposable board for one test; every row it creates is deleted after."""
    yield SCRATCH_UID
    for d in store.list_decisions(SCRATCH_UID, scope="all"):
        store.delete_decision(SCRATCH_UID, d["id"])


def test_the_store_filters_by_owner_and_defaults_to_the_active_queue(scratch_board):
    store.create_decision(scratch_board, {"title": "Mine", "owner": "Priya Shah"})
    store.create_decision(scratch_board, {"title": "Theirs", "owner": "Jordan Ellis"})
    store.create_decision(scratch_board, {"title": "Done", "owner": "Priya Shah",
                                          "status": "archived"})

    active = store.list_decisions(scratch_board)
    assert sorted(d["title"] for d in active) == ["Mine", "Theirs"]

    mine = store.list_decisions(scratch_board, owners=["priya shah"])
    assert [d["title"] for d in mine] == ["Mine"], "owner matching ignores case"

    assert [d["title"] for d in store.list_decisions(scratch_board, scope="archived")] == ["Done"]
    assert store.count_by_scope(scratch_board) == {"active": 2, "archived": 1}
    assert store.list_owners(scratch_board) == ["Jordan Ellis", "Priya Shah"]


def test_moving_a_decision_writes_through_the_audited_path(scratch_board):
    """The Move-to control must leave the same trail a drag used to."""
    did = store.create_decision(scratch_board, {"title": "Move me", "status": "planned"})
    store.change_status(scratch_board, did, "approved")
    actions = [r["action"] for r in store.list_revisions(scratch_board, did)]
    assert "status_changed" in actions


# ── 9. end to end: a chat answer becomes a record on the agenda ──────────────


def test_an_answer_becomes_a_dated_decision_the_board_bands_as_overdue(scratch_board):
    """The whole handoff, in the order the user performs it:

        chat answer -> Create decision -> seeded draft -> saved record
                    -> board request  -> agenda band   -> brief with evidence
    """
    seed = seed_from_answer({"messages": [_answer()]}, 0)
    assert seed is not None

    did = store.create_decision(
        scratch_board,
        {**seed, "owner": "Priya Shah", "status": "under_review",
         "priority": "high", "due_date": "2026-09-08"},
    )
    assert did

    request = board.build_board_request(
        user_id=scratch_board, view="agenda", scope="active", week_offset=0,
        selected=did, search="", statuses=None, priorities=None, owners=None,
        sort="due", today=TODAY,
    )
    view = board.build_board_view(request)

    queue_text = _text(view.queue)
    assert "OVERDUE" in queue_text.upper()
    assert "1 day overdue" in queue_text
    assert "Priya Shah" in queue_text
    assert "1 overdue" in _text(view.counts)
    assert view.week_label == "This week · 7–13 Sep 2026"
    assert view.ribbon_class == "decision-ribbon"

    saved = store.get_decision(scratch_board, did)
    panel = _text(brief.decision_brief(saved, store.list_revisions(scratch_board, did), TODAY))
    assert "7.0%" in panel, "the figure the decision was taken on survived the round trip"
    assert "Canada" in panel, "and so did the scope it was measured under"


def test_the_archive_view_shows_the_archive_and_the_queue_does_not(scratch_board):
    store.create_decision(scratch_board, {"title": "Live one"})
    store.create_decision(scratch_board, {"title": "Old one", "status": "archived"})
    common = dict(user_id=scratch_board, view="list", week_offset=0, selected=None,
                  search="", statuses=None, priorities=None, owners=None,
                  sort="due", today=TODAY)

    active = board.build_board_view(board.build_board_request(scope="active", **common))
    assert "Live one" in _text(active.queue) and "Old one" not in _text(active.queue)
    assert "Archived (1)" in _text(active.archive)

    archived = board.build_board_view(board.build_board_request(scope="archived", **common))
    assert "Old one" in _text(archived.queue) and "Live one" not in _text(archived.queue)
    assert "Active decisions" in _text(archived.archive)


def test_a_filter_that_matches_nothing_says_so_rather_than_rendering_blank(scratch_board):
    store.create_decision(scratch_board, {"title": "Live one"})
    view = board.build_board_view(board.build_board_request(
        user_id=scratch_board, view="agenda", scope="active", week_offset=0,
        selected=None, search="nothing matches this", statuses=None, priorities=None,
        owners=None, sort="due", today=TODAY,
    ))
    assert "No decisions match this view." in _text(view.queue)


# ── 10. the stylesheet ───────────────────────────────────────────────────────


DECISION_CSS = Path("assets/va_decision_board.css").read_text(encoding="utf-8")


def test_the_board_owns_one_stylesheet_that_sorts_before_the_shell():
    """Dash serves /assets alphabetically; a sheet sorting after va_shell.css
    would take the chrome back (see tests/test_app_shell.py)."""
    assert "va_decision_board.css" < "va_shell.css"
    style = Path("assets/style.css").read_text(encoding="utf-8")
    stray = [l for l in style.splitlines() if l.strip().startswith(".decision-")]
    assert not stray, f"decision rules left behind in style.css: {stray[:3]}"


def test_the_row_template_is_declared_once_so_header_and_rows_cannot_drift():
    assert "--decision-row-cols:" in DECISION_CSS
    assert DECISION_CSS.count("grid-template-columns: var(--decision-row-cols)") == 1


def test_the_board_styles_from_tokens_rather_than_brand_hexes():
    """Brand colour lives in assets/theme_tokens.css; a hex here would fork it."""
    import re

    body = "\n".join(
        l for l in DECISION_CSS.splitlines() if not l.strip().startswith(("/*", "*", "//"))
    )
    for brand in ("#000F47", "#000f47", "#0b4bff", "#0B4BFF", "#c53532"):
        assert brand not in body, f"{brand} is a token, not a literal"
    assert re.search(r"var\(--va-navy\)", body)


def test_the_brief_folds_under_the_queue_rather_than_squeezing_it_on_narrow_screens():
    assert "@media (max-width: 1180px)" in DECISION_CSS
    assert "@media (max-width: 880px)" in DECISION_CSS
