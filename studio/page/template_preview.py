"""Geometry-based, editable preview of the FILLED template (no LibreOffice).

Re-creates each template slide in HTML from the cached ``Template`` geometry and
overlays the materialized field values — so the screen mirrors what ``fill.py``
writes into the ``.pptx`` (same ``materialize_fields(doc)`` source = screen↔PPT
parity). Filled slots are editable inputs; unmapped slots show a placeholder chip;
non-slot shapes render read-only for context. A per-slide "add note" appends a free
text element that the fill engine also lays down.

Also hosts the template Review (live validation + Re-validate / Auto-fix) and the
Export panel.
"""
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from dash import dcc, html

from studio.template_fill import registry
from studio.template_fill import validate as TV
from studio.template_fill.fill import _label_subs
from studio.template_fill.model import materialize_fields
from studio.template_fill.preview_assets import cached_doc_backgrounds

PREVIEW_W = 900  # px — the on-screen slide width; height derives from the aspect ratio


def _emu_to_px(value: int, scale: float) -> float:
    return max(0.0, float(value) * scale)


def _apply_subs(text: str, subs) -> str:
    for pattern, repl in subs:
        text = pattern.sub(repl, text)
    return text


def _is_dark(hexstr: Optional[str]) -> bool:
    if not hexstr or len(hexstr) != 6:
        return False
    r, g, b = (int(hexstr[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.5


def _font_px(shape, scale: float, w_px: float, h_px: float, *, rendered_background: bool = False) -> Optional[float]:
    if not getattr(shape, "font_size_pt", None):
        return None
    # One point is 12700 EMU, so this keeps browser text scaled in the same
    # coordinate system as the slide geometry.
    exact = max(5.0, float(shape.font_size_pt) * 12700.0 * scale)
    if rendered_background:
        return exact

    # Geometry fallback has no PowerPoint text engine/autofit. Clamp the extracted
    # font size to the available box so fallback previews stay readable instead of
    # spilling across neighbouring template regions.
    lines = [p.strip() for p in getattr(shape, "paragraphs", []) if p and p.strip()]
    line_count = max(1, len(lines))
    longest = max((len(line) for line in lines), default=12)
    height_cap = h_px / max(1.3, line_count * 1.18)
    width_cap = w_px / max(8.0, longest * 0.52)
    return max(6.0, min(exact, height_cap, width_cap, 22.0))


# ── one shape → positioned HTML ──────────────────────────────────────────────


def _edit_input(slot_key: str, value: str, placeholder: bool, *, render_overlay: bool = False) -> dcc.Input:
    # The value is ALWAYS the materialized text (placeholder slots show their token);
    # the app only persists an override when the committed value actually differs, so
    # untouched placeholders never become spurious "filled" values.
    return dcc.Input(
        id={"type": "qs-tf-edit", "key": slot_key},
        value=value,
        debounce=True,                       # commit on blur / Enter
        className=(
            "qs-tf-input"
            + (" placeholder" if placeholder else "")
            + (" render-overlay" if render_overlay else "")
        ),
    )


def _text_shape(shape, fields_by_target, subs) -> Optional[html.Div]:
    """Read-only text: filled values and static labels render as text (editing lives
    in the side panel, so the slide stays a clean preview)."""
    children: List[Any] = []
    for i, para in enumerate(shape.paragraphs):
        fld = fields_by_target.get((shape.shape_id, ("para", i)))
        if fld:
            cls = "qs-tf-static" + (" is-filled" if fld["filled"] else " is-ph")
            text = str(fld["text"]) if fld["filled"] else _apply_subs(str(fld["token"]), subs)
            children.append(html.Div(text, className=cls))
        elif para.strip():
            children.append(html.Div(_apply_subs(para, subs), className="qs-tf-static"))
    if not children:
        return None
    return html.Div(children, className="qs-tf-shape")


def _table_shape(shape, fields_by_target, slide_idx, subs) -> Optional[html.Div]:
    rows = []
    for r, row in enumerate(shape.table or []):
        cells = []
        for c, cell in enumerate(row):
            fld = fields_by_target.get((shape.shape_id, ("cell", r, c)))
            if fld:
                text = str(fld["text"]) if fld["filled"] else _apply_subs(str(fld["token"]), subs)
                cells.append(html.Td(text, className="qs-tf-td" + (" is-filled" if fld["filled"] else "")))
            else:
                cells.append(html.Td(_apply_subs(cell, subs), className="qs-tf-th" if r == 0 else ""))
        rows.append(html.Tr(cells))
    return html.Div(html.Table(html.Tbody(rows), className="qs-tf-table"), className="qs-tf-shape")


def _chart_manual_cue() -> Any:
    """A small badge marking a chart the engine cannot auto-fill (think-cell/linked),
    so the user knows to update its data by hand in PowerPoint."""
    return html.Div(
        [html.I(className="bi bi-exclamation-triangle-fill"), " Manual chart"],
        className="qs-tf-chart-cue",
        title="This chart is think-cell / externally linked — its data can't be filled "
              "automatically. The preview shows the live figures; update the chart in PowerPoint.",
    )


def _chart_svg(shape, values, w_px, h_px) -> Any:
    """A populated mini chart: the per-LoB growth quadrant for scatter/bubble, else a
    small bar of the template's own series — so the preview shows DATA, not a stub."""
    is_quadrant = any(k in (shape.chart_type or "") for k in ("XY_SCATTER", "BUBBLE"))
    cue = [_chart_manual_cue()] if getattr(shape, "chart_external", False) else []
    pts = (values.get("growth_bubble") or {}).get("points", []) if is_quadrant else []
    pad = 6
    iw, ih = max(40, w_px - 2 * pad), max(30, h_px - 2 * pad)
    if is_quadrant and pts:
        xs = [p.get("marsh_yoy") or 0 for p in pts]
        ys = [p.get("carrier_yoy") or 0 for p in pts]
        lo, hi = min(xs + ys + [0]), max(xs + ys + [0]) or 1
        rng = (hi - lo) or 1

        def sx(v): return pad + (v - lo) / rng * iw
        def sy(v): return pad + ih - (v - lo) / rng * ih

        x0, y0 = sx(0), sy(0)  # the axes split the plot into four growth quadrants
        # carrier (y) vs marsh (x): TL carrier↑/marsh↓ (light green), TR both↑ (green),
        # BL both↓ (red), BR carrier↓/marsh↑ (light red).
        quad = lambda l, t, w, h, c: html.Div(className="qs-tf-quad", style={
            "left": f"{l:.0f}px", "top": f"{t:.0f}px", "width": f"{max(0,w):.0f}px",
            "height": f"{max(0,h):.0f}px", "background": c})
        quads = [
            quad(pad, pad, x0 - pad, y0 - pad, "#E4F4E7"),                       # TL light green
            quad(x0, pad, pad + iw - x0, y0 - pad, "#BFE3C6"),                   # TR green
            quad(pad, y0, x0 - pad, pad + ih - y0, "#E8B7B7"),                   # BL red
            quad(x0, y0, pad + iw - x0, pad + ih - y0, "#F6DCDC"),              # BR light red
        ]
        dots = []
        for p in pts:
            cx, cy = sx(p.get("marsh_yoy") or 0), sy(p.get("carrier_yoy") or 0)
            dots.append(html.Div(title=str(p.get("lob")), className="qs-tf-dot",
                                 style={"left": f"{cx:.0f}px", "top": f"{cy:.0f}px"}))
        diag = html.Div(className="qs-tf-diag",
                        style={"left": f"{pad}px", "top": f"{pad}px",
                               "width": f"{iw:.0f}px", "height": f"{ih:.0f}px"})
        return html.Div([*quads, diag, *dots, *cue], className="qs-tf-chartwrap")
    # Fallback: render the template's first series as proportional bars.
    series = shape.chart_series[0][1] if shape.chart_series else []
    if series:
        m = max(abs(v) for v in series) or 1
        bars = [html.Div(className="qs-tf-bar2",
                         style={"height": f"{abs(v) / m * ih:.0f}px"}) for v in series[:12]]
        return html.Div([*bars, *cue], className="qs-tf-bars")
    return html.Div([html.I(className="bi bi-bar-chart"), " chart", *cue], className="qs-tf-stub")


def _render_shape(shape, fields_by_target, scale, slide_idx, values, subs, *, rendered_background: bool = False) -> Optional[html.Div]:
    if shape.w <= 0 or shape.h <= 0:
        return None
    w_px, h_px = _emu_to_px(shape.w, scale), _emu_to_px(shape.h, scale)
    style = {
        "left": f"{_emu_to_px(shape.x, scale):.0f}px",
        "top": f"{_emu_to_px(shape.y, scale):.0f}px",
        "width": f"{w_px:.0f}px",
        "height": f"{h_px:.0f}px",
    }
    cls = "qs-tf-box"
    # Over a pixel-perfect PNG, only non-text decoration would differ — text/tables
    # are already in the image, so skip them (the side panel handles editing).
    if rendered_background and shape.kind in ("table", "text", "chart", "picture", "ole"):
        return None
    if shape.kind == "table" and shape.table:
        inner = _table_shape(shape, fields_by_target, slide_idx, subs)
        if inner is None:
            return None
    elif shape.kind == "chart":
        inner = _chart_svg(shape, values, w_px, h_px)
        cls += " is-chart"
    elif shape.kind == "text":
        inner = _text_shape(shape, fields_by_target, subs)
        if inner is None:
            # An empty shape that is purely a coloured panel (e.g. a full-slide navy
            # divider background) still renders as its fill.
            if shape.fill_color and not rendered_background:
                inner = ""
            else:
                return None
        if shape.fill_color and not rendered_background:
            style["background"] = f"#{shape.fill_color}"
            style["color"] = "#fff" if _is_dark(shape.fill_color) else "#0b1f44"
        if shape.font_color and not shape.fill_color:
            style["color"] = f"#{shape.font_color}"
        font_px = _font_px(shape, scale, w_px, h_px, rendered_background=rendered_background)
        if font_px:
            style["fontSize"] = f"{font_px:.1f}px"
        if shape.font_face:
            style["fontFamily"] = f"{shape.font_face}, Arial, sans-serif"
        if shape.bold:
            style["fontWeight"] = "700"
        if shape.italic:
            style["fontStyle"] = "italic"
        if shape.align:
            style["textAlign"] = shape.align
    elif shape.kind == "picture" and shape.image_url and not rendered_background:
        inner = html.Img(src=shape.image_url, className="qs-tf-img")
        cls += " is-picture"
    elif shape.kind in ("picture", "ole"):
        if rendered_background:
            return None
        label = {"picture": "Image", "ole": "think-cell"}.get(shape.kind, shape.kind)
        inner = html.Div([html.I(className="bi bi-image"), f" {label}"], className="qs-tf-stub")
    elif shape.fill_color and not rendered_background:
        inner = ""
        style["background"] = f"#{shape.fill_color}"
    else:
        return None
    return html.Div(inner, className=cls, style=style)


# ── edit panel (the real-app editing surface) ────────────────────────────────

_ROLE_LABEL = {
    "subject_name": "Carrier name", "marsh_gwp": "Marsh GWP", "marsh_gwp_yoy": "Marsh GWP YoY",
    "carrier_gwp": "Carrier GWP", "carrier_gwp_yoy": "Carrier GWP YoY", "sow_pct": "Share of wallet",
    "sow_yoy": "SoW change", "rank": "Market rank", "rank_yoy": "Rank change",
    "growth_bubble": "Growth chart",
}


def _field_label(fld: Dict[str, Any]) -> str:
    role = fld.get("role") or ""
    if role.startswith("country_name"):
        n = role[role.find("[") + 1:role.find("]")]
        return f"Country {int(n) + 1}" if n.isdigit() else "Country"
    if role in _ROLE_LABEL:
        return _ROLE_LABEL[role]
    tok = (fld.get("token") or "").strip()
    return (tok[:22] + "…") if len(tok) > 22 else (tok or "Text")


def _fields_panel(slide_fields: List[Dict[str, Any]]) -> html.Div:
    """A labelled, scrollable editor for every fillable value on the current slide —
    the 'real application' editing surface (no hunting transparent boxes on the slide)."""
    editable = [f for f in slide_fields if f["value_kind"] != "series"]
    if not editable:
        body: Any = html.Div("No editable fields on this slide.", className="qs-tf-fp-empty")
    else:
        rows = []
        for fld in sorted(editable, key=lambda f: (not f["filled"], _field_label(f).lower())):
            key = f"{fld['slide_idx']}:{fld['shape_id']}:{'-'.join(str(p) for p in fld['where'])}"
            rows.append(html.Div(
                [
                    html.Div(
                        [html.Span(_field_label(fld), className="qs-tf-fp-label"),
                         html.Span("placeholder" if fld["placeholder"] else "data",
                                   className="qs-tf-fp-tag" + ("" if fld["placeholder"] else " ok"))],
                        className="qs-tf-fp-head",
                    ),
                    dcc.Input(
                        id={"type": "qs-tf-edit", "key": key},
                        value="" if fld["placeholder"] else str(fld["text"]),
                        placeholder=str(fld["token"]) if fld["placeholder"] else "",
                        debounce=True,
                        className="qs-tf-fp-input",
                    ),
                ],
                className="qs-tf-fp-row",
            ))
        body = html.Div(rows, className="qs-tf-fp-list")
    return html.Div(
        [
            html.Div([html.I(className="bi bi-pencil-square"), " Edit fields"], className="qs-tf-fp-title"),
            html.Div("Type a value to fill or override; blank a field to clear it.", className="qs-tf-fp-note"),
            body,
        ],
        className="qs-tf-fp",
    )


# ── slide + body ─────────────────────────────────────────────────────────────


def template_preview_body(tdoc: Mapping[str, Any], view: Mapping[str, Any]) -> html.Div:
    template, _ = registry.derive_manifest(tdoc["template_path"])
    fields = materialize_fields(dict(tdoc))
    stored_urls = list(tdoc.get("background_urls") or [])
    cached_urls = cached_doc_backgrounds(dict(tdoc), len(template.slides))
    # Assembled decks cache their renders per FILE (not per doc-values) — consult that
    # store too, so a render that failed at generate time but succeeded later (e.g. the
    # user's own PowerPoint stopped hogging COM) still replaces the geometry fallback.
    if not any(cached_urls) and tdoc.get("assembled"):
        from studio.template_fill.preview_assets import _cached_backgrounds

        cached_urls = _cached_backgrounds(tdoc["template_path"], len(template.slides))
    rendered_urls = [
        (stored_urls[i] if i < len(stored_urls) and stored_urls[i] else cached_urls[i])
        for i in range(len(template.slides))
    ]
    order = [i for i in tdoc.get("order", list(range(len(template.slides)))) if i not in tdoc.get("hidden", [])]
    pos = int(view.get("idx", 0))
    pos = pos if 0 <= pos < len(order) else 0
    idx = order[pos] if order else 0
    slide = template.slides[idx]

    scale = PREVIEW_W / float(template.width_emu or 12192000)
    height = template.height_emu * scale
    values = dict(tdoc.get("values", {}))
    subs = _label_subs(values)
    by_target = {(f["shape_id"], tuple(f["where"])): f
                 for f in fields.values() if f["slide_idx"] == idx}

    background_url = rendered_urls[idx] if idx < len(rendered_urls) else getattr(slide, "background_url", None)
    rendered_background = bool(background_url)
    shapes = [
        s for s in (
            _render_shape(sh, by_target, scale, idx, values, subs, rendered_background=rendered_background)
            for sh in slide.shapes
        )
        if s
    ]
    surface_style = {"width": f"{PREVIEW_W}px", "height": f"{height:.0f}px"}
    surface_cls = "qs-tf-surface"
    if rendered_background:
        surface_style.update({
            "backgroundImage": f"url('{background_url}')",
            "backgroundSize": "100% 100%",
            "backgroundRepeat": "no-repeat",
        })
        surface_cls += " has-rendered-bg"
    surface = html.Div(
        shapes,
        className=surface_cls,
        style=surface_style,
    )

    filled = sum(1 for f in fields.values() if f["slide_idx"] == idx and f["filled"])
    placeholders = sum(1 for f in fields.values() if f["slide_idx"] == idx and f["placeholder"])
    slide_fields = [f for f in fields.values() if f["slide_idx"] == idx]
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Button(html.I(className="bi bi-chevron-left"),
                                        id={"type": "qs-goto", "idx": max(0, pos - 1), "src": "tf"},
                                        className="qs-tf-addbtn", disabled=pos == 0),
                            html.Button(html.I(className="bi bi-chevron-right"),
                                        id={"type": "qs-goto", "idx": min(len(order) - 1, pos + 1), "src": "tf"},
                                        className="qs-tf-addbtn", disabled=pos >= len(order) - 1),
                            html.Span([html.I(className="bi bi-easel"),
                                       f" Slide {pos + 1} of {len(order)} · {slide.title() or slide.layout}"],
                                      className="qs-tf-title"),
                        ],
                        className="qs-tf-actions",
                    ),
                    html.Div(
                        [html.Span([html.I(className="bi bi-check2-circle"), f" {filled} filled"], className="qs-tf-pill ok"),
                         html.Span([html.I(className="bi bi-dash-circle"), f" {placeholders} placeholder"], className="qs-tf-pill warn"),
                         html.Span([html.I(className="bi bi-image"), " exact render" if rendered_background else " geometry preview"],
                                   className="qs-tf-pill ok" if rendered_background else "qs-tf-pill"),
                         html.Button([html.I(className="bi bi-plus-lg"), " Add note"],
                                     id={"type": "qs-tf-add", "slide": idx}, className="qs-tf-addbtn")],
                        className="qs-tf-actions",
                    ),
                ],
                className="qs-tf-bar",
            ),
            html.Div(
                [
                    html.Div(surface, className="qs-tf-stage"),
                    _fields_panel(slide_fields),
                ],
                className="qs-tf-workspace",
            ),
        ],
        className="qs-tf-preview",
    )


# ── Review (live validation + re-run) ────────────────────────────────────────


def template_review_body(tdoc: Mapping[str, Any]) -> html.Div:
    issues = TV.validate_doc(dict(tdoc))
    counts = TV.summary(dict(tdoc))
    fields = materialize_fields(dict(tdoc))
    filled = sum(1 for f in fields.values() if f["filled"])
    mapped = sum(1 for f in fields.values() if f["role"])
    clean = counts["total"] == 0

    rows = [
        html.Div(
            [
                html.I(className=f"bi {'bi-exclamation-octagon' if i['severity'] == 'error' else 'bi-exclamation-triangle'} qs-chk-icon warn"),
                html.Div([
                    html.Div(f"Slide {i['slide_idx'] + 1} · {i['category']}", className="qs-chk-label"),
                    html.Div(i["message"], className="qs-chk-detail"),
                ]),
                (html.Span("auto-fixable", className="qs-tf-pill ok") if i["auto_fixable"] else html.Span()),
            ],
            className="qs-chk-row warn",
        )
        for i in issues
    ]
    if clean:
        rows = [html.Div([html.I(className="bi bi-check-circle-fill qs-chk-icon ok"),
                          html.Div([html.Div("All mapped values resolved", className="qs-chk-label"),
                                    html.Div(f"{filled} filled · {mapped} mapped · no validation errors", className="qs-chk-detail")])],
                         className="qs-chk-row")]

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div([html.I(className="bi bi-patch-check"), "Validation"], className="qs-panel-title"),
                            html.Div(f"{counts['total']} issue(s) · {counts['auto_fixable']} auto-fixable",
                                     className="qs-review-score" + (" ok" if clean else "")),
                        ],
                        className="qs-review-head",
                    ),
                    html.Div(rows, className="qs-chk-list"),
                    html.Div(
                        [
                            html.Button([html.I(className="bi bi-arrow-repeat"), " Re-validate"],
                                        id={"type": "qs-tf-revalidate"}, className="qs-tf-addbtn"),
                            html.Button([html.I(className="bi bi-magic"), " Auto-fix & re-run"],
                                        id={"type": "qs-tf-autofix"}, className="qs-review-cta",
                                        disabled=counts["auto_fixable"] == 0),
                        ],
                        className="qs-tf-actions",
                    ),
                ],
                className="qs-review-card",
            ),
            # Export folded into Review (Export is no longer its own mode): the
            # summary + download button, served by the same ``qs-export`` callback.
            html.Div(
                [
                    html.Div([html.I(className="bi bi-filetype-pptx"), "Export"], className="qs-panel-title"),
                    html.P(f"The exported deck IS your template, filled in: {filled} values mapped, "
                           f"{counts['total']} open validation issue(s). Placeholders you didn't map "
                           f"are preserved exactly as authored.", className="qs-preview-note"),
                    html.Button([html.I(className="bi bi-download"), " Export PPTX"],
                                id={"type": "qs-export", "loc": "panel"}, className="qs-review-cta"),
                ],
                className="qs-review-card qs-export-card",
            ),
        ],
        className="qs-review",
    )
