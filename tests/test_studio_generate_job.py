"""Generating a deck: the background build, the batched writes, the pruned previews.

These are the three things that made a finished deck fail to reach the canvas:

  * the build ran INSIDE the Dash callback, so a build longer than the browser's patience
    lost its answer and left the previous deck on screen;
  * every commentary column was written one after the next, which is what made a build
    that long in the first place;
  * every deck ever generated left a full render of every slide in ``assets/``.

All deterministic — no LLM, no DB_PATH. The model writer is injected, and the build is a
stub wherever the test is about the plumbing rather than about the deck.
"""
from __future__ import annotations

import threading
import time

import pytest

from studio.authoring import jobs
from studio.authoring.generate import DeckDocuments
from studio.authoring.progress import PHASES, label_for, percent_done
from studio.template_fill import rewrites
from studio.template_fill.rewrites import PendingRewrite


# ── the background build ─────────────────────────────────────────────────────


def _await(job, timeout: float = 5.0) -> dict:
    """Block until the job finishes, so the assertions read as the poll would."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = job.snapshot()
        if state["done"]:
            return state
        time.sleep(0.01)
    raise AssertionError(f"build did not finish within {timeout}s")


def test_a_build_runs_off_the_callback_and_hands_back_its_documents():
    """The whole point: start returns at once, the documents arrive later."""
    docs = DeckDocuments(doc={"order": [0]}, tdoc={"n_slides": 7})
    started = time.time()
    job = jobs.start_build({"filters": {"carrier": "Zurich"}}, builder=lambda s, report: docs)
    assert time.time() - started < 1.0, "starting a build must not wait for it"

    state = _await(job)
    assert state["error"] is None
    assert state["percent"] == 100
    assert job.documents() is docs
    assert state["slides"] == 7
    jobs.clear_job(job.job_id)


def test_a_failing_build_reaches_the_user_instead_of_dying_in_its_thread():
    def explode(selection, report):
        raise RuntimeError("no money measure")

    job = jobs.start_build({"filters": {}}, builder=explode)
    state = _await(job)
    assert state["done"] and state["error"] == "no money measure"
    assert job.documents() is None
    jobs.clear_job(job.job_id)


def test_a_build_reports_every_phase_it_enters():
    seen = []

    def builder(selection, report):
        for phase in PHASES:
            report(phase.id, f"doing {phase.id}")
        return DeckDocuments()

    job = jobs.start_build({}, builder=builder)

    def watch():
        while not job.snapshot()["done"]:
            seen.append(job.snapshot()["phase"])
    threading.Thread(target=watch, daemon=True).start()
    _await(job)
    # The reporter is what the progress panel reads, so the labels must resolve.
    assert all(label_for(p.id) != "Working" for p in PHASES)
    assert percent_done(PHASES[0].id) < percent_done(PHASES[-1].id) < 100
    jobs.clear_job(job.job_id)


def test_a_job_that_has_been_cleared_is_gone():
    job = jobs.start_build({}, builder=lambda s, report: DeckDocuments())
    _await(job)
    jobs.clear_job(job.job_id)
    assert jobs.get_job(job.job_id) is None


# ── writing a deck's commentary in one batch ─────────────────────────────────


def _pending(draft: str) -> PendingRewrite:
    return PendingRewrite(draft=draft, node="test", topic="working", subject="Zurich")


def test_a_pending_column_already_renders_as_its_draft():
    """Deferral is only safe because a value holding one is never wrong."""
    assert str(_pending("the book grew 12%")) == "the book grew 12%"


def test_every_column_is_written_back_to_its_own_role():
    value_sets = [
        {"fbnote:0:1:0:0": _pending("a"), "fb:0:2:0:0": "$1.2m"},
        {"fbnote:1:1:0:0": _pending("b")},
    ]
    written = rewrites.write_all(value_sets, write=lambda p: p.draft.upper())
    assert written == [{"fbnote:0:1:0:0": "A", "fb:0:2:0:0": "$1.2m"},
                       {"fbnote:1:1:0:0": "B"}]


def test_the_deterministic_draft_stands_when_the_model_returns_nothing():
    written = rewrites.write_all([{"r": _pending("the draft")}], write=lambda p: "")
    assert written == [{"r": "the draft"}]


def test_which_column_finishes_first_cannot_change_the_deck():
    """The whole risk of batching. A slow first column must not reorder anything."""
    def write(pending):
        time.sleep(0.05 if pending.draft == "first" else 0.0)
        return pending.draft.upper()

    value_sets = [{"a": _pending("first"), "b": _pending("second")}]
    assert rewrites.write_all(value_sets, write=write) == [{"a": "FIRST", "b": "SECOND"}]


def test_the_columns_are_written_concurrently_not_one_after_the_next():
    live, peak, lock = [0], [0], threading.Lock()

    def write(pending):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        return pending.draft

    rewrites.write_all([{f"r{i}": _pending(str(i)) for i in range(8)}], write=write)
    assert peak[0] > 1, "a deck's commentary columns must not be written serially"


def test_a_value_set_with_no_pending_columns_is_handed_straight_back():
    assert rewrites.write_all([{"a": "done"}], write=lambda p: "never") == [{"a": "done"}]


# ── the preview cache ────────────────────────────────────────────────────────


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_TEMPLATE_ASSET_ROOT", str(tmp_path / "previews"))
    return tmp_path


def _deck_file(tmp_path, name: str, body: bytes):
    path = tmp_path / name
    path.write_bytes(body)
    return str(path)


def test_only_the_deck_on_screen_keeps_its_slide_images(cache, monkeypatch):
    from studio.template_fill import preview_assets as PA

    # Two decks generated in a row; the second must not leave the first's renders behind.
    old = _deck_file(cache, "old.pptx", b"deck-one")
    new = _deck_file(cache, "new.pptx", b"deck-two")
    monkeypatch.setattr(PA, "source_template_paths", lambda: [])
    for path in (old, new):
        (PA.template_cache_dir(path) / "backgrounds").mkdir(parents=True)

    assert PA.prune_cache([new]) == 1
    assert PA.template_cache_dir(new).exists()
    assert not PA.template_cache_dir(old).exists()


def test_the_source_templates_are_never_pruned(cache, monkeypatch):
    """Six files that never change and are the slow half of opening the canvas."""
    from studio.template_fill import preview_assets as PA

    template = _deck_file(cache, "overall_template.pptx", b"template")
    monkeypatch.setattr(PA, "source_template_paths", lambda: [template])
    PA.template_cache_dir(template).mkdir(parents=True)

    PA.prune_cache([])
    assert PA.template_cache_dir(template).exists()


def test_a_kept_template_still_sheds_its_old_document_renders(cache, monkeypatch):
    """Each EDIT adds a full render inside the kept directory, so it is trimmed inside."""
    from studio.template_fill import preview_assets as PA

    template = _deck_file(cache, "overall_template.pptx", b"template")
    monkeypatch.setattr(PA, "source_template_paths", lambda: [template])
    renders = PA.template_cache_dir(template) / "doc-backgrounds"
    for i in range(4):
        (renders / f"render-{i}").mkdir(parents=True)
        time.sleep(0.01)          # mtime order is what "newest" means here

    assert PA.prune_cache([]) == 3
    assert [d.name for d in renders.iterdir()] == ["render-3"]


def test_a_read_only_preview_directory_is_still_removed(cache, monkeypatch):
    """Regression: OneDrive marks every folder it syncs read-only, and ``rmtree`` refuses
    those with a bare "Access is denied" — so the first prune deleted 7 of 1,736."""
    import os
    import stat

    from studio.template_fill import preview_assets as PA

    deck = _deck_file(cache, "deck.pptx", b"deck")
    monkeypatch.setattr(PA, "source_template_paths", lambda: [])
    backgrounds = PA.template_cache_dir(deck) / "backgrounds"
    backgrounds.mkdir(parents=True)
    (backgrounds / "slide-000.png").write_bytes(b"png")
    for path in (backgrounds / "slide-000.png", backgrounds, PA.template_cache_dir(deck)):
        os.chmod(path, stat.S_IREAD)

    assert PA.prune_cache([]) == 1
    assert not PA.template_cache_dir(deck).exists()


def test_pruning_an_empty_cache_is_not_an_error(cache):
    from studio.template_fill import preview_assets as PA

    assert PA.prune_cache([]) == 0


# ── the callbacks that start and land a build ────────────────────────────────


def _component_ids(node) -> set:
    """Every plain-string component id in a rendered Dash tree."""
    found, stack = set(), [node]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        if isinstance(item, str) or item is None:
            continue
        cid = getattr(item, "id", None)
        if isinstance(cid, str):
            found.add(cid)
        children = getattr(item, "children", None)
        if children is not None:
            stack.append(children)
    return found


def _fixed(dependencies) -> list:
    """Plain-string ids only — a pattern-matching id reads back as '{"…":["ALL"]}'."""
    return [d["id"] for d in dependencies if not d["id"].startswith("{")]


def _output_ids(callback) -> list:
    outputs = callback["output"]
    outputs = outputs if isinstance(outputs, (list, tuple)) else [outputs]
    return [o.component_id for o in outputs
            if isinstance(getattr(o, "component_id", None), str)]


@pytest.fixture(scope="module")
def studio_app():
    from studio.authoring.layout import build_layout, create_app
    from studio.authoring.navigation import register_navigation
    from studio.authoring.setup import register_setup

    app = create_app()
    app.layout = build_layout()
    register_setup(app)
    register_navigation(app)
    return app


def test_the_build_poll_survives_the_author_walking_away_from_setup(studio_app):
    """The poll ticks for the whole build, which outlasts the screen it started on.

    Regression: the progress card lived in the Setup form, so opening Canvas mid-build
    left the poll writing into a component that was no longer on the page — and Dash
    refuses a callback whose output is missing, which is the finished deck never landing.
    """
    from studio.page.authoring.shell import authoring_shell

    poll = next(cb for cb in studio_app.callback_map.values()
                if "qs-gen-poll.n_intervals" in {d["id"] + "." + d["property"]
                                                 for d in cb["inputs"]})
    always_mounted = _component_ids(build_layout_for_test())
    missing = [dep for dep in _fixed(poll["state"]) + _output_ids(poll)
               if dep not in always_mounted]
    assert not missing, missing
    # …and the canvas mode really is one of the screens it has to survive.
    canvas = authoring_shell(None, mode="canvas", cut_groups=[], tdoc=None)
    assert "studio-gen-progress" not in _component_ids(canvas)


def build_layout_for_test():
    """The Studio shell minus ``qs-app`` — everything mounted for as long as Studio is."""
    from studio.authoring.layout import studio_chrome, studio_stores

    from dash import html

    return html.Div([*studio_stores(), *studio_chrome()])


def test_generate_starts_a_build_instead_of_running_one(studio_app):
    """The whole fix: the click callback must not be the thing that builds the deck."""
    import inspect

    from studio.authoring import setup as S

    source = inspect.getsource(S.register_setup)
    assert "jobs.start_build(selection)" in source
    assert "_generated_assembled_tdoc" not in source, "the build belongs off the callback"


def test_the_progress_card_clears_itself_once_the_deck_has_landed():
    from studio.page.authoring.setup import generate_progress

    assert generate_progress({"done": True, "error": None, "percent": 100}) == ""
    assert generate_progress(None) == ""


def test_a_failed_build_says_so_where_the_author_can_see_it():
    from studio.page.authoring.setup import generate_progress

    panel = generate_progress({"done": True, "error": "no money measure", "percent": 0})
    assert "no money measure" in str(panel.children[1].children)


# ── the real business flow, end to end ───────────────────────────────────────


def test_a_selection_becomes_a_previewable_deck(monkeypatch):
    """Setup selection -> book -> evidence -> sub-decks -> merged .pptx -> preview doc.

    Scoped to the overall axis and with the slide renderer off, so it proves the pipeline
    rather than the machine's PowerPoint. ``STUDIO_AI=off`` pins it to the deterministic
    composers: every column comes back as its draft, which is exactly the guarantee the
    deferral rests on.
    """
    from pathlib import Path

    from studio.authoring.generate import build_documents

    monkeypatch.setenv("STUDIO_AI", "off")
    monkeypatch.setenv("STUDIO_TEMPLATE_RENDERER", "none")

    phases = []
    docs = build_documents(
        {"filters": {"carrier": "Zurich"}, "report": "qbr", "template_scope": "overall",
         "data_basis": "premium", "style": "balanced", "ai": True},
        report=lambda phase, message: phases.append(phase),
    )

    assert [p.id for p in PHASES] == phases, "every phase must be announced, in order"
    assert docs.tdoc and docs.tdoc.get("assembled"), "the deliverable is the assembled deck"
    assert Path(docs.tdoc["template_path"]).exists()
    assert docs.tdoc["n_slides"] > 0
    # No column may reach the document still holding a pending rewrite.
    assert not rewrites.pending_items(docs.tdoc.get("values") or {})


# ── how much of the deck a model actually wrote ──────────────────────────────


def test_a_deck_reports_how_many_columns_the_model_wrote(caplog):
    """Every refusal path ends by returning the draft, per column and quietly — so a deck
    written entirely by the rule composers looks like one the model wrote badly."""
    import logging

    sets = [{"a": _pending("draft one"), "b": _pending("draft two")}]
    with caplog.at_level(logging.INFO, logger="studio.template_fill.rewrites"):
        rewrites.write_all(sets, write=lambda p: p.draft.upper() if p.draft.endswith("one")
                           else p.draft)
    assert "1/2 column(s) written by the model" in caplog.text


def test_a_deck_no_model_wrote_says_so_loudly(caplog):
    import logging

    sets = [{"a": _pending("draft")}]
    with caplog.at_level(logging.WARNING, logger="studio.template_fill.rewrites"):
        rewrites.write_all(sets, write=lambda p: p.draft)
    assert "NO column in this deck was model-written" in caplog.text
