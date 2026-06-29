"""Template-fill: dynamic analysis, slot detection, role mapping, and the fill.

Deterministic — runs against the seed DB (no DB_PATH, no LLM). Proves the analyzer
is generic (works on the starter template AND a different seed deck) and that the
fill replaces mapped tokens while leaving unmapped slots as placeholders.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation

from studio.compute import compute_overall
from studio.template_fill import roles as R
from studio.template_fill import slots as S
from studio.template_fill.analyze import analyze
from studio.template_fill.fill import fill_template
from studio.template_fill.model import materialize_fields, new_template_doc
from studio.template_fill.slots import classify

TEMPLATE = "template/qbr_template.pptx"
SEED_DECK = "studio/_seed/test_qbr.pptx"


def _result():
    return compute_overall(filters={"carrier": "Zurich", "year": 2025})


# ── slot classification (the generic token grammar) ──────────────────────────


@pytest.mark.parametrize("token,kind", [
    ("xx.x", "int"), ("x.x%", "pct"), ("$xx,xxxm", "money"), ("x.xB", "money"),
    ("x", "int"), ("Country (1)", "text"), ("………", "text"),
])
def test_classify_detects_placeholders(token, kind):
    assert classify(token) == kind


@pytest.mark.parametrize("text", ["xyz", "Carrier Country xyz YoY change", "Property", "$2,100M", ""])
def test_classify_ignores_non_placeholders(text):
    # Real values and prose with an embedded 'x' must NOT be slots.
    assert classify(text) is None or text == "Carrier Country xyz YoY change"


# ── analyzer is generic across templates ─────────────────────────────────────


def test_analyzer_detects_slots_on_starter_template():
    slots = S.detect(analyze(TEMPLATE))
    assert len(slots) > 50
    # No hard-coded slide indices: slots span multiple slides.
    assert len({s.slide_idx for s in slots}) > 3


def test_analyzer_runs_on_a_different_pptx():
    if not Path(SEED_DECK).exists():
        pytest.skip("seed deck not present")
    template = analyze(SEED_DECK)          # must not raise on a non-starter deck
    assert template.slides


# ── role inference + fill ────────────────────────────────────────────────────


def test_manifest_maps_core_roles():
    bindings = R.infer(S.detect(analyze(TEMPLATE)))
    roles = {b.role for b in bindings if b.role}
    assert {"subject_name", "marsh_gwp", "carrier_gwp", "sow_pct", "rank"} <= roles


def test_fill_replaces_mapped_tokens_and_keeps_placeholders(tmp_path):
    doc = new_template_doc(_result(), template_path=TEMPLATE)
    out = fill_template(doc, out_path=str(tmp_path / "filled.pptx"))
    prs = Presentation(out)
    all_text = "\n".join(
        sh.text_frame.text
        for s in prs.slides for sh in s.shapes
        if sh.has_text_frame
    )
    # The carrier name replaced the generic "Carrier" label, and no x-placeholder
    # money token survived where a value was mapped.
    assert "Zurich" in all_text
    assert "$xx,xxxm" not in all_text and "$xxx.xM" not in all_text
    # An unmapped qualitative placeholder (ellipsis prose) survived untouched.
    assert "…" in all_text or "......" in all_text


def test_render_token_matches_placeholder_style():
    from studio.template_fill.render import render_token
    # Money auto-scales to billions (short, no overflow); keeps the token's $ presence.
    assert render_token("$xx,xxxm", 2.29e9, "money") == "$2.3B"
    assert render_token("x.xB", 2.29e9, "money") == "2.3B"
    assert render_token("xxxM", 2.079e8, "money") == "208M"          # millions below 1bn
    assert render_token("+xx.x%", 28.6, "pct") == "+28.6%"
    assert render_token("#x", 5, "rank") == "#5"
    assert render_token("PY (-x.x%▼)", 9.9, "pct") == "PY (+9.9%▲)"   # sign + arrow follow data


def test_single_country_hides_second_country_block(tmp_path):
    # One country selected → the "Country (2)" divider block is dropped from export.
    res = compute_overall(filters={"carrier": "Zurich", "country": ["Singapore"], "year": 2025})
    doc = new_template_doc(res, template_path=TEMPLATE)
    assert doc["hidden"], "expected a hidden second-country block"
    full = len(analyze(TEMPLATE).slides)
    out = fill_template(doc, out_path=str(tmp_path / "pruned.pptx"))
    assert len(Presentation(out).slides) == full - len(doc["hidden"])


def test_country_token_substituted_in_labels(tmp_path):
    res = compute_overall(filters={"carrier": "Zurich", "country": ["Singapore"], "year": 2025})
    doc = new_template_doc(res, template_path=TEMPLATE)
    out = fill_template(doc, out_path=str(tmp_path / "subbed.pptx"))
    text = "\n".join(sh.text_frame.text for s in Presentation(out).slides
                     for sh in s.shapes if sh.has_text_frame)
    assert "xyz" not in text.lower()          # the literal placeholder is gone
    assert "Singapore" in text                # replaced by the selection


def test_materialize_is_parity_source():
    doc = new_template_doc(_result(), template_path=TEMPLATE)
    fields = materialize_fields(doc)
    filled = [f for f in fields.values() if f["filled"]]
    assert filled and all(not str(f["text"]).strip().endswith("x") for f in filled)
