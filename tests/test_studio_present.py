"""Present: the delivered deck as a full-screen slideshow.

The show is built from the same renders the canvas shows, in the deck's own order,
without the pages the author hid, and with their committed edits drawn in. These tests
walk that path on the real overall template: the button, the pages chosen, the renders
filled in, the overlay laid out, and the callback that opens and closes it.
"""
from __future__ import annotations

import pathlib

import pytest
from dash.development.base_component import Component

from studio.authoring import present as present_cb
from studio.page import slideshow as SS
from studio.page import template_preview as TP
from studio.page.authoring.chrome import _placeholder_topbar
from studio.page.authoring.present import present_button, slideshow_overlay
from studio.template_fill import preview_assets as PA
from studio.template_fill import text_edits as TE

TEMPLATE = pathlib.Path(__file__).parents[1] / "template" / "overall_template.pptx"
ASSETS = pathlib.Path(__file__).parents[1] / "assets"


@pytest.fixture(autouse=True)
def _only_the_renders_named_here(monkeypatch):
    """Renders are exactly the URLs a test puts on the doc — never the cache on disk."""
    if not TEMPLATE.exists():
        pytest.skip("the overall template is not checked out")
    monkeypatch.setattr(TP, "public_url_exists", lambda url: bool(url))
    monkeypatch.setattr(TP, "cached_doc_backgrounds", lambda doc, n: [None] * n)
    monkeypatch.setattr(PA, "_cached_backgrounds", lambda path, n: [None] * n)

    def no_renderer(*args, **kwargs):
        raise AssertionError("this test did not expect a render")

    monkeypatch.setattr(PA, "ensure_rendered_slide_backgrounds", no_renderer)


def _tdoc(**extra):
    return {
        "template_path": str(TEMPLATE),
        "values": {}, "manifest": [], "overrides": {}, "map_overrides": {},
        "added": {}, "hidden": [], "order": list(range(6)),
        "width_emu": 12192000, "height_emu": 6858000, "n_slides": 6,
        "assembled": True,
        "background_urls": [f"/assets/render-{i}.png" for i in range(6)],
        **extra,
    }


def _walk(node):
    if node is None:
        return
    if isinstance(node, (list, tuple)):
        for child in node:
            yield from _walk(child)
        return
    yield node
    if isinstance(node, Component):
        yield from _walk(getattr(node, "children", None))


def _with_class(node, cls):
    return [n for n in _walk(node) if cls in str(getattr(n, "className", "") or "").split()]


# ── the button ───────────────────────────────────────────────────────────────


def test_present_is_live_only_once_there_is_a_delivered_deck():
    assert present_button(False).disabled is True
    assert present_button(True).disabled is False
    assert present_button(True).id == {"type": "qs-present", "op": "open"}


def test_the_generated_deck_top_bar_offers_present_beside_export():
    bar = _placeholder_topbar(enabled=True)
    ids = [n.id for n in _walk(bar) if isinstance(getattr(n, "id", None), dict)]
    assert {"type": "qs-present", "op": "open"} in ids
    assert {"type": "qs-export", "loc": "top"} in ids


# ── which pages, and their pictures ──────────────────────────────────────────


def test_the_show_follows_the_deck_order_and_leaves_hidden_pages_out():
    show = SS.build_slideshow(_tdoc(order=[2, 0, 1, 3, 4, 5], hidden=[3]))
    assert [s.image_url for s in show.slides] == [
        "/assets/render-2.png", "/assets/render-0.png", "/assets/render-1.png",
        "/assets/render-4.png", "/assets/render-5.png",
    ]
    assert all(s.title for s in show.slides)


def test_a_page_nobody_has_looked_at_is_rendered_before_the_show_opens(monkeypatch):
    asked = {}

    def render(path, count, *, only=None, **kwargs):
        asked["only"] = sorted(only)
        return [f"/assets/fresh-{i}.png" if i in only else None for i in range(count)]

    monkeypatch.setattr(PA, "ensure_rendered_slide_backgrounds", render)
    urls = [f"/assets/render-{i}.png" for i in range(6)]
    urls[1] = urls[4] = None
    show = SS.build_slideshow(_tdoc(background_urls=urls))
    assert asked["only"] == [1, 4]
    assert show.slides[1].image_url == "/assets/fresh-1.png"
    assert show.slides[4].image_url == "/assets/fresh-4.png"


def test_a_failed_render_presents_the_page_title_instead_of_crashing(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("PowerPoint is busy")

    monkeypatch.setattr(PA, "ensure_rendered_slide_backgrounds", broken)
    urls = [f"/assets/render-{i}.png" for i in range(6)]
    urls[2] = None
    show = SS.build_slideshow(_tdoc(background_urls=urls))
    assert show.slides[2].image_url is None
    overlay = slideshow_overlay(show)
    missing = _with_class(overlay, "qs-present-missing-title")
    assert [m.children for m in missing] == [show.slides[2].title]


def test_a_single_filled_template_never_renders_the_unfilled_file():
    urls = [None] * 6
    # The autouse renderer raises if called: a non-assembled doc must not ask for one.
    show = SS.build_slideshow(_tdoc(assembled=False, background_urls=urls))
    assert all(s.image_url is None for s in show.slides)


def test_an_edited_page_is_presented_with_its_edits(monkeypatch):
    drawn = []

    def edited(path, edits, page, count, **kwargs):
        drawn.append(page)
        return f"/assets/edited-{page}.png"

    monkeypatch.setattr(SS, "edited_slide_url", edited)
    show = SS.build_slideshow(_tdoc(**{TE.EDITS_KEY: {"2:5": ["New words"]}}))
    assert drawn == [2]
    assert show.slides[2].image_url == "/assets/edited-2.png"
    assert not show.slides[2].edits_not_shown


def test_edits_that_could_not_be_drawn_are_flagged_not_hidden(monkeypatch):
    monkeypatch.setattr(SS, "edited_slide_url", lambda *a, **k: None)
    show = SS.build_slideshow(_tdoc(**{TE.EDITS_KEY: {"2:5": ["New words"]}}))
    assert show.slides[2].image_url == "/assets/render-2.png"
    assert show.slides[2].edits_not_shown
    notes = _with_class(slideshow_overlay(show), "qs-present-note")
    assert len(notes) == 1


# ── the overlay ──────────────────────────────────────────────────────────────


def test_the_show_opens_on_one_page_and_numbers_every_page():
    show = SS.build_slideshow(_tdoc(), start=3)
    overlay = slideshow_overlay(show)
    pages = _with_class(overlay, "qs-present-slide")
    assert len(pages) == 6
    assert [i for i, p in enumerate(pages) if "is-current" in p.className] == [3]
    counts = [c.children for c in _with_class(overlay, "qs-present-count")]
    assert counts == [f"{n} / 6" for n in range(1, 7)]
    close = [n for n in _walk(overlay) if getattr(n, "id", None) == {"type": "qs-present", "op": "close"}]
    assert len(close) == 1


def test_an_out_of_range_start_opens_on_page_one():
    assert SS.build_slideshow(_tdoc(), start=40).start == 0
    assert SS.clamp_start("x", 5) == 0


def test_presenting_from_the_canvas_starts_on_the_page_being_edited():
    assert present_cb.show_start({"mode": "canvas", "idx": 4}) == 4
    assert present_cb.show_start({"mode": "review", "idx": 4}) == 0
    assert present_cb.show_start(None) == 0


# ── the callback ─────────────────────────────────────────────────────────────


def test_open_lays_the_show_and_close_takes_it_down(monkeypatch):
    monkeypatch.setattr(present_cb, "usable_tdoc", lambda doc: doc)
    opened = present_cb.slideshow_for("open", _tdoc(), {"mode": "canvas", "idx": 2})
    pages = _with_class(opened, "qs-present-slide")
    assert len(pages) == 6 and "is-current" in pages[2].className
    assert present_cb.slideshow_for("close", _tdoc(), None) is None


def test_there_is_no_show_without_a_delivered_deck(monkeypatch):
    monkeypatch.setattr(present_cb, "usable_tdoc", lambda doc: None)
    assert present_cb.slideshow_for("open", _tdoc(), None) is None


def test_both_buttons_drive_the_one_host_that_outlives_a_mode_switch():
    import dash

    from studio.authoring.layout import studio_chrome

    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    present_cb.register_present(app)
    (callback,) = [c for k, c in app.callback_map.items() if "qs-present-host" in k]
    (trigger,) = callback["inputs"]
    assert '"type":"qs-present"' in str(trigger["id"]).replace(" ", "").replace("'", '"')
    hosts = [n for n in _walk(studio_chrome()) if getattr(n, "id", None) == "qs-present-host"]
    assert len(hosts) == 1


# ── the browser side ─────────────────────────────────────────────────────────


def test_the_page_turning_script_and_styles_ship_with_the_app():
    script = (ASSETS / "studio_present.js").read_text(encoding="utf-8")
    for needle in ("ArrowRight", "ArrowLeft", "Escape", "requestFullscreen",
                   "fullscreenchange", ".qs-present-close"):
        assert needle in script
    css = (ASSETS / "studio_present.css").read_text(encoding="utf-8")
    assert ".qs-present-slide.is-current" in css
