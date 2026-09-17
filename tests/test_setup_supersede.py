"""The Setup form stays live while it works — so the LAST change has to be the one that wins.

The busy overlay is a progress cue with ``pointer-events: none`` (``assets/studio_authoring.css``
says so in as many words: "a change made while it is up must still land"), and four callbacks
answer every filter change concurrently. Two changes in quick succession therefore put two sets
of answers in flight, and without a guard the one that happens to arrive last repaints the form —
which may be the answer to the selection the user has already left.

These tests pin the guard: an answer for a superseded selection is dropped, the newest one is
never dropped, and one viewer's typing never discards another viewer's answer.
"""
from __future__ import annotations

import inspect
import threading

import pytest

from studio.authoring import supersede


@pytest.fixture(autouse=True)
def _forget_viewers():
    supersede.clear()
    yield
    supersede.clear()


# ── the rule ─────────────────────────────────────────────────────────────────


def test_an_answer_for_an_older_selection_is_superseded():
    first = supersede.begin({"carrier": "Zurich"})
    assert not supersede.superseded(first)

    supersede.begin({"carrier": "Zurich", "country": "Japan"})    # the user moved on
    assert supersede.superseded(first), "the stale answer would have repainted the form"


def test_the_newest_answer_is_never_superseded():
    supersede.begin({"carrier": "Zurich"})
    newest = supersede.begin({"carrier": "AIG"})
    assert not supersede.superseded(newest)


def test_a_repeat_of_the_same_selection_does_not_supersede_itself():
    """The four callbacks all begin on the SAME selection, and a remount re-fires them.

    None of those must invalidate the others — only a different selection does.
    """
    cascade = supersede.begin({"carrier": "Zurich"})
    supersede.begin({"carrier": "Zurich"})        # the preview, the survey panel, a remount
    assert not supersede.superseded(cascade)


def test_selection_key_ignores_the_order_the_controls_were_read_in():
    assert (supersede.selection_key({"carrier": "Zurich", "year": 2025})
            == supersede.selection_key({"year": 2025, "carrier": "Zurich"}))
    assert (supersede.selection_key({"carrier": "Zurich"})
            != supersede.selection_key({"carrier": "AIG"}))
    # A multi-select's values are part of the identity, not just its presence.
    assert (supersede.selection_key({"country": ["Japan"]})
            != supersede.selection_key({"country": ["Japan", "Singapore"]}))


def test_a_ticket_from_a_viewer_that_never_began_is_not_stale():
    """A caller that does not take part must never be told its answer is worthless."""
    assert not supersede.superseded(supersede.Ticket(viewer="nobody", selection="x"))


def test_one_viewer_does_not_drop_another_viewers_answer(monkeypatch):
    """Two people on the same server: B changing a filter must not blank A's dropdowns."""
    monkeypatch.setattr(supersede, "viewer_key", lambda: "viewer-a")
    a = supersede.begin({"carrier": "Zurich"})
    monkeypatch.setattr(supersede, "viewer_key", lambda: "viewer-b")
    supersede.begin({"carrier": "AIG"})

    assert not supersede.superseded(a), "another viewer's change dropped this one's answer"


def test_the_viewer_key_falls_back_outside_a_request():
    """Called from a test or a first render there is no Flask request at all."""
    assert supersede.viewer_key() == "local"


def test_the_viewer_table_stays_bounded(monkeypatch):
    """A long-lived server must not keep a fact about every session it has ever served."""
    for i in range(supersede._MAX_VIEWERS + 5):
        monkeypatch.setattr(supersede, "viewer_key", lambda i=i: f"viewer-{i}")
        supersede.begin({"carrier": f"C{i}"})
    assert len(supersede._latest) <= supersede._MAX_VIEWERS


# ── the shape it takes under real concurrency ────────────────────────────────


def test_a_slow_answer_loses_to_a_change_made_while_it_was_computing():
    """The actual sequence: the cascade starts, the user picks again, the cascade finishes.

    The slow one must not win just because it replies last — which, with two concurrent
    requests, is exactly what could happen.
    """
    started = threading.Event()
    verdict = {}

    def slow_cascade():
        ticket = supersede.begin({"carrier": "Zurich"})
        started.set()
        moved_on.wait(2)                       # the user changes a filter meanwhile
        verdict["slow"] = supersede.superseded(ticket)

    moved_on = threading.Event()
    worker = threading.Thread(target=slow_cascade)
    worker.start()
    started.wait(2)

    fresh = supersede.begin({"carrier": "Zurich", "country": "Japan"})
    moved_on.set()
    worker.join(5)

    assert verdict["slow"] is True, "the stale answer was allowed to land"
    assert not supersede.superseded(fresh), "the change the user actually made was dropped"


def test_stale_says_so_in_the_log(caplog):
    ticket = supersede.begin({"carrier": "Zurich"})
    supersede.begin({"carrier": "AIG"})
    with caplog.at_level("INFO"):
        assert supersede.stale(ticket, "option cascade") is True
    assert "option cascade" in caplog.text


# ── every filter-driven callback takes part ──────────────────────────────────


def test_every_callback_that_answers_a_filter_change_drops_a_stale_answer():
    """Four callbacks answer a filter change, and all four can repaint the form.

    A new one added without the guard is the regression this catches: it would be the one
    callback that can still show the previous selection's answer.
    """
    from studio.authoring import setup as S

    source = inspect.getsource(S.register_setup)
    assert source.count("supersede.begin(") == 4, (
        "the option cascade, the scope preview, the survey panel and the survey peers")
    assert source.count("supersede.stale(") == 4, "each must also CHECK before returning"
    assert source.count("raise PreventUpdate") >= 4


def test_the_guard_runs_after_the_work_not_before_it():
    """Checked at the END of the callback: the point is to discard an answer that took so
    long the filters moved on, and at the start there is nothing to discard yet."""
    from studio.authoring import setup as S

    for name in ("refresh_form", "scope_preview"):
        body = next(src for src in _callback_bodies(S.register_setup) if f"def {name}(" in src)
        assert body.index("supersede.begin(") < body.index("supersede.stale("), name


def _callback_bodies(register):
    """Each inner callback of ``register``, as source text."""
    source = inspect.getsource(register)
    chunks = source.split("    @app.callback(")
    return [chunk for chunk in chunks if "def " in chunk]
