from __future__ import annotations

from studio.page import template_preview as TP
from studio.template_fill.analyze import Slide, Template


def test_template_preview_uses_cached_background_without_rendering(monkeypatch):
    template = Template(
        path="assembled.pptx",
        width_emu=12192000,
        height_emu=6858000,
        slides=[Slide(index=0, layout="blank")],
    )
    monkeypatch.setattr(TP.registry, "derive_manifest", lambda path: (template, []))
    monkeypatch.setattr(TP, "materialize_fields", lambda doc: {})
    monkeypatch.setattr(TP, "cached_doc_backgrounds", lambda doc, slide_count: ["/assets/cached.png"])

    body = TP.template_preview_body(
        {
            "template_path": "assembled.pptx",
            "values": {},
            "manifest": [],
            "hidden": [],
            "order": [0],
            "background_urls": ["/assets/pre-rendered.png"],
        },
        {"idx": 0},
    )

    stage = body.children[1].children[0].children
    assert stage.style["backgroundImage"] == "url('/assets/pre-rendered.png')"
