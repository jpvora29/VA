"""The MoM workspace inside the merged shell.

MoM was a standalone Dash app on its own port with its own layout, palette and Flask
download route. Folding it into the one application is where the integration risks
live, and they are the ones this file checks:

  * an id that collides with Studio's or the Chatbot's (Dash refuses to start),
  * a callback pointing at a component the page never renders,
  * a store the workspace reads that nobody mounts,
  * a re-render that would empty the upload zones the user already filled.

The frame tests need only Dash. The wired-application test needs the ``config``
package, which is absent from some working copies, so it skips itself there.
"""
from __future__ import annotations

import collections
import json
import pathlib

import dash
import pytest
from dash.development.base_component import Component

from mom.modes import DEFAULT_MODE, MODES
from mom.progress import PHASES
from ui.mom.callbacks import can_generate, file_status, missing_hint, register_mom
from ui.mom.render import mom_body, mom_rail, progress_panel, rail_steps, step_class
from ui.shell.rail import RAIL_CLASS
from ui.shell.stores import global_stores, mom_stores


def _walk(node):
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk(item)


def _ids(node) -> list[str]:
    out = []
    for component in _walk(node):
        cid = getattr(component, "id", None)
        if cid is None:
            continue
        out.append(json.dumps(cid, sort_keys=True) if isinstance(cid, dict) else cid)
    return out


def _text(node) -> str:
    """Every string in the tree, for asserting on what the user actually reads."""
    parts = []
    for component in _walk(node):
        children = getattr(component, "children", None)
        for child in children if isinstance(children, (list, tuple)) else [children]:
            if isinstance(child, str):
                parts.append(child)
    return " ".join(parts)


# ── the workspace shape ──────────────────────────────────────────────────────


def test_the_rail_wears_the_shared_frame_and_its_own_toggle():
    """MoM is now a real workspace, but the left edge must not change identity."""
    rail = mom_rail()
    assert rail.className.split()[0] == RAIL_CLASS
    toggles = [
        c.id for c in _walk(rail)
        if isinstance(getattr(c, "id", None), dict) and c.id.get("type") == "va-rail-toggle"
    ]
    assert toggles == [{"type": "va-rail-toggle", "rail": "mom"}]


def test_the_rail_shows_the_pipeline_the_engine_actually_runs():
    """A rail that lists steps the pipeline does not have would lie during a run."""
    assert _text(mom_rail()).count("Reading") >= 1
    for phase in PHASES:
        assert phase.label in _text(mom_rail())


def test_the_rail_keeps_the_placeholder_geometry_so_the_icon_column_matches():
    """`va-rail-step` is what assets/va_shell.css sizes for the collapsed column."""
    for step in rail_steps("tagging"):
        assert step.className.startswith("va-rail-step")
    assert "mom-rail-steps" in _ids(mom_rail())


def test_the_rail_lights_the_phase_the_run_is_in():
    running = [i for i, phase in enumerate(PHASES) if "is-running" in step_class(i, "tagging", False)]
    assert [PHASES[i].id for i in running] == ["tagging"]
    # Everything before it is done, everything after is untouched.
    assert "is-done" in step_class(0, "tagging", False)
    assert step_class(len(PHASES) - 1, "tagging", False) == "va-rail-step"
    assert all("is-done" in step_class(i, "summary", True) for i in range(len(PHASES)))


def test_the_body_offers_both_document_types_with_the_default_lit():
    body = mom_body()
    ids = _ids(body)
    for mode in MODES:
        assert json.dumps({"mode": mode.id, "type": "mom-mode"}, sort_keys=True) in ids
        assert mode.label in _text(body)

    active = [
        c for c in _walk(body)
        if isinstance(getattr(c, "id", None), dict)
        and c.id.get("type") == "mom-mode"
        and "is-active" in (c.className or "")
    ]
    assert [c.id["mode"] for c in active] == [DEFAULT_MODE]


def test_generate_starts_disabled_so_a_run_cannot_start_without_files():
    button = next(c for c in _walk(mom_body()) if getattr(c, "id", None) == "mom-generate")
    assert button.disabled is True


def test_the_upload_zones_are_static_and_only_their_status_moves():
    """A callback that re-rendered a zone would drop the file already chosen — the
    shape the standalone app was built around, and the reason it is kept here."""
    body = mom_body()
    ids = _ids(body)
    for zone in ("mom-upload-note", "mom-upload-deck"):
        assert ids.count(zone) == 1
    for status in ("mom-note-status", "mom-deck-status", "mom-progress", "mom-hint",
                   "mom-note-formats"):
        assert status in ids

    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_mom(app)
    outputs = []
    for callback in app.callback_map.values():
        target = callback["output"]
        outputs += list(target) if isinstance(target, list) else [target]

    # Nothing may write the zones' `children`, nor the `children` of anything holding
    # them: either would rebuild the component and drop the file it is carrying. The
    # one output a zone does take is `accept`, which the mode switch changes in place.
    structural = {"children", "contents"}
    holders = {"mom-upload-note", "mom-upload-deck", "mom-note-cell"}
    offenders = [
        f"{out.component_id}.{out.component_property}"
        for out in outputs
        if out.component_id in holders and out.component_property in structural
    ]
    assert offenders == []
    assert "mom-upload-note.accept" in {
        f"{out.component_id}.{out.component_property}" for out in outputs
    }


# ── the button's guard ───────────────────────────────────────────────────────


def test_generate_is_armed_only_when_a_run_is_possible():
    note, deck = {"path": "/a/note.pdf"}, {"path": "/a/deck.pptx"}
    assert can_generate("ai_summary", note, deck)
    assert not can_generate("ai_summary", note, None)
    assert not can_generate("ai_summary", None, deck)
    assert not can_generate(None, note, deck)
    assert not can_generate("ai_summary", {"name": "x"}, deck), "a name is not a staged file"


def test_generate_comes_back_when_a_run_ends():
    """Nothing writes ``mom-job`` when a run FINISHES — the poll switching itself off
    is the only signal. Without it as an input, the button stayed disabled for the
    rest of the session and a second run was impossible."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_mom(app)

    arming = [
        callback for callback in app.callback_map.values()
        if any(
            getattr(out, "component_id", None) == "mom-generate"
            for out in (callback["output"] if isinstance(callback["output"], list)
                        else [callback["output"]])
        )
    ]
    assert len(arming) == 1
    inputs = {dep["id"] for dep in arming[0]["inputs"]}
    assert "mom-poll" in inputs, "the button never learns a run ended"


def test_the_hint_names_the_file_still_missing():
    assert "meeting note" in missing_hint(None, None)
    assert "QBR deck" in missing_hint({"path": "n"}, None)
    assert missing_hint({"path": "n"}, {"path": "d"}) == ""


def test_a_rejected_upload_says_so_rather_than_failing_silently():
    from mom.uploads import StagedFile

    good = file_status(StagedFile(name="deck.pptx", path=pathlib.Path("deck.pptx")))
    assert "deck.pptx" in _text(good) and "is-good" in good.className
    bad = file_status(None, "notes.txt is not .pdf or .docx.")
    assert "is-bad" in bad.className and "notes.txt" in _text(bad)
    assert file_status(None) == ""


# ── the progress panel ───────────────────────────────────────────────────────


def test_a_running_panel_shows_the_step_and_no_download():
    panel = progress_panel({"step": "Tagging and scoring", "percent": 40,
                            "message": "Tagging 8 slide(s)", "done": False, "error": None})
    assert "Tagging and scoring" in _text(panel) and "40%" in _text(panel)
    assert "mom-download-btn" not in _ids(panel)


def test_a_finished_panel_offers_the_document():
    panel = progress_panel({
        "step": "Writing the minutes", "percent": 100, "message": "ready", "done": True,
        "error": None, "filename": "Zurich_Meeting_Notes.docx", "client": "Zurich",
        "topics": ["Key Takeaways / KPIs & Performance Headlines"],
    })
    assert "mom-download-btn" in _ids(panel)
    assert "Zurich_Meeting_Notes.docx" in _text(panel)
    assert "KPIs & Performance Headlines" in _text(panel)


def test_a_failed_panel_shows_the_reason_and_never_a_download():
    """A failed run that still offered a download would hand over a stale file."""
    panel = progress_panel({"step": "Verifying", "percent": 60, "message": "",
                            "done": True, "error": "Only 1 priority pair was produced."})
    assert "mom-download-btn" not in _ids(panel)
    assert "Only 1 priority pair" in _text(panel)
    fill = next(c for c in _walk(panel) if "mom-progress-fill" in (c.className or ""))
    assert fill.style["width"] == "0%"


# ── stores and stylesheet ────────────────────────────────────────────────────


def test_every_store_the_workspace_reads_is_mounted():
    """A callback reading a store nobody mounts fires with None forever."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_mom(app)

    mounted = set(_ids(global_stores())) | set(_ids(mom_body())) | set(_ids(mom_rail()))
    # `mom-download-btn` is rendered by the poll once a run succeeds.
    mounted.add("mom-download-btn")

    for key, callback in app.callback_map.items():
        for dep in list(callback["inputs"]) + list(callback["state"]):
            if isinstance(dep["id"], str) and dep["id"].startswith("mom-"):
                assert dep["id"] in mounted, f"{key} -> {dep['id']}"


def test_the_poll_is_off_until_a_run_starts():
    """An idle MoM tab must not fire a callback every 1.5s for the whole session."""
    poll = next(s for s in mom_stores() if s.id == "mom-poll")
    assert poll.disabled is True
    assert poll.interval >= 1000


def test_the_workspace_brings_no_second_palette():
    """The standalone app carried its own navy/teal/ice hex values. On a page that
    already agrees on `--va-*` tokens, a fifth palette is the seam this merge removes."""
    import re

    css = pathlib.Path("assets/va_mom.css").read_text(encoding="utf-8")
    literals = set(re.findall(r"#[0-9a-fA-F]{3,8}\b", css))
    # One exception: a danger wash light enough that no token exists for it.
    assert literals <= {"#fdf2f2"}, literals
    assert "var(--va-" in css


def test_the_stylesheet_still_sorts_before_the_shell_sheet():
    """Dash serves /assets sorted; va_shell.css must stay last (test_app_shell.py)."""
    import os

    sheets = sorted(f for f in os.listdir("assets") if f.endswith(".css"))
    assert "va_mom.css" in sheets and sheets[-1] == "va_shell.css"


# ── the wired application ────────────────────────────────────────────────────

_NEEDS_CONFIG = "config/ is absent from this working copy; the Chatbot half cannot import"


@pytest.fixture(scope="module")
def merged_app():
    pytest.importorskip("config.report_config", reason=_NEEDS_CONFIG)
    import app as app_module

    app_module.app._setup_server()
    return app_module.app


def test_mom_registered_its_callbacks(merged_app):
    keys = " ".join(merged_app.callback_map)
    assert "mom-job.data" in keys          # a run starts
    assert "mom-progress.children" in keys  # and reports back
    assert "mom-download.data" in keys      # and hands over the document


def test_mom_ids_do_not_collide_with_the_rest_of_the_page(merged_app):
    from ui.shell.layout import app_shell

    seen = collections.Counter(_ids([merged_app.layout, app_shell(1, "Tester", "mom")]))
    assert [i for i, n in seen.items() if n > 1] == []


def test_the_mom_pane_holds_the_whole_workspace(merged_app):
    from ui.shell.layout import app_shell
    from ui.shell.tabs import pane_id

    pane = next(
        c for c in _walk(app_shell(1, "Tester", "mom"))
        if getattr(c, "id", None) == pane_id("mom")
    )
    ids = _ids(pane)
    assert {"mom-rail-steps", "mom-generate", "mom-upload-note", "mom-upload-deck"} <= set(ids)
