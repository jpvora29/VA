"""What each paragraph of a text box looks like, resolved the way PowerPoint does.

The canvas draws an author's retyped words over the exact render of the slide, so the
new words have to look like the ones they replace: the same size, colour, weight,
bullet and indent, paragraph by paragraph. Almost none of that is written on the run
itself — it is inherited. PowerPoint looks, most specific first, at:

1. the run's ``a:rPr`` and the paragraph's ``a:pPr``;
2. the shape's own ``a:lstStyle`` (level ``lvlNpPr``);
3. for a placeholder: the layout's placeholder, the master's placeholder, then the
   master's ``p:txStyles`` (title / body / other);
4. for any other shape: the theme's ``a:objectDefaults/a:txDef`` and the
   presentation's ``p:defaultTextStyle``.

This module walks that chain once per paragraph and returns plain values. Pure reading:
it never changes a file, and a malformed piece of XML costs that one value only.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pptx.oxml.ns import qn

EMU_PER_PT = 12700

# Glyphs a symbol font draws for the bullet characters templates actually use. Drawn in
# a browser font, "§" would read as a section sign instead of Wingdings' square.
_SYMBOL_BULLETS = {
    "wingdings": {"§": "■", "n": "■", "l": "●", "Ø": "➢", "ü": "✓", "q": "❑",
                  "v": "❖", "Ÿ": "•", "o": "□", "w": "◆", "à": "➔", "Ü": "➢", "è": "➔"},
    "symbol": {"·": "•", "": "•"},
}

_ALIGN = {"l": "left", "ctr": "center", "r": "right", "just": "justify", "dist": "justify"}
_ANCHOR = {"t": "top", "ctr": "middle", "b": "bottom"}
_PRESET_COLORS = {"black": "000000", "white": "FFFFFF", "red": "FF0000", "blue": "0000FF",
                  "green": "008000", "yellow": "FFFF00", "gray": "808080"}


@dataclass(frozen=True)
class ParaStyle:
    """The resolved look of one paragraph — every value PowerPoint would use."""

    level: int = 0
    size_pt: Optional[float] = None
    color: Optional[str] = None             # hex, no '#'
    bold: bool = False
    italic: bool = False
    font_face: Optional[str] = None
    align: Optional[str] = None             # left | center | right | justify
    margin_left_pt: float = 0.0
    indent_pt: float = 0.0                  # first line; negative = hanging bullet
    bullet: str = ""                        # a glyph, "" for none
    bullet_color: Optional[str] = None
    numbered: str = ""                      # autonumber scheme, e.g. "arabicPeriod"
    number_start: int = 1
    space_before_pt: float = 0.0
    space_after_pt: float = 0.0
    line_spacing: Optional[float] = None    # multiple of single spacing


@dataclass(frozen=True)
class BodyStyle:
    """The text box around the paragraphs: insets, vertical anchor, autofit shrink."""

    inset_left_pt: float = 7.2
    inset_top_pt: float = 3.6
    inset_right_pt: float = 7.2
    inset_bottom_pt: float = 3.6
    anchor: str = "top"
    font_scale: float = 1.0


@dataclass(frozen=True)
class ThemeContext:
    """What a colour or font name means in this deck: the theme scheme and defaults."""

    colors: Mapping[str, str] = field(default_factory=dict)   # dk1/lt1/accent1/tx1/bg1 → hex
    major_font: Optional[str] = None
    minor_font: Optional[str] = None
    defaults: Tuple[Any, ...] = ()        # txDef lstStyle, presentation defaultTextStyle


# ── the theme ────────────────────────────────────────────────────────────────


def theme_context(prs, master) -> ThemeContext:
    """Read ``master``'s theme: scheme colours (with the clrMap aliases) and fonts."""
    from lxml import etree

    colors: Dict[str, str] = {}
    major = minor = None
    defaults: List[Any] = []
    try:
        theme = etree.fromstring(master.part.part_related_by(
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme").blob)
        scheme = theme.find(".//" + qn("a:clrScheme"))
        for child in (scheme if scheme is not None else ()):
            value = _color_value(child)
            if value:
                colors[etree.QName(child).localname] = value
        cmap = master.element.find(qn("p:clrMap"))
        for alias, slot in (dict(cmap.attrib) if cmap is not None else {}).items():
            if slot in colors:
                colors[alias] = colors[slot]
        major = _typeface(theme.find(".//" + qn("a:majorFont")))
        minor = _typeface(theme.find(".//" + qn("a:minorFont")))
        tx_def = theme.find(".//" + qn("a:objectDefaults") + "/" + qn("a:txDef") + "/" + qn("a:lstStyle"))
        if tx_def is not None:
            defaults.append(tx_def)
    except Exception:  # noqa: BLE001 — an unreadable theme leaves the defaults to the caller
        pass
    default_style = prs.element.find(qn("p:defaultTextStyle"))
    if default_style is not None:
        defaults.append(default_style)
    return ThemeContext(colors=colors, major_font=major, minor_font=minor, defaults=tuple(defaults))


def _typeface(font_el) -> Optional[str]:
    latin = font_el.find(qn("a:latin")) if font_el is not None else None
    return latin.get("typeface") if latin is not None else None


def _color_value(slot) -> Optional[str]:
    """The hex a theme scheme slot holds (``a:srgbClr`` or a system colour's last value)."""
    srgb, sysc = slot.find(qn("a:srgbClr")), slot.find(qn("a:sysClr"))
    if srgb is not None:
        return (srgb.get("val") or "").upper() or None
    if sysc is not None:
        return (sysc.get("lastClr") or "").upper() or None
    return None


# ── colours ──────────────────────────────────────────────────────────────────


def _adjust(hexv: str, color_el) -> str:
    """Apply ``lumMod``/``lumOff``/``tint``/``shade`` — how templates say "75% navy"."""
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (0, 2, 4))
    for mod in color_el:
        tag = mod.tag.split("}")[-1]
        try:
            val = int(mod.get("val")) / 100000
        except (TypeError, ValueError):
            continue
        if tag in ("lumMod", "lumOff"):
            h, lum, s = colorsys.rgb_to_hls(r, g, b)
            lum = lum * val if tag == "lumMod" else lum + val
            r, g, b = colorsys.hls_to_rgb(h, min(max(lum, 0.0), 1.0), s)
        elif tag == "shade":
            r, g, b = r * val, g * val, b * val
        elif tag == "tint":
            r, g, b = (c + (1 - c) * (1 - val) for c in (r, g, b))
    return "".join(f"{round(min(max(c, 0.0), 1.0) * 255):02X}" for c in (r, g, b))


def resolve_color(parent, theme: ThemeContext) -> Optional[str]:
    """The hex a ``solidFill`` / ``buClr`` element names, theme colours resolved."""
    if parent is None:
        return None
    for color_el in parent:
        tag = color_el.tag.split("}")[-1]
        base = None
        if tag == "srgbClr":
            base = color_el.get("val")
        elif tag == "schemeClr":
            base = theme.colors.get(color_el.get("val") or "")
        elif tag == "sysClr":
            base = color_el.get("lastClr")
        elif tag == "prstClr":
            base = _PRESET_COLORS.get(color_el.get("val") or "")
        if base and len(base) == 6:
            return _adjust(base.upper(), color_el)
    return None


# ── the inheritance chain ────────────────────────────────────────────────────


def _txbody_lststyle(element) -> Any:
    """The ``a:lstStyle`` of a shape element's text body, if it has one."""
    if element is None:
        return None
    body = element.find(qn("p:txBody"))
    if body is None:
        body = element.find(qn("a:txBody"))
    return body.find(qn("a:lstStyle")) if body is not None else None


def _master_style(master, ph_type: str) -> Any:
    styles = master.element.find(qn("p:txStyles")) if master is not None else None
    if styles is None:
        return None
    if ph_type in ("title", "ctrTitle"):
        return styles.find(qn("p:titleStyle"))
    if ph_type in ("dt", "ftr", "sldNum", "hdr"):
        return styles.find(qn("p:otherStyle"))
    return styles.find(qn("p:bodyStyle"))


def shape_chain(shape, slide, theme: ThemeContext) -> Tuple[Any, ...]:
    """Every list style a text shape inherits from, most specific first."""
    chain: List[Any] = [_txbody_lststyle(shape._element)]
    if getattr(shape, "is_placeholder", False):
        ph = shape._element.ph
        ph_type = (ph.get("type") if ph is not None else None) or "obj"
        try:
            base = shape._base_placeholder              # the layout's placeholder
        except Exception:  # noqa: BLE001
            base = None
        if base is not None:
            chain.append(_txbody_lststyle(base._element))
            try:
                master_ph = base._base_placeholder      # the master's placeholder
            except Exception:  # noqa: BLE001
                master_ph = None
            if master_ph is not None:
                chain.append(_txbody_lststyle(master_ph._element))
        chain.append(_master_style(slide.slide_layout.slide_master, ph_type))
    else:
        chain.extend(theme.defaults)
    return tuple(el for el in chain if el is not None)


def cell_chain(theme: ThemeContext) -> Tuple[Any, ...]:
    """A table cell inherits the presentation defaults (its table style sets little text)."""
    return tuple(el for el in theme.defaults if el is not None)


# ── one paragraph ────────────────────────────────────────────────────────────


def _level_props(chain: Sequence[Any], level: int) -> List[Any]:
    out: List[Any] = []
    for style in chain:
        lvl = style.find(qn(f"a:lvl{level + 1}pPr"))
        if lvl is not None:
            out.append(lvl)
        default = style.find(qn("a:defPPr"))
        if default is not None:
            out.append(default)
    return out


def _first_attr(elements: Sequence[Any], name: str) -> Optional[str]:
    for el in elements:
        value = el.get(name)
        if value is not None:
            return value
    return None


def _first_child(elements: Sequence[Any], *names: str) -> Any:
    for el in elements:
        for name in names:
            child = el.find(qn(name))
            if child is not None:
                return child
    return None


def _run_props(p_el) -> Any:
    """The formatting of the paragraph's first piece of text (run, field, or end mark)."""
    for tag in ("a:r", "a:fld"):
        piece = p_el.find(qn(tag))
        if piece is not None:
            rpr = piece.find(qn("a:rPr"))
            if rpr is not None:
                return rpr
    return p_el.find(qn("a:endParaRPr"))


def _is_true(value: Optional[str]) -> bool:
    return str(value or "").lower() in ("1", "true")


def _font(latin, theme: ThemeContext) -> Optional[str]:
    face = latin.get("typeface") if latin is not None else None
    if face in ("+mj-lt", "+mj-ea", "+mj-cs"):
        return theme.major_font
    if face in ("+mn-lt", "+mn-ea", "+mn-cs"):
        return theme.minor_font
    return face or None


def _bullet(p_props: Sequence[Any]) -> Tuple[str, str, int]:
    """``(glyph, autonumber scheme, start)`` from the first source that says anything."""
    for el in p_props:
        if el.find(qn("a:buNone")) is not None:
            return "", "", 1
        auto = el.find(qn("a:buAutoNum"))
        if auto is not None:
            return "", auto.get("type") or "arabicPeriod", int(auto.get("startAt") or 1)
        char = el.find(qn("a:buChar"))
        if char is not None:
            glyph = char.get("char") or "•"
            font = _first_child(p_props, "a:buFont")
            face = (font.get("typeface") or "").lower() if font is not None else ""
            for family, table in _SYMBOL_BULLETS.items():
                if family in face:
                    return table.get(glyph, "•"), "", 1
            return glyph, "", 1
    return "", "", 1


def _points(value: Optional[str], per_point: float) -> Optional[float]:
    try:
        return int(value) / per_point if value is not None else None
    except ValueError:
        return None


def _spacing(p_props: Sequence[Any], tag: str) -> Tuple[Optional[float], Optional[float]]:
    """``(points, percent)`` for ``a:spcBef`` / ``a:lnSpc`` from the nearest source."""
    node = _first_child(p_props, tag)
    if node is None:
        return None, None
    pts, pct = node.find(qn("a:spcPts")), node.find(qn("a:spcPct"))
    return (_points(pts.get("val"), 100) if pts is not None else None,
            _points(pct.get("val"), 100000) if pct is not None else None)


def paragraph_style(p_el, chain: Sequence[Any], theme: ThemeContext,
                    body: BodyStyle = BodyStyle()) -> ParaStyle:
    """Resolve one ``a:p`` against its inheritance ``chain``."""
    own = p_el.find(qn("a:pPr"))
    level = int(own.get("lvl") or 0) if own is not None else 0
    p_props = ([own] if own is not None else []) + _level_props(chain, level)
    r_props = [el for el in [_run_props(p_el)] + [pp.find(qn("a:defRPr")) for pp in p_props]
               if el is not None]

    size = _points(_first_attr(r_props, "sz"), 100)
    fill = _first_child(r_props, "a:solidFill")
    glyph, numbered, start = _bullet(p_props)
    bullet_fill = _first_child(p_props, "a:buClr")
    before_pts, before_pct = _spacing(p_props, "a:spcBef")
    after_pts, after_pct = _spacing(p_props, "a:spcAft")
    _line_pts, line_pct = _spacing(p_props, "a:lnSpc")
    return ParaStyle(
        level=level,
        size_pt=(size * body.font_scale) if size else None,
        color=resolve_color(fill, theme),
        bold=_is_true(_first_attr(r_props, "b")),
        italic=_is_true(_first_attr(r_props, "i")),
        font_face=_font(_first_child(r_props, "a:latin"), theme),
        align=_ALIGN.get(_first_attr(p_props, "algn") or ""),
        margin_left_pt=_points(_first_attr(p_props, "marL"), EMU_PER_PT) or 0.0,
        indent_pt=_points(_first_attr(p_props, "indent"), EMU_PER_PT) or 0.0,
        bullet=glyph,
        bullet_color=resolve_color(bullet_fill, theme),
        numbered=numbered,
        number_start=start,
        space_before_pt=(before_pts if before_pts is not None
                         else (before_pct or 0.0) * (size or 18.0)),
        space_after_pt=(after_pts if after_pts is not None
                        else (after_pct or 0.0) * (size or 18.0)),
        line_spacing=line_pct,
    )


def body_style(txbody) -> BodyStyle:
    """Insets, anchor and autofit shrink from a text body's ``a:bodyPr``."""
    props = txbody.find(qn("a:bodyPr")) if txbody is not None else None
    if props is None:
        return BodyStyle()
    fit = props.find(qn("a:normAutofit"))
    scale = _points(fit.get("fontScale"), 100000) if fit is not None else None

    def inset(name: str, default: float) -> float:
        value = _points(props.get(name), EMU_PER_PT)
        return default if value is None else value

    return BodyStyle(
        inset_left_pt=inset("lIns", 7.2), inset_top_pt=inset("tIns", 3.6),
        inset_right_pt=inset("rIns", 7.2), inset_bottom_pt=inset("bIns", 3.6),
        anchor=_ANCHOR.get(props.get("anchor") or "", "top"),
        font_scale=scale or 1.0,
    )


def frame_styles(txbody, chain: Sequence[Any], theme: ThemeContext) -> Tuple[BodyStyle, List[ParaStyle]]:
    """``(the box, one style per paragraph)`` for a text body — aligned with its paragraphs."""
    body = body_style(txbody)
    paragraphs = txbody.findall(qn("a:p")) if txbody is not None else []
    return body, [paragraph_style(p, chain, theme, body) for p in paragraphs]
