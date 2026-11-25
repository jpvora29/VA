"""Per-user usage workbooks: machine identity, one sheet per workspace, wiring."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

from core.usage_metrics import (
    ASK_ICG,
    MOM,
    RECAP,
    SHEET_COLUMNS,
    STUDIO,
    TAB_VISITS,
    UsageActor,
    chat_turn_event,
    identity,
    last_question_and_reply,
    mom_generate_event,
    recap_upload_event,
    record_usage,
    sheet_columns,
    studio_columns,
    studio_generate_event,
    tab_visit_event,
)
from core.usage_metrics import workbook as wb
from ui import usage_tracking

ALICE = UsageActor(user_id="alice01", email="alice@icg.com")
BOB = UsageActor(user_id="bob02", email="bob@icg.com")


@pytest.fixture
def usage_folder(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("USAGE_METRICS", "on")
    monkeypatch.setenv("USAGE_METRICS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def machine(monkeypatch):
    """Pretend the machine login is ``jdoe`` with the given (default: no) email."""

    def set_machine(email: str = "") -> None:
        monkeypatch.setattr(identity, "system_user_id", lambda: "jdoe")
        monkeypatch.setattr(identity, "system_email", lambda: email)

    set_machine()
    return set_machine


def read_sheet(path: Path, sheet: str) -> list[dict]:
    rows = load_workbook(path)[sheet]
    header = [cell.value for cell in rows[1]]
    return [
        dict(zip(header, row)) for row in rows.iter_rows(min_row=2, values_only=True)
    ]


def record_and_wait(actor, event) -> None:
    future = record_usage(actor, event)
    assert future is not None
    future.result(timeout=30)


# ── identity ──────────────────────────────────────────────────────────────────


def test_user_id_is_the_machine_login_not_the_app_id(machine):
    machine("j.doe@icg.com")
    actor = identity.actor_for_store({"id": 3, "username": "someone-else"})
    assert actor == UsageActor(user_id="jdoe", email="j.doe@icg.com")


def test_app_sso_email_fills_in_when_the_machine_has_none(machine):
    actor = identity.actor_for_store({"id": 3, "username": "J.Doe@ICG.com"})
    assert actor == UsageActor(user_id="jdoe", email="j.doe@icg.com")


def test_machine_email_wins_over_the_app_username(machine):
    machine("real@icg.com")
    assert identity.current_actor("other@icg.com").email == "real@icg.com"


def test_no_signed_in_user_records_nothing(machine, usage_folder):
    assert identity.actor_for_store(None) is None
    assert identity.actor_for_store({}) is None
    assert identity.actor_for_app_user(None) is None
    assert record_usage(None, tab_visit_event("Studio")) is None


def test_real_machine_lookups_return_strings():
    assert isinstance(identity.system_user_id(), str)
    assert identity.system_user_id()
    email = identity.system_email()
    assert email == "" or "@" in email


# ── pure pieces ───────────────────────────────────────────────────────────────


def test_studio_selection_spreads_over_its_columns():
    columns = studio_columns(
        {
            "report": "qbr",
            "filters": {"Country": ["Singapore", "Japan"], "Year": [2025]},
            "peers_by_country": {"SG": ["A", "B"]},
            "audience": "executive",
            "date_from": "2025-01-01",
            "date_to": "2025-09-30",
            "brand_new_control": "x",
            "ai": True,
            "template_path": "x.pptx",
            "survey_carrier": None,
        }
    )
    assert columns["Deliverable"] == "qbr"
    assert columns["Filters"] == "Country=Singapore, Japan; Year=2025"
    assert columns["Peers by country"] == "SG=A, B"
    assert columns["Audience"] == "executive"
    assert columns["Period"] == "calendar: 2025-01-01 to 2025-09-30"
    assert columns["Other selections"] == "Brand new control: x"
    assert "Survey carrier" not in columns


def test_every_event_fits_its_sheet():
    events = [
        studio_generate_event({"report": "qbr"}),
        recap_upload_event(["a.pptx"]),
        mom_generate_event("Client meeting", "n.docx", "d.pptx"),
        chat_turn_event("q", "a"),
        tab_visit_event("Studio"),
    ]
    assert [e.sheet for e in events] == [STUDIO, RECAP, MOM, ASK_ICG, TAB_VISITS]
    for event in events:
        assert len(event.as_row(ALICE)) == len(sheet_columns(event.sheet))
        assert set(event.values) <= set(SHEET_COLUMNS[event.sheet])


def test_question_and_reply_never_borrows_an_older_answer():
    answered = [
        {"type": "HumanMessage", "content": "old q"},
        {"type": "AIMessage", "content": "old a"},
        {"type": "HumanMessage", "content": "new q"},
        {"type": "AIMessage", "content": [{"type": "text", "text": "new a"}]},
    ]
    assert last_question_and_reply(answered) == ("new q", "new a")
    assert last_question_and_reply(answered[:3]) == ("new q", "")
    assert last_question_and_reply([]) == ("", "")


def test_filename_is_the_user_id_and_never_a_path(tmp_path):
    assert wb.workbook_path(tmp_path, "jdoe").name == "jdoe.xlsx"
    path = wb.workbook_path(tmp_path, "..\\CORP\\jdoe")
    assert path.parent == tmp_path
    assert path.name == "CORP_jdoe.xlsx"


# ── writing ───────────────────────────────────────────────────────────────────


def test_workbook_has_one_sheet_per_workspace(usage_folder):
    record_and_wait(ALICE, tab_visit_event("Recap"))
    book = load_workbook(usage_folder / "alice01.xlsx")
    assert book.sheetnames == [STUDIO, RECAP, MOM, ASK_ICG, TAB_VISITS]
    for name in book.sheetnames:
        assert tuple(cell.value for cell in book[name][1]) == sheet_columns(name)


def test_rows_land_on_their_sheet_in_their_users_file(usage_folder):
    record_and_wait(ALICE, studio_generate_event({"report": "qbr", "audience": "exec"}))
    record_and_wait(ALICE, recap_upload_event(["Q3 QBR.pptx", "Q2 QBR.pptx"]))
    record_and_wait(BOB, chat_turn_event("What is GWP?", "$5M.", thread_id="t1"))
    record_and_wait(ALICE, mom_generate_event("Client meeting", "n.docx", "d.pptx"))

    assert sorted(p.name for p in usage_folder.glob("*.xlsx")) == [
        "alice01.xlsx",
        "bob02.xlsx",
    ]
    alice = usage_folder / "alice01.xlsx"
    (studio,) = read_sheet(alice, STUDIO)
    assert (studio["User ID"], studio["Email"]) == ("alice01", "alice@icg.com")
    assert (studio["Deliverable"], studio["Audience"]) == ("qbr", "exec")
    assert isinstance(studio["Timestamp"], datetime)
    (recap,) = read_sheet(alice, RECAP)
    assert (recap["Uploaded files"], recap["File count"]) == (
        "Q3 QBR.pptx\nQ2 QBR.pptx",
        2,
    )
    (mom,) = read_sheet(alice, MOM)
    assert (mom["Note file"], mom["Deck file"]) == ("n.docx", "d.pptx")
    assert read_sheet(alice, ASK_ICG) == []

    (chat,) = read_sheet(usage_folder / "bob02.xlsx", ASK_ICG)
    assert (chat["Question"], chat["Reply"], chat["Conversation"]) == (
        "What is GWP?",
        "$5M.",
        "t1",
    )


def test_formula_like_and_control_text_is_stored_as_plain_text(usage_folder):
    question = '=HYPERLINK("http://x")\x07 why?'
    record_and_wait(ALICE, chat_turn_event(question, "ok"))
    sheet = load_workbook(usage_folder / "alice01.xlsx")[ASK_ICG]
    cell = sheet.cell(row=2, column=sheet_columns(ASK_ICG).index("Question") + 1)
    assert cell.data_type == "s"
    assert cell.value == '=HYPERLINK("http://x") why?'


def test_a_locked_workbook_keeps_rows_pending_until_it_frees(tmp_path, monkeypatch):
    path = tmp_path / "u.xlsx"
    real_write = wb.write_rows

    def locked(*_args, **_kwargs):
        raise PermissionError("open in Excel")

    monkeypatch.setattr(wb, "write_rows", locked)
    first = studio_generate_event({"report": "qbr"})
    with pytest.raises(PermissionError):
        wb.append_rows(path, [(first.sheet, first.as_row(ALICE))])
    assert wb.pending_path(path).exists()

    monkeypatch.setattr(wb, "write_rows", real_write)
    second = tab_visit_event("MoM")
    wb.append_rows(path, [(second.sheet, second.as_row(ALICE))])
    assert not wb.pending_path(path).exists()
    (studio,) = read_sheet(path, STUDIO)
    assert isinstance(studio["Timestamp"], datetime)
    assert [r["Tab"] for r in read_sheet(path, TAB_VISITS)] == ["MoM"]


def test_switched_off_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_METRICS", "off")
    monkeypatch.setenv("USAGE_METRICS_DIR", str(tmp_path))
    assert record_usage(ALICE, tab_visit_event("Studio")) is None
    assert not list(tmp_path.iterdir())


# ── UI wiring (the callback bodies, called directly) ──────────────────────────

SIGNED_IN = {"id": 4, "username": "x@y.com"}


@pytest.fixture
def captured(monkeypatch, machine) -> list:
    calls: list = []
    monkeypatch.setattr(
        usage_tracking,
        "record_usage",
        lambda actor, event: calls.append((actor, event)),
    )
    return calls


def test_tab_visit_uses_the_navbar_label(captured):
    usage_tracking.record_tab_visit("chat", SIGNED_IN)
    actor, event = captured[0]
    assert actor.user_id == "jdoe"
    assert (event.sheet, event.values["Tab"]) == (TAB_VISITS, "Ask ICG")


def test_recap_upload_lists_the_deck_names(captured):
    files = [
        {"name": "Q3 QBR.pptx", "path": "p1"},
        {"name": "Q2 QBR.pptx", "path": "p2"},
    ]
    usage_tracking.record_recap_upload(files, SIGNED_IN)
    usage_tracking.record_recap_upload([], SIGNED_IN)
    assert len(captured) == 1
    assert captured[0][1].values["Uploaded files"] == "Q3 QBR.pptx\nQ2 QBR.pptx"


def test_studio_generate_records_the_selection(captured):
    usage_tracking.record_studio_generate(None, SIGNED_IN)
    usage_tracking.record_studio_generate({"report": "qbr"}, SIGNED_IN)
    assert [e.values["Deliverable"] for _a, e in captured] == ["qbr"]


def test_mom_generate_records_both_uploads(captured):
    usage_tracking.record_mom_generate(
        "job1",
        None,
        {"name": "notes.docx"},
        {"name": "deck.pptx"},
        SIGNED_IN,
    )
    usage_tracking.record_mom_generate(
        "job2", None, None, {"name": "d.pptx"}, SIGNED_IN
    )
    usage_tracking.record_mom_generate(None, None, {}, {}, SIGNED_IN)
    assert len(captured) == 2
    first, second = (event.values for _a, event in captured)
    assert (first["Note file"], first["Deck file"]) == ("notes.docx", "deck.pptx")
    assert (second["Note file"], second["Deck file"]) == ("", "d.pptx")
