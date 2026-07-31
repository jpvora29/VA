"""Feedback / quadrant / highlights tables — per-entity KPI cells and commentary.

The portfolio pages carry four shapes the generic slot path cannot fill:

  * the per-country **feedback table** ("What's working well · What's not · Growth
    Opportunities" with a Marsh GWP / Carrier GWP / Peer GWP / Carrier Rank / Carrier SoW /
    Peer SoW callout block per country row);
  * the **quadrant** on the per-country "Carrier:" slide (Successes · Challenges ·
    Opportunities · Key Messages) — authored either as one table or, in the current
    templates, as four free text panels under four heading boxes;
  * the one-cell **Key Highlights** table on the ranking slide.

Detection is generic (header/caption text and geometry, never slide indices) so it survives
template edits, mirroring :mod:`studio.template_fill.grids`: ``augment`` re-binds each cell
to a positional ``fb:<slide>:<shape>:<r>:<c>`` role (a panel gets
``fbnote:<slide>:<shape>:p:<para>``); ``values`` computes the texts from the deterministic
compute layer — every sentence is assembled around real figures, and the optional LLM only
re-words it behind the faithfulness verifier.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from logger import get_logger
from studio import compute as C
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Template
from studio.template_fill.render import _money
from studio.template_fill.slots import Slot

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_COUNTRY_COL = "Country"
_YEAR_COL = "Year"

_COUNTRY_TOKEN = re.compile(r"(?:Country\s*/\s*)?(?:Country|Region)\s*\(\s*(\d+)\s*\)", re.I)

# Cell-caption text → the KPI that cell displays (feedback-table callout block). The peer
# captions come FIRST so a "Peer GWP" cell is never read as the carrier's own premium.
_KPI_CAPTIONS: Tuple[Tuple[str, str], ...] = (
    ("peer gwp", "peer"),
    ("peer sow", "peer_sow"),
    ("marsh gwp", "marsh"),
    ("carrier gwp", "carrier"),
    ("carrier rank", "rank"),
    ("carrier sow", "sow"),
)
# Header text → the commentary column it heads (feedback table).
_FEEDBACK_TOPICS: Tuple[Tuple[str, str], ...] = (
    ("working well", "working"),
    ("not", "challenges"),
    ("growth", "growth"),
)
# Header text → the commentary quadrant it heads ("Carrier:" slide).
_QUADRANT_TOPICS: Tuple[Tuple[str, str], ...] = (
    ("success", "working"),
    ("challenge", "challenges"),
    ("opportunit", "growth"),
    ("message", "key_messages"),
)


def _role(slide_idx: int, shape_id: int, at: str, kind: str) -> str:
    """Positional role for one filled place. Commentary gets the ``fbnote:`` prefix (the
    fill engine styles those in the standard commentary font); KPI callouts stay ``fb:``
    so they keep the template's own value/caption formatting. ``at`` locates the place
    within its shape — ``"<r>:<c>"`` for a table cell, ``"p:<i>"`` for a panel paragraph."""
    prefix = "fbnote" if kind in _COMPOSERS else "fb"
    return f"{prefix}:{slide_idx}:{shape_id}:{at}"


def _cell_at(r: int, c: int) -> str:
    return f"{r}:{c}"


def _para_at(i: int) -> str:
    return f"p:{i}"


# ── detection (header/caption driven, template-agnostic) ─────────────────────


def _kpi_of(cell: str) -> Optional[str]:
    low = " ".join(cell.split()).lower()
    for marker, kpi in _KPI_CAPTIONS:
        if marker in low:
            return kpi
    return None


def _topic_columns(header_row: List[str], topics: Tuple[Tuple[str, str], ...]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for c, cell in enumerate(header_row):
        low = " ".join(cell.split()).lower()
        for marker, topic in topics:
            if marker in low:
                out[c] = topic
                break
    return out


def _feedback_cells(sh: Shape) -> List[Tuple[int, int, str, Optional[int]]]:
    """``[(r, c, kind, country_ord)]`` for one feedback table (empty if not one).

    ``kind`` is a commentary topic or a KPI name; ``country_ord`` is the 1-based
    ``Country/Region (n)`` index of the row block the cell belongs to.
    """
    table = sh.table or []
    if not table:
        return []
    topic_cols = _topic_columns(table[0], _FEEDBACK_TOPICS)
    if "working" not in topic_cols.values():
        return []
    # Row blocks: a row whose col-0 carries "Country / Region (n)" starts a block that
    # also covers the following row (the Rank/SoW half of the callout).
    blocks: List[Tuple[int, int]] = []          # (start_row, country_ord)
    for r, row in enumerate(table):
        m = _COUNTRY_TOKEN.search(row[0] or "")
        if m:
            blocks.append((r, int(m.group(1))))
    cells: List[Tuple[int, int, str, Optional[int]]] = []
    for start, ord_n in blocks:
        for c, topic in topic_cols.items():
            cells.append((start, c, topic, ord_n))
        for r in (start, start + 1):
            if r >= len(table):
                continue
            for c, cell in enumerate(table[r]):
                kpi = _kpi_of(cell)
                if kpi:
                    cells.append((r, c, kpi, ord_n))
    return cells


def _quadrant_cells(sh: Shape) -> List[Tuple[int, int, str, Optional[int]]]:
    """``[(r, c, topic, None)]`` for the Successes/Challenges/Opportunities/Messages table."""
    table = sh.table or []
    if len(table) < 2:
        return []
    topic_cols = _topic_columns(table[0], _QUADRANT_TOPICS)
    if len(topic_cols) < 3:
        return []
    return [(1, c, topic, None) for c, topic in topic_cols.items()]


def _highlight_cells(sh: Shape) -> List[Tuple[int, int, str, Optional[int]]]:
    """The one-cell "Key Highlights:" table."""
    table = sh.table or []
    if len(table) == 1 and len(table[0]) == 1 and "key highlight" in table[0][0].lower():
        return [(0, 0, "highlights", None)]
    return []


_DETECTORS: Tuple[Callable[[Shape], List[Tuple[int, int, str, Optional[int]]]], ...] = (
    _feedback_cells, _quadrant_cells, _highlight_cells,
)

# Two heading boxes are never further apart than this fraction of the slide width, so a
# body panel further than that from a heading's centre does not belong to it.
_COLUMN_TOLERANCE = 0.12


def _cx(sh: Shape) -> float:
    return sh.x + sh.w / 2.0


def _quadrant_panels(slide, slide_width: int) -> List[Tuple[int, int, str]]:
    """``[(shape_id, para_idx, topic)]`` for a quadrant authored as four TEXT PANELS.

    The current per-country "Carrier:" slide drops the quadrant table for four heading
    boxes with a tall body panel under each. Pairing is geometric: a heading takes the
    tallest text shape below it whose horizontal centre is nearest its own — so a restyle
    that moves or resizes the columns keeps working, and the heading's own background bar
    (which sits level with it, not below) is never mistaken for the body.
    """
    headings = [(sh, topic) for sh in slide.shapes if sh.kind == "text"
                for topic in [_quadrant_topic(sh.text)] if topic]
    if len(headings) < 3:
        return []
    tolerance = slide_width * _COLUMN_TOLERANCE
    used: set = set()
    out: List[Tuple[int, int, str]] = []
    for heading, topic in sorted(headings, key=lambda h: _cx(h[0])):
        bodies = [sh for sh in slide.shapes
                  if sh.kind == "text" and sh.shape_id not in used
                  and sh.y > heading.y and abs(_cx(sh) - _cx(heading)) < tolerance
                  and not _quadrant_topic(sh.text)]
        if not bodies:
            continue
        body = max(bodies, key=lambda sh: sh.h)
        used.add(body.shape_id)
        out.append((body.shape_id, 0, topic))
    return out if len(out) >= 3 else []


def _quadrant_topic(text: str) -> Optional[str]:
    """The quadrant a SHORT heading names, or None (long prose is never a heading)."""
    low = " ".join((text or "").split()).lower()
    if not low or len(low) > 30:
        return None
    for marker, topic in _QUADRANT_TOPICS:
        if marker in low:
            return topic
    return None


def _targets(template: Template) -> List[Dict[str, Any]]:
    """Every fillable place: ``{slide_idx, shape_id, where, at, kind, country_ord}``.

    A slide's TABLES are read first; only a slide with no fillable table falls back to the
    text-panel quadrant, so a template that still authors its quadrant as a table is
    unaffected."""
    out: List[Dict[str, Any]] = []
    for slide in template.slides:
        found: List[Dict[str, Any]] = []
        for sh in slide.shapes:
            if sh.kind != "table":
                continue
            for detect in _DETECTORS:
                cells = detect(sh)
                if cells:
                    found.extend({"slide_idx": slide.index, "shape_id": sh.shape_id,
                                  "where": ["cell", r, c], "at": _cell_at(r, c),
                                  "kind": kind, "country_ord": ordn}
                                 for r, c, kind, ordn in cells)
                    break
        if not found:
            found = [{"slide_idx": slide.index, "shape_id": shape_id,
                      "where": ["para", para], "at": _para_at(para),
                      "kind": topic, "country_ord": None}
                     for shape_id, para, topic in _quadrant_panels(slide, template.width_emu)]
        out.extend(found)
    return out


def _token_at(template: Template, target: Dict[str, Any]) -> str:
    """The template's own text at a target — the placeholder the write replaces."""
    sh = template.shape(target["slide_idx"], target["shape_id"])
    where = target["where"]
    if sh is None:
        return ""
    if where[0] == "cell" and sh.table:
        r, c = int(where[1]), int(where[2])
        if r < len(sh.table) and c < len(sh.table[r]):
            return sh.table[r][c]
        return ""
    i = int(where[1])
    return sh.paragraphs[i] if i < len(sh.paragraphs) else ""


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Re-bind (or add) each detected cell / panel to its ``fb:`` role (idempotent)."""
    by_key = {b.slot.key: b for b in bindings}
    extra: List[R.Binding] = []
    n = 0
    for t in _targets(template):
        where = t["where"]
        slot = Slot(t["slide_idx"], t["shape_id"], where, "", "text", "")
        role = _role(t["slide_idx"], t["shape_id"], t["at"], t["kind"])
        existing = by_key.get(slot.key)
        if existing is not None:
            existing.role, existing.placeholder = role, False
        else:
            extra.append(R.Binding(
                slot=Slot(t["slide_idx"], t["shape_id"], where, _token_at(template, t),
                          "text", ""),
                role=role, placeholder=False))
        n += 1
    if n:
        logger.info("feedback: bound %d cell(s)/panel(s) (%d added)", n, len(extra))
    return bindings + extra


# ── facts (deterministic compute, per entity scope) ──────────────────────────


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as exc:  # noqa: BLE001 — a failing metric must not break the fill
        logger.warning("feedback: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


def _facts(result, filters: Dict[str, Any]) -> Dict[str, Any]:
    """Carrier/Marsh totals + YoY, rank, SoW movement and the peer benchmark for one scope."""
    subject = result.subject
    base = {k: v for k, v in filters.items() if k != _CARRIER_COL}
    carrier = _safe(C.period_totals, result.flow, filters, result.engine) or {}
    marsh = _safe(C.period_totals, result.flow, base, result.engine) or {}
    rank = _safe(C.rank_movement, result.flow, filters, result.engine, subject) or {}
    sow = _safe(C.sow_movement, result.flow, filters, result.engine, subject) or {}
    peer = _safe(C.peer_average_totals, result.flow, filters, result.engine) or {}
    return {"carrier": carrier, "marsh": marsh, "rank": rank, "sow": sow, "peer": peer}


# ── deterministic text composition (every claim carries its figure) ──────────


def _arrow(v: Optional[float]) -> str:
    if v is None or v == 0:
        return "►"
    return "▲" if v > 0 else "▼"


# KPI callout kind → (which fact, which current/delta keys, caption). Money KPIs render as
# a compact amount, share KPIs as a percentage, rank as an integer place.
_MONEY_KPIS: Dict[str, Tuple[str, str, str, str]] = {
    #  kind          fact       current    delta   caption
    "marsh": ("marsh", "current", "pct", "Marsh GWP"),
    "carrier": ("carrier", "current", "pct", "Carrier GWP"),
    "peer": ("peer", "current", "pct", "Peer\n GWP"),
}
_SHARE_KPIS: Dict[str, Tuple[str, str, str, str]] = {
    "sow": ("sow", "current", "delta", "Carrier SoW"),
    "peer_sow": ("peer", "sow", "sow_delta", "Peer\n SoW"),
}


def _delta_tail(delta: Optional[float]) -> str:
    return "" if delta is None else f" ({delta:+.1f}%{_arrow(delta)})"


def _kpi_cell(kind: str, f: Dict[str, Any]) -> str:
    """One callout cell in the template's own style: value (delta arrow) + caption."""
    spec = _MONEY_KPIS.get(kind)
    if spec is not None:
        fact, cur_key, delta_key, caption = spec
        t = f[fact]
        if t.get(cur_key) is None:
            return ""
        return f"{_money(t[cur_key])}{_delta_tail(t.get(delta_key))}\n{caption}"
    spec = _SHARE_KPIS.get(kind)
    if spec is not None:
        fact, cur_key, delta_key, caption = spec
        t = f[fact]
        if t.get(cur_key) is None:
            return ""
        return f"{t[cur_key]:.1f}%{_delta_tail(t.get(delta_key))}\n{caption}"
    if kind == "rank":
        t = f["rank"]
        if t.get("current") is None:
            return ""
        d = t.get("delta")
        chg = "" if d is None else (f" (+{d}▲)" if d > 0 else (f" ({d}▼)" if d < 0 else " (=0►)"))
        return f"{int(t['current'])}{chg}\nCarrier Rank"
    return ""


def _working_text(f: Dict[str, Any]) -> str:
    parts: List[str] = []
    c, r, s = f["carrier"], f["rank"], f["sow"]
    if (c.get("pct") or 0) > 0:
        parts.append(f"GWP with Marsh grew {c['pct']:+.1f}% YoY to {_money(c['current'])}.")
    if (r.get("delta") or 0) > 0:
        parts.append(f"Market rank improved {int(r['delta'])} place(s) to #{int(r['current'])}.")
    if (s.get("delta") or 0) > 0:
        parts.append(f"Share of wallet rose {s['delta']:+.1f}% to {s['current']:.1f}%.")
    if not parts and c.get("current"):
        parts.append(f"Book held at {_money(c['current'])} with Marsh.")
    return " ".join(parts[:2])


def _challenges_text(f: Dict[str, Any]) -> str:
    parts: List[str] = []
    c, r, s = f["carrier"], f["rank"], f["sow"]
    if (c.get("pct") or 0) < 0:
        parts.append(f"GWP with Marsh declined {c['pct']:+.1f}% YoY to {_money(c['current'])}.")
    if (r.get("delta") or 0) < 0:
        parts.append(f"Market rank slipped {abs(int(r['delta']))} place(s) to #{int(r['current'])}.")
    if (s.get("delta") or 0) < 0:
        parts.append(f"Share of wallet fell {s['delta']:+.1f}% to {s['current']:.1f}%.")
    if not parts and (f["marsh"].get("pct") is not None) and (c.get("pct") is not None) \
            and f["marsh"]["pct"] > c["pct"]:
        parts.append(
            f"Growth of {c['pct']:+.1f}% trails the Marsh book ({f['marsh']['pct']:+.1f}%)."
        )
    return " ".join(parts[:2])


def _growth_text(f: Dict[str, Any]) -> str:
    c, m, s = f["carrier"], f["marsh"], f["sow"]
    parts: List[str] = []
    if c.get("current") is not None and m.get("current"):
        headroom = m["current"] - c["current"]
        if headroom > 0:
            share = f" at {s['current']:.1f}% share of wallet" if s.get("current") is not None else ""
            parts.append(
                f"{_money(headroom)} of the {_money(m['current'])} Marsh book is placed elsewhere{share} — headroom to grow."
            )
    if (m.get("pct") or 0) > 0 and (c.get("pct") is not None) and m["pct"] > c["pct"]:
        parts.append(f"Marsh demand is growing {m['pct']:+.1f}% YoY — capture more of the flow.")
    return " ".join(parts[:2])


def _key_messages_text(f: Dict[str, Any]) -> str:
    c, r, s = f["carrier"], f["rank"], f["sow"]
    parts: List[str] = []
    if c.get("current") is not None:
        yoy = f" ({c['pct']:+.1f}% YoY)" if c.get("pct") is not None else ""
        parts.append(f"{_money(c['current'])} written with Marsh{yoy}.")
    pos: List[str] = []
    if r.get("current") is not None:
        pos.append(f"rank #{int(r['current'])}")
    if s.get("current") is not None:
        pos.append(f"{s['current']:.1f}% share of wallet")
    if pos:
        parts.append("Position: " + ", ".join(pos) + ".")
    return " ".join(parts[:2])


def _highlights_text(f: Dict[str, Any]) -> str:
    lines: List[str] = []
    for text in (_working_text(f), _challenges_text(f), _growth_text(f)):
        if text:
            lines.append(text)
    return "Key Highlights:\n" + "\n".join(lines[:3]) if lines else ""


_COMPOSERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "working": _working_text,
    "challenges": _challenges_text,
    "growth": _growth_text,
    "key_messages": _key_messages_text,
    "highlights": _highlights_text,
}


# ── value resolution ─────────────────────────────────────────────────────────


def _reporting_filters(result) -> Dict[str, Any]:
    """The result's filters with the reporting year pinned (max pin, else latest in scope)."""
    from studio.template_fill.bindings import _latest_year_in_scope

    f = dict(result.resolved_filters or {})
    year = f.get(_YEAR_COL)
    if isinstance(year, (list, tuple, set)):
        year = max(int(y) for y in year) if year else None
    if year is None:
        year = _latest_year_in_scope(result, {k: v for k, v in f.items() if k != _YEAR_COL})
    if year is not None:
        f[_YEAR_COL] = int(year)
    return f


def _countries_in_scope(result) -> List[str]:
    """Countries by premium (biggest first) — the order the ``Country (n)`` labels use."""
    from studio.template_fill.bindings import _country_breakdown

    return [r["name"] for r in _country_breakdown(result) if r.get("name")]


def _polish(text: str, kind: str, style: Optional[str]) -> str:
    """LLM re-word behind the faithfulness verifier; KPI cells stay deterministic."""
    if kind not in _COMPOSERS or kind == "highlights" or not text:
        return text
    from studio.template_fill.commentary import _polish as polish

    return polish(text, node=f"feedback-{kind}", style=style)


def values(template: Template, result) -> Dict[str, Any]:
    """``{fb-role: text}`` for every detected table cell, scoped per country row.

    Feedback-table rows are scoped to their ``Country (n)`` (within the sub-deck's own
    product/country scope); quadrant/highlight cells use the sub-deck scope itself.
    Rows beyond the countries in scope are blanked so no ``$xxx.xM`` placeholder survives.
    """
    targets = _targets(template)
    if not targets:
        return {}
    fy = _reporting_filters(result)
    style = getattr(result, "style", "balanced")
    countries = _countries_in_scope(result) if any(t["country_ord"] for t in targets) else []

    facts_cache: Dict[Optional[str], Dict[str, Any]] = {}

    def facts_for(country: Optional[str]) -> Dict[str, Any]:
        if country not in facts_cache:
            scoped = {**fy, _COUNTRY_COL: country} if country else fy
            facts_cache[country] = _facts(result, scoped)
        return facts_cache[country]

    text_cache: Dict[Tuple[Optional[str], str], str] = {}
    out: Dict[str, Any] = {}
    for t in targets:
        ordn = t["country_ord"]
        role = _role(t["slide_idx"], t["shape_id"], t["at"], t["kind"])
        country: Optional[str] = None
        if ordn is not None:
            if ordn > len(countries):            # row beyond the data → blank the block
                out[role] = ""
                continue
            country = countries[ordn - 1]
        key = (country, t["kind"])
        if key not in text_cache:
            f = facts_for(country)
            composer = _COMPOSERS.get(t["kind"])
            text = composer(f) if composer else _kpi_cell(t["kind"], f)
            text_cache[key] = _polish(text, t["kind"], style)
        # KPI callouts always write (a blank beats a stale "$xx.xM" placeholder);
        # an empty commentary keeps the template's ellipsis as a visible fill-me cue.
        if text_cache[key] or t["kind"] not in _COMPOSERS:
            out[role] = text_cache[key]
    logger.info("feedback: resolved %d table cell value(s)", len(out))
    return out
