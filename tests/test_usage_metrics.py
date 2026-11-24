"""Per-user usage workbooks: row shape, file per user, locked-file recovery, wiring."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

from core.usage_metrics import (
    COLUMNS,
    actor_from_store,
    chat_turn_event,
    format_studio_selection,
    last_question_and_reply,
    make_actor,
    record_usage,
    studio_generate_event,
    tab_visit_event,
    upload_event,
)
from core.usage_metrics import workbook as wb
from ui import usage_tracking


@pytest.fixture
def usage_folder(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("USAGE_METRICS", "on")
    monkeypatch.setenv("USAGE_METRICS_DIR", str(tmp_path))
    return tmp_path


def read_rows(path: Path) -> list[dict]:
    sheet = load_workbook(path)[wb.SHEET]
    header = [cell.value for cell in sheet[1]]
    return [
        dict(zip(header, row)) for row in sheet.iter_rows(min_row=2, values_only=True)
    ]


def record_and_wait(actor, event) -> None:
    future = record_usage(actor, event)
    assert future is not None
    future.result(timeout=30)


# ── pure pieces ───────────────────────────────────────────────────────────────


def test_sso_username_is_the_email():
    actor = make_actor(7, "Jane.Doe@Example.com")
    assert actor.email == "jane.doe@example.com"
    assert actor.file_key == "jane.doe@example.com"


def test_local_username_has_no_email_and_names_the_file():
    actor = actor_from_store({"id": 3, "username": "jash"})
    assert actor is not None
    assert (actor.user_id, actor.email, actor.file_key) == ("3", "", "jash")


def test_no_signed_in_user_records_nothing(usage_folder):
    assert actor_from_store(None) is None
    assert actor_from_store({}) is None
    assert record_usage(None, tab_visit_event("Studio")) is None


def test_studio_selection_keeps_choices_and_drops_plumbing():
    text = format_studio_selection(
        {
            "report": "qbr",
            "filters": {"Country": ["Singapore", "Japan"], "Year": [2025]},
            "peers_by_country": {"SG": ["A", "B"]},
            "audience": "executive",
            "ai": True,
            "template_path": "x.pptx",
            "slides": {"premium": [1]},
            "survey_carrier": None,
            "cuts": [],
        }
    )
    assert text.splitlines() == [
        "Report: qbr",
        "Filters: Country=Singapore, Japan; Year=2025",
        "Peers by country: SG=A, B",
        "Audience: executive",
    ]


def test_question_and_reply_never_borrows_an_older_answer():
    answered = [
        {"type": "HumanMessage", "content": "old q"},
        {"type": "AIMessage", "content": "old a"},
        {"type": "HumanMessage", "content": "new q"},
        {"type": "AIMessage", "content": [{"type": "text", "text": "new a"}]},
    ]
    assert last_question_and_reply(answered) == ("new q", "new a")
    unanswered = answered[:3]
    assert last_question_and_reply(unanswered) == ("new q", "")
    assert last_question_and_reply([]) == ("", "")


def test_unsafe_characters_never_reach_the_filename(tmp_path):
    path = wb.workbook_path(tmp_path, "..\\evil/name:x")
    assert path.parent == tmp_path
    assert path.name == "evil_name_x.xlsx"


# ── writing ───────────────────────────────────────────────────────────────────


def test_each_user_gets_their_own_workbook(usage_folder):
    alice = make_actor(1, "alice@icg.com")
    bob = make_actor(2, "bob@icg.com")
    record_and_wait(alice, tab_visit_event("Studio"))
    record_and_wait(bob, chat_turn_event("What is GWP?", "GWP is $5M.", thread_id="t1"))
    record_and_wait(alice, studio_generate_event({"report": "qbr", "audience": "exec"}))

    assert sorted(p.name for p in usage_folder.glob("*.xlsx")) == [
        "alice@icg.com.xlsx",
        "bob@icg.com.xlsx",
    ]
    alice_rows = read_rows(usage_folder / "alice@icg.com.xlsx")
    assert [r["Action"] for r in alice_rows] == ["Opened tab", "Generate deck"]
    assert alice_rows[1]["Studio selections"] == "Report: qbr\nAudience: exec"
    assert isinstance(alice_rows[0]["Timestamp"], datetime)

    (bob_row,) = read_rows(usage_folder / "bob@icg.com.xlsx")
    assert bob_row["Tab"] == "Ask ICG"
    assert bob_row["Email"] == "bob@icg.com"
    assert (bob_row["Question"], bob_row["Reply"]) == ("What is GWP?", "GWP is $5M.")
    assert bob_row["Notes"] == "conversation t1"


def test_header_matches_columns(usage_folder):
    record_and_wait(make_actor(1, "a@b.com"), tab_visit_event("Recap"))
    sheet = load_workbook(usage_folder / "a@b.com.xlsx")[wb.SHEET]
    assert tuple(cell.value for cell in sheet[1]) == COLUMNS


def test_formula_like_and_control_text_is_stored_as_plain_text(usage_folder):
    question = '=HYPERLINK("http://x")\x07 why?'
    record_and_wait(make_actor(1, "a@b.com"), chat_turn_event(question, "ok"))
    sheet = load_workbook(usage_folder / "a@b.com.xlsx")[wb.SHEET]
    cell = sheet.cell(row=2, column=COLUMNS.index("Question") + 1)
    assert cell.data_type == "s"
    assert cell.value == '=HYPERLINK("http://x") why?'


def test_a_locked_workbook_keeps_rows_pending_until_it_frees(tmp_path, monkeypatch):
    path = tmp_path / "u.xlsx"
    real_write = wb.write_rows

    def locked(*_args, **_kwargs):
        raise PermissionError("open in Excel")

    monkeypatch.setattr(wb, "write_rows", locked)
    actor = make_actor(1, "u")
    with pytest.raises(PermissionError):
        wb.append_rows(path, [tab_visit_event("Studio").as_row(actor)])
    assert wb.pending_path(path).exists()

    monkeypatch.setattr(wb, "write_rows", real_write)
    wb.append_rows(path, [tab_visit_event("MoM").as_row(actor)])
    assert not wb.pending_path(path).exists()
    assert [r["Tab"] for r in read_rows(path)] == ["Studio", "MoM"]
    assert isinstance(read_rows(path)[0]["Timestamp"], datetime)


def test_switched_off_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_METRICS", "off")
    monkeypatch.setenv("USAGE_METRICS_DIR", str(tmp_path))
    assert record_usage(make_actor(1, "a@b.com"), tab_visit_event("Studio")) is None
    assert not list(tmp_path.iterdir())


# ── UI wiring (the callback bodies, called directly) ──────────────────────────


@pytest.fixture
def captured(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(
        usage_tracking,
        "record_usage",
        lambda actor, event: calls.append((actor, event)),
    )
    return calls


def test_tab_visit_uses_the_navbar_label(captured):
    usage_tracking.record_tab_visit("chat", {"id": 4, "username": "x@y.com"})
    actor, event = captured[0]
    assert (actor.email, event.tab, event.action) == (
        "x@y.com",
        "Ask ICG",
        "Opened tab",
    )


def test_recap_upload_lists_the_deck_names(captured):
    files = [
        {"name": "Q3 QBR.pptx", "path": "p1"},
        {"name": "Q2 QBR.pptx", "path": "p2"},
    ]
    usage_tracking.record_recap_upload(files, {"id": 4, "username": "x@y.com"})
    usage_tracking.record_recap_upload([], {"id": 4, "username": "x@y.com"})
    assert len(captured) == 1
    assert captured[0][1].uploaded_files == "Q3 QBR.pptx\nQ2 QBR.pptx"


def test_studio_generate_records_the_selection(captured):
    usage_tracking.record_studio_generate(None, {"id": 1, "username": "a"})
    usage_tracking.record_studio_generate({"report": "qbr"}, {"id": 1, "username": "a"})
    assert [e.studio_selections for _a, e in captured] == ["Report: qbr"]


def test_mom_generate_records_both_uploads(captured):
    usage_tracking.record_mom_generate(
        "job1",
        None,
        {"name": "notes.docx"},
        {"name": "deck.pptx"},
        {"id": 1, "username": "a"},
    )
    usage_tracking.record_mom_generate(None, None, {}, {}, {"id": 1, "username": "a"})
    assert len(captured) == 1
    assert captured[0][1].uploaded_files == "notes.docx\ndeck.pptx"
    assert captured[0][1].action.startswith("Generate (")


def test_upload_event_skips_blank_names():
    assert (
        upload_event("Recap", ["a.pptx", "", "b.pptx"], "x").uploaded_files
        == "a.pptx\nb.pptx"
    )
