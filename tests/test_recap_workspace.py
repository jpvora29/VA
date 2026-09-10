"""The Recap workspace inside the merged shell.

Recap was a standalone Dash app on its own port with its own layout, its own palette
and its own Azure credentials. Folding it into the one application is where the
integration risks live, and they are the ones this file checks:

  * an id that collides with Studio's, MoM's or the Chatbot's (Dash refuses to start),
  * a callback pointing at a component the page never renders,
  * a store the workspace reads that nobody mounts,
  * a re-render that would empty the upload zone the user already filled,
  * a second palette arriving with the page.

The frame tests need only Dash. The wired-application test needs the ``config``
package, which is absent from some working copies, so it skips itself there.
"""
from __future__ import annotations

import json
import pathlib

import dash
import pytest
from dash.development.base_component import Component

from recap.metadata import DeckMetadata
from recap.progress import PHASES, STAGES
from recap.uploads import StagedFile
from ui.recap.callbacks import can_generate, file_status, missing_hint, register_recap
from ui.recap.render import (
    meta_chips,
    progress_panel,
    rail_steps,
    recap_body,
    recap_rail,
    step_class,
)
from ui.shell.rail import RAIL_CLASS
from ui.shell.stores import global_stores, recap_stores


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


def _outputs(app) -> list:
    outputs = []
    for callback in app.callback_map.values():
        target = callback["output"]
        outputs += list(target) if isinstance(target, list) else [target]
    return outputs


@pytest.fixture()
def wired_app():
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_recap(app)
    return app


# ── the workspace shape ──────────────────────────────────────────────────────


def test_the_rail_wears_the_shared_frame_and_its_own_toggle():
    """Recap is now a real workspace, but the left edge must not change identity."""
    rail = recap_rail()
    assert rail.className.split()[0] == RAIL_CLASS
    toggles = [
        c.id for c in _walk(rail)
        if isinstance(getattr(c, "id", None), dict) and c.id.get("type") == "va-rail-toggle"
    ]
    assert toggles == [{"type": "va-rail-toggle", "rail": "recap"}]


def test_the_rail_shows_the_pipeline_the_engine_actually_runs():
    """A rail that lists steps the pipeline does not have would lie during a run."""
    shown = _text(recap_rail())
    for phase in PHASES:
        assert phase.label in shown


def test_every_stage_belongs_to_a_phase_the_rail_shows():
    """A stage whose phase is not on the rail would move the bar and light nothing."""
    rail_phases = {phase.id for phase in PHASES}
    assert {stage.phase for stage in STAGES} <= rail_phases


def test_the_rail_keeps_the_placeholder_geometry_so_the_icon_column_matches():
    """`va-rail-step` is what assets/va_shell.css sizes for the collapsed column."""
    for step in rail_steps("classify"):
        assert step.className.startswith("va-rail-step")
    assert "recap-rail-steps" in _ids(recap_rail())


def test_the_rail_lights_the_phase_the_run_is_in():
    running = [i for i, _ in enumerate(PHASES) if "is-running" in step_class(i, "classify", False)]
    assert [PHASES[i].id for i in running] == ["classify"]
    # Everything before it is done, everything after is untouched.
    assert "is-done" in step_class(0, "classify", False)
    assert step_class(len(PHASES) - 1, "classify", False) == "va-rail-step"
    assert all("is-done" in step_class(i, "render", True) for i in range(len(PHASES)))


def test_generate_starts_disabled_so_a_run_cannot_start_without_a_deck():
    button = next(c for c in _walk(recap_body()) if getattr(c, "id", None) == "recap-generate")
    assert button.disabled is True


def test_the_zone_takes_several_decks_at_once():
    """A recap can cover more than one quarter — that is the shape MoM does not have."""
    zone = next(c for c in _walk(recap_body()) if getattr(c, "id", None) == "recap-upload")
    assert zone.multiple is True
    assert zone.accept == ".pptx"


def test_the_upload_zone_is_static_and_only_its_status_moves(wired_app):
    """A callback that re-rendered the zone would drop the decks already chosen — the
    shape the standalone app was built around, and the reason it is kept here."""
    ids = _ids(recap_body())
    assert ids.count("recap-upload") == 1
    for target in ("recap-file-status", "recap-meta", "recap-progress", "recap-hint"):
        assert target in ids

    structural = {"children", "contents"}
    offenders = [
        f"{out.component_id}.{out.component_property}"
        for out in _outputs(wired_app)
        if out.component_id == "recap-upload" and out.component_property in structural
    ]
    assert offenders == []


# ── the button's guard ───────────────────────────────────────────────────────


def test_generate_is_armed_only_when_a_deck_is_staged(tmp_path):
    deck = tmp_path / "q2.pptx"
    deck.write_bytes(b"x")
    assert can_generate([{"name": "q2.pptx", "path": str(deck)}])
    assert not can_generate([])
    assert not can_generate(None)
    assert not can_generate([{"name": "q2.pptx"}]), "a name is not a staged file"
    assert not can_generate([{"name": "gone.pptx", "path": str(tmp_path / "gone.pptx")}])


def test_generate_comes_back_when_a_run_ends(wired_app):
    """Nothing writes ``recap-job`` when a run FINISHES — the poll switching itself off
    is the only signal. Without it as an input, the button would stay disabled for the
    rest of the session and a second run would be impossible."""
    arming = [
        callback for callback in wired_app.callback_map.values()
        if any(
            getattr(out, "component_id", None) == "recap-generate"
            for out in (callback["output"] if isinstance(callback["output"], list)
                        else [callback["output"]])
        )
    ]
    assert len(arming) == 1
    inputs = {dep["id"] for dep in arming[0]["inputs"]}
    assert "recap-poll" in inputs, "the button never learns a run ended"


def test_the_hint_names_what_is_still_missing():
    assert "QBR deck" in missing_hint(None)
    assert missing_hint([{"name": "q2.pptx", "path": __file__}]) == ""


def test_each_upload_reports_its_own_outcome():
    """A drop of five decks with one bad file must not lose the four good ones."""
    staged = [StagedFile(name="q1.pptx", path=pathlib.Path("q1.pptx")),
              StagedFile(name="q2.pptx", path=pathlib.Path("q2.pptx"))]
    lines = file_status(staged, ["notes.txt is not .pptx."])
    assert len(lines) == 3
    assert "q1.pptx" in _text(lines) and "notes.txt" in _text(lines)
    assert [line.className for line in lines] == ["is-good", "is-good", "is-bad"]
    assert file_status([]) == ""


# ── the cover-slide chips ────────────────────────────────────────────────────


def test_the_chips_show_what_the_cover_said():
    """Recap's own tweak on the MoM page: a misread client is a wrong title on every
    slide of the finished deck, so it is shown BEFORE the run, not after."""
    chips = meta_chips(DeckMetadata(client_name="Acme Corp", quarter="Q2", year="2026"))
    shown = _text(chips)
    assert "Acme Corp" in shown and "Q2" in shown and "2026" in shown
    assert "Client" in shown


def test_the_chips_say_so_when_the_cover_gave_nothing():
    assert "Nothing detected" in _text(meta_chips(DeckMetadata()))


# ── the progress panel ───────────────────────────────────────────────────────


def test_a_running_panel_shows_the_stage_and_no_download():
    panel = progress_panel({"step": "Classifying insights", "percent": 70,
                            "message": "acme_q2.pptx", "done": False, "error": None})
    assert "Classifying insights" in _text(panel) and "70%" in _text(panel)
    assert "recap-download-btn" not in _ids(panel)


def test_a_finished_panel_offers_the_deck():
    panel = progress_panel({
        "step": "Rendering the PPTX", "percent": 100, "message": "ready", "done": True,
        "error": None, "filename": "acme_q2_2026_recap.pptx", "client": "Acme Corp",
        "period": "Q2 2026", "takeaways": ["Growth in Germany"],
        "insights": 42, "action_items": 3,
    })
    assert "recap-download-btn" in _ids(panel)
    shown = _text(panel)
    assert "acme_q2_2026_recap.pptx" in shown and "Acme Corp" in shown
    assert "Growth in Germany" in shown
    assert "42 insight(s) read" in shown and "3 action item(s)" in shown


def test_a_failed_panel_shows_the_reason_and_never_a_download():
    """A failed run that still offered a download would hand over a stale deck."""
    panel = progress_panel({"step": "Extracting slides", "percent": 15, "message": "",
                            "done": True, "error": "acme_q2.pptx is not a PowerPoint file."})
    assert "recap-download-btn" not in _ids(panel)
    assert "not a PowerPoint file" in _text(panel)
    fill = next(c for c in _walk(panel) if "recap-progress-fill" in (c.className or ""))
    assert fill.style["width"] == "0%"


# ── stores and stylesheet ────────────────────────────────────────────────────


def test_every_store_the_workspace_reads_is_mounted(wired_app):
    """A callback reading a store nobody mounts fires with None forever."""
    mounted = set(_ids(global_stores())) | set(_ids(recap_body())) | set(_ids(recap_rail()))
    # `recap-download-btn` is rendered by the poll once a run succeeds.
    mounted.add("recap-download-btn")

    for key, callback in wired_app.callback_map.items():
        for dep in list(callback["inputs"]) + list(callback["state"]):
            if isinstance(dep["id"], str) and dep["id"].startswith("recap-"):
                assert dep["id"] in mounted, f"{key} -> {dep['id']}"


def test_recap_ids_do_not_collide_with_another_workspace():
    """All four workspaces are mounted at once; two components sharing an id is a
    Dash startup error, not a rendering quirk."""
    ids = [i for i in _ids(global_stores()) if isinstance(i, str)]
    assert len(ids) == len(set(ids))


def test_the_poll_is_off_until_a_run_starts():
    """An idle Recap tab must not fire a callback every 1.5s for the whole session."""
    poll = next(s for s in recap_stores() if s.id == "recap-poll")
    assert poll.disabled is True
    assert poll.interval >= 1000


def test_the_workspace_brings_no_second_palette():
    """The standalone app carried its own teal/ice hex values. On a page that already
    agrees on `--va-*` tokens, a second palette is the seam this merge removes."""
    import re

    css = pathlib.Path("assets/va_recap.css").read_text(encoding="utf-8")
    literals = set(re.findall(r"#[0-9a-fA-F]{3,8}\b", css))
    # One exception, shared with the MoM sheet: a danger wash light enough that no
    # token exists for it.
    assert literals <= {"#fdf2f2"}, literals
    assert "var(--va-" in css


def test_the_stylesheet_still_sorts_before_the_shell_sheet():
    """Dash serves /assets sorted; the Recap sheet must load before the shell sheet,
    which owns the rail and the pane heights (see test_app_shell.py for the full
    ordering contract)."""
    import os

    sheets = sorted(f for f in os.listdir("assets") if f.endswith(".css"))
    assert sheets.index("va_recap.css") < sheets.index("va_shell.css"), sheets


# ── the wired application ────────────────────────────────────────────────────

_NEEDS_CONFIG = "config/ is absent from this working copy; the Chatbot half cannot import"


@pytest.fixture(scope="module")
def merged_app():
    pytest.importorskip("config.report_config", reason=_NEEDS_CONFIG)
    import app as app_module

    app_module.app._setup_server()
    return app_module.app


def test_recap_registered_its_callbacks(merged_app):
    keys = " ".join(merged_app.callback_map)
    assert "recap-job.data" in keys           # a run starts
    assert "recap-progress.children" in keys  # and reports back


def test_the_recap_pane_is_mounted_beside_the_others(merged_app):
    from ui.shell.layout import app_shell
    from ui.shell.tabs import pane_id

    ids = _ids(app_shell(1, "Tester", "recap"))
    assert pane_id("recap") in ids
    assert "recap-upload" in ids
