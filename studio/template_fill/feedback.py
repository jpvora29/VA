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
from studio import segments as SEG
from studio.template_fill import facts_mix, facts_trend
from studio.template_fill import rewrites
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Template
from studio.template_fill import units as U
from studio.template_fill.render import _money
from studio.template_fill.slots import Slot

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_COUNTRY_COL = "Country"
_PRODUCT_COL = "Product_Line"
_INDUSTRY_COL = "SIC_Major_Class"
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


def _is_pinned(filters: Dict[str, Any], column: str) -> bool:
    value = filters.get(column)
    values = tuple(value) if isinstance(value, (list, tuple, set)) else ((value,) if value else ())
    return len(values) == 1


def _driver_dim(filters: Dict[str, Any]) -> str:
    """The dimension a YoY move is best decomposed by IN THIS SCOPE.

    A product sub-deck is already one line of business, so its drivers are countries;
    every other scope decomposes by line of business, which is how the deck reads
    everywhere else.

    A product page's COUNTRY ROW has both axes pinned, and used to decompose by country
    anyway — one value, so ``_named_moves`` and ``_capture_gap`` both returned nothing and
    the cell fell through to the generic headroom line. Its drivers are industries.
    """
    if _is_pinned(filters, _PRODUCT_COL) and _is_pinned(filters, _COUNTRY_COL):
        return _INDUSTRY_COL
    return _COUNTRY_COL if _is_pinned(filters, _PRODUCT_COL) else _PRODUCT_COL


_SEGMENT_COL = "Client_Segment"


def _segment_dims(filters: Dict[str, Any]) -> Tuple[str, ...]:
    """The decompositions that can carry a finding IN THIS SCOPE.

    Never a dimension the scope has already pinned: a page filtered to one industry that
    decomposed by industry could only report itself back.
    """
    from studio import segments as SEG

    return tuple(d for d in SEG.configured_dims() if not _is_pinned(filters, d))


def _segment_facts(result, filters: Dict[str, Any]) -> Dict[str, Any]:
    """This scope decomposed by industry and by client segment.

    The one fact family that says WHERE inside the scope the book sits. Everything else in
    ``_facts`` describes the scope as a single number, which is why every page argued from
    the same six figures however differently its column was briefed.
    """
    from studio import segments as SEG

    dims = _segment_dims(filters)
    if not dims:
        return {}
    year = C._current_year(filters)
    found = _safe(SEG.find_all, flow=result.flow, filters=filters, engine=result.engine,
                  subject=result.subject, dims=dims, year=year) or {}
    above = _parent_filters(filters)
    if not found or above is None:
        return found
    parent = _safe(SEG.find_all, flow=result.flow, filters=above, engine=result.engine,
                   subject=result.subject, dims=dims, year=year) or {}
    narrowed, tracks = SEG.narrow(found, parent)
    _SEGMENT_TRACKS[_scope_key(result, filters)] = tracks
    return narrowed


def _tracks_its_parent(result, filters: Dict[str, Any]) -> bool:
    """True when this scope had findings and none of them survived narrowing.

    Computed alongside the decomposition rather than inside it, so the segments map stays
    a map of dimensions and nothing has to know to skip a sentinel key.
    """
    return bool(_SEGMENT_TRACKS.get(_scope_key(result, filters)))


def _scope_key(result, filters: Dict[str, Any]) -> Tuple[Any, ...]:
    return (result.flow, str(result.subject), _filters_signature(filters))


def _filters_signature(filters: Dict[str, Any]) -> Tuple[Tuple[str, Any], ...]:
    out = []
    for col, val in sorted((filters or {}).items()):
        out.append((col, tuple(sorted(map(str, val)))
                    if isinstance(val, (list, tuple, set)) else val))
    return tuple(out)


# Set by ``_segment_facts`` for the scope it just narrowed, read by ``_tracks_its_parent``
# on the next line of the same ``_facts`` call. Small and short-lived rather than a second
# pair of queries to answer a question the narrowing already answered.
_SEGMENT_TRACKS: Dict[Tuple[Any, ...], bool] = {}


def _parent_filters(filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The scope one level up: this cut without its narrowest entity pin.

    A product page's country row sits under that product across every market; a country
    page sits under the whole portfolio. Comparing a scope with its own parent is what
    decides whether a finding belongs to this page or to the one above it.
    """
    for col in (_COUNTRY_COL, _PRODUCT_COL):
        if _is_pinned(filters, col):
            return {k: v for k, v in filters.items() if k != col}
    return None


def _facts(result, filters: Dict[str, Any]) -> Dict[str, Any]:
    """Carrier/Marsh totals + YoY, rank, SoW movement, the peer benchmark, the
    per-dimension decomposition of both books — the carrier's own movers and the Marsh
    pool they were won from — and where inside the scope the book actually sits.

    These eight lookups are independent and were an obvious candidate for running at
    once. Measured, they are not: the engine is a local SQLite file and each primitive
    spends most of its time in pandas afterwards, so a thread pool bought nothing outside
    the noise and cost a layer of indirection. The concurrency that DID pay for itself is
    over the model calls, where the wait is a network round trip
    (:mod:`studio.template_fill.rewrites`).
    """
    subject = result.subject
    base = {k: v for k, v in filters.items() if k != _CARRIER_COL}
    dim = _driver_dim(filters)
    carrier = _safe(C.period_totals, result.flow, filters, result.engine) or {}
    marsh = _safe(C.period_totals, result.flow, base, result.engine) or {}
    rank = _safe(C.rank_movement, result.flow, filters, result.engine, subject) or {}
    sow = _safe(C.sow_movement, result.flow, filters, result.engine, subject) or {}
    peer = _safe(C.peer_average_totals, result.flow, filters, result.engine) or {}
    movers = _safe(C.movement_by_dim, result.flow, dim, filters, result.engine, top=8) or []
    pool = _safe(C.movement_by_dim, result.flow, dim, base, result.engine, top=8) or []
    return {"subject": str(subject or ""), "carrier": carrier, "marsh": marsh, "rank": rank,
            "sow": sow, "peer": peer, "movers": movers, "pool": pool,
            # The two families that are not another reading of the headline: HOW the book
            # is distributed, and WHERE it is heading. Without them every column argued
            # from the same six numbers, which is why every column read alike.
            "mix": facts_mix.load(result, filters),
            "trend": facts_trend.load(result, filters, annual_pct=carrier.get("pct")),
            "segments": _segment_facts(result, filters),
            "segments_track": _tracks_its_parent(result, filters)}


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


# Commentary cells are BULLET LISTS: each composer returns its points MOST MATERIAL FIRST,
# one per line, and the fill engine renders each line as its own bulleted paragraph.
#
# How many of those points survive depends on the surface. A quadrant panel is a whole
# column of the slide and can carry the argument — the movement, what drove it, how it
# reads against the peer benchmark, and what it is worth. A feedback-table cell is one row
# of a table alongside five KPI callouts, so it keeps the headlines only.
_PANEL_BULLETS = 4
_CELL_BULLETS = 3
# "Key Highlights" is a ONE-ROW table across the top of a page, not a column: its heading
# plus two points is what fits before the text overflows the cell's own border.
_HIGHLIGHT_BULLETS = 3


def _bullets(parts: List[str], limit: int = _PANEL_BULLETS) -> str:
    return "\n".join(p for p in parts[:limit] if p)


def _signed_money(raw: float) -> str:
    """A movement, with its direction — ``_money`` is unsigned by design."""
    return ("-" if raw < 0 else "+") + _money(raw)


# ── prose formatting ─────────────────────────────────────────────────────────
# These panels are read aloud in a carrier's boardroom, so they are written the way an
# adviser speaks: the direction of a movement belongs in the VERB ("grew 12.0%"), not in a
# sign glued to the number ("+12.0%"), which reads as a spreadsheet cell rather than a
# sentence. The figures themselves are untouched — only how they are said.


def _mag(pct: float) -> str:
    """A movement's size, for a sentence that already carries its direction."""
    return f"{abs(pct):.1f}%"


def _moved(pct: float) -> str:
    """A movement as a clause of its own: ``grew 12.0%`` / ``fell 3.0%``."""
    return f"{'grew' if pct >= 0 else 'fell'} {_mag(pct)}"


def _up_down(pct: float) -> str:
    """A movement hung off a noun: ``up 12.0%`` / ``down 3.0%``."""
    return f"{'up' if pct >= 0 else 'down'} {_mag(pct)}"


def _subject(f: Dict[str, Any], *, opening: bool = False) -> str:
    """The carrier by name where the facts carry it, else "the account".

    A partner names the account rather than talking around it. ``opening`` capitalises the
    fallback for a sentence that starts on it.
    """
    name = str(f.get("subject") or "").strip()
    if name:
        return name
    return "The account" if opening else "the account"


def _and(parts: List[str]) -> str:
    """``a``, ``a and b``, ``a, b and c`` — a list said the way it is spoken.

    An item carrying its own comma takes a comma before the "and" too, or the two run
    together ("Cyber, up $85M and Financial Lines, up $67M" reads as three things). Only the
    items BEFORE the last matter: a comma inside the final item cannot blur the join.
    """
    if len(parts) < 2:
        return "".join(parts)
    tail = ", and " if any("," in p for p in parts[:-1]) else " and "
    return ", ".join(parts[:-1]) + tail + parts[-1]


def _rank_of(r: Dict[str, Any]) -> str:
    """``#5 of 41`` where the field size is known, else ``#5``."""
    return f"#{int(r['current'])}" + (f" of {int(r['of_n'])}" if r.get("of_n") else "")


def _places(n: int) -> str:
    return "1 place" if abs(n) == 1 else f"{abs(n)} places"


# A movement smaller than this share of the book is noise rather than a finding. Naming a
# $145K move on a $208M book — as "what premium was given back on" — is exactly what makes
# commentary read as generated: a partner would not have mentioned it.
_MATERIAL_MOVE_SHARE = 0.01


def _material_floor(f: Dict[str, Any]) -> float:
    """The smallest movement worth naming, from the size of the book it moved."""
    return abs((f.get("carrier") or {}).get("current") or 0.0) * _MATERIAL_MOVE_SHARE


def _named_moves(rows: List[Dict[str, Any]], *, rising: bool, top: int = 2,
                 floor: float = 0.0) -> str:
    """``Cyber, up $22M (97.3%), and Financial Lines, up $16M (57.1%)`` — the movers, named.

    A scope with one value on the driver dimension (a product page's own line of business)
    cannot decompose into anything: naming it would only restate the headline. Movements
    below ``floor`` are left out for the same reason — they carry no argument.
    """
    if len(rows) < 2:
        return ""
    picked = [x for x in rows
              if ((x.get("delta") or 0.0) > 0) is rising
              and abs(x.get("delta") or 0.0) >= floor and (x.get("delta") or 0.0)][:top]
    word = "up" if rising else "down"
    parts = [f"{x['name']}, {word} {_money(abs(x['delta']))}"
             + (f" ({_mag(x['pct'])})" if x.get("pct") is not None else "")
             for x in picked]
    return _and(parts)


def _point_of_share(f: Dict[str, Any]) -> Optional[float]:
    """What one percentage point of share of wallet is worth, in premium."""
    total = (f.get("marsh") or {}).get("current")
    return (total / 100.0) if total else None


def _peer_share_gap(f: Dict[str, Any]) -> Optional[float]:
    """How far the carrier's share of wallet sits BELOW the top-5 peer average, in points."""
    mine = (f.get("sow") or {}).get("current")
    theirs = (f.get("peer") or {}).get("sow")
    if mine is None or theirs is None or theirs <= mine:
        return None
    return theirs - mine


def _working_points(f: Dict[str, Any]) -> List[str]:
    """Successes: what grew, what drove it, and what the growth bought."""
    c, m, r, s = f["carrier"], f.get("marsh") or {}, f["rank"], f["sow"]
    parts: List[str] = []
    if (c.get("pct") or 0) > 0:
        line = (f"{_subject(f, opening=True)} grew its book with Marsh {_mag(c['pct'])} "
                f"year on year to {_money(c['current'])}")
        if m.get("pct") is not None and m["pct"] < c["pct"]:
            line += (f", well ahead of the wider Marsh book, which {_moved(m['pct'])}, so the "
                     f"gain was won on share rather than carried by the market")
        elif m.get("pct") is not None:
            line += f", against a wider Marsh book that {_moved(m['pct'])}"
        parts.append(line + ".")
    risers = _named_moves(f.get("movers") or [], rising=True, floor=_material_floor(f))
    if risers and (c.get("delta") or 0) > 0:
        parts.append(f"The increase was led by {risers}, out of a total book movement of "
                     f"{_money(c['delta'])}.")
    if (r.get("delta") or 0) > 0:
        parts.append(f"Rank within the Marsh book improved {_places(int(r['delta']))} to "
                     f"{_rank_of(r)}, and that came at competitors' expense rather than "
                     f"from a growing pool.")
    if (s.get("delta") or 0) > 0:
        line = f"Share of wallet rose {U.points(s['delta'])} to {s['current']:.1f}%"
        peer_sow = (f.get("peer") or {}).get("sow")
        if peer_sow is not None:
            side = "above" if s["current"] >= peer_sow else "below"
            line += (f", which leaves the book {U.points(s['current'] - peer_sow)} {side} "
                     f"the top-5 peer average of {peer_sow:.1f}%")
        parts.append(line + ".")
    # Where the book places above its own standard. A scope-level growth figure says the
    # book grew; this says which part of it the rest could be measured against.
    from studio.template_fill import segment_prose as P

    parts += P.points(_segments(f), SEG.Placement.STRONG, subject=_subject(f), limit=2)

    if not parts and c.get("current"):
        parts.append(f"{_subject(f, opening=True)} held its book with Marsh at "
                     f"{_money(c['current'])}.")
    return parts


def _challenges_points(f: Dict[str, Any]) -> List[str]:
    """Challenges: where the book lost ground, in absolute terms and against the market.

    A growing book can still be losing: trailing the Marsh book, sitting below the peer
    share benchmark and giving premium back on individual lines are all real, evidenced
    challenges — nothing here is written without a figure behind it.
    """
    c, m, r, s = f["carrier"], f.get("marsh") or {}, f["rank"], f["sow"]
    parts: List[str] = []
    if (c.get("pct") or 0) < 0:
        line = (f"{_subject(f, opening=True)}'s book with Marsh fell {_mag(c['pct'])} "
                f"year on year to {_money(c['current'])}")
        if m.get("pct") is not None and m["pct"] > c["pct"]:
            line += f", while the wider Marsh book {_moved(m['pct'])}, so this is lost share"
        parts.append(line + ".")
    if (r.get("delta") or 0) < 0:
        parts.append(f"Rank within the Marsh book slipped {_places(int(r['delta']))} to "
                     f"{_rank_of(r)}.")
    if (s.get("delta") or 0) < 0:
        parts.append(f"Share of wallet fell {U.points(s['delta'])} to {s['current']:.1f}%.")
    if (c.get("pct") is not None) and (m.get("pct") is not None) and m["pct"] > c["pct"] \
            and (c.get("pct") or 0) >= 0:
        parts.append(f"Growth of {_mag(c['pct'])} trails a wider Marsh book that "
                     f"{_moved(m['pct'])}, so {_subject(f)} is growing but losing ground.")
    fallers = _named_moves(f.get("movers") or [], rising=False, floor=_material_floor(f))
    if fallers:
        # "Offsetting the gains" only means something on a book that made gains; on a book
        # that shrank overall these lines ARE the decline, and saying otherwise would read
        # as a softener rather than a finding.
        tail = ", which offset the gains elsewhere" if (c.get("pct") or 0) > 0 else ""
        parts.append(f"Premium was given back on {fallers}{tail}.")
    # Where the ground was actually given, named. A decline stated at scope level is a
    # number; the same decline located in an industry or a client segment is a mechanism,
    # which is what this column is for.
    from studio.template_fill import segment_prose as P

    parts += P.points(_segments(f), SEG.Placement.LOSING, subject=_subject(f), limit=2)

    conc = _concentration_point(f)
    if conc:
        parts.append(conc)

    # Last, and only when nothing above located the problem: the scope-level peer gap is
    # the same observation without a place attached to it.
    gap = _peer_share_gap(f)
    point = _point_of_share(f)
    if gap is not None:
        line = (f"At {s['current']:.1f}% share of wallet the book sits {U.points(gap)} "
                f"below the top-5 peer average of {f['peer']['sow']:.1f}%")
        if point:
            line += f", which is about {_money(gap * point)} of premium in scope"
        parts.append(line + ".")
    return parts


# Below this the book is spread, not concentrated, and saying so is not a finding.
_CONCENTRATED_TOP3 = 60.0


def _concentration_point(f: Dict[str, Any]) -> Optional[str]:
    """How much of the book rests on its largest few segments.

    ``terms.yaml`` forbids calling a concentrated book risky without naming what would have
    to happen for it to hurt, so the sentence states the shape and points at the one of
    those segments that is moving the wrong way -- which is the thing that would hurt.
    """
    for findings in _segments(f).values():
        top3 = findings.top3_share
        if top3 is None or top3 < _CONCENTRATED_TOP3:
            continue
        slipping = next((r for r in findings.written[:3] if (r.sow_delta or 0) < 0), None)
        tail = f", and share slipped in {slipping.name}" if slipping else ""
        return (f"The book's three largest {findings.label} groups carry {top3:.0f}% "
                f"of everything it writes here{tail}.")
    return None


def _segments(f: Dict[str, Any]) -> Dict[str, Any]:
    """This scope's DISTINGUISHING decomposition, or nothing. Every consumer reads it
    through here so a fact set built before segments existed still composes exactly as it
    did."""
    return f.get("segments") or {}


def _tracks_parent(f: Dict[str, Any]) -> bool:
    """True when this scope has findings but none its parent does not already make."""
    return bool(f.get("segments_track"))


def _growth_points(f: Dict[str, Any]) -> List[str]:
    """Opportunities: where the premium the book does not have actually sits.

    Ordered by what a carrier's leadership can act on, which is not the order the figures
    arrive in. Absence first - business Marsh already places that this book writes none of
    - then the segments it writes below its own standard, then those below the benchmark,
    then the one it places best as evidence the rest can be moved.

    The scope-level lines that used to lead this column now trail it. "Every point of share
    is worth about $4M" and "closing the gap to the peer average would add roughly $349K"
    are arithmetic on the headline, and on a line whose real story was $69M of untouched
    industries they were what the column said instead. They stay as the tail, so a scope
    with no segment findings still fills its cell.
    """
    from studio.template_fill import segment_prose as P

    c, m, s_ = f["carrier"], f.get("marsh") or {}, f["sow"]
    found = _segments(f)
    subject = _subject(f)
    parts: List[str] = P.points(found, *SEG.OPPORTUNITY_KINDS, subject=subject, limit=3)

    summary = P.absence_summary(found, subject)
    if summary and len(parts) < 2:
        parts.append(summary)
    # Nothing here differs from the wider book. Saying so is a finding; repeating the
    # portfolio's own story on every page, as this column used to, is not.
    if not parts and _tracks_parent(f):
        parts.append(P.tracking_note(share=(f.get("sow") or {}).get("current")))

    # The proof point is the only STRONG line this column carries, so it leads its class.
    proof = next((p for p in (P.sentence(r, subject, lead=True)
                              for fs in found.values()
                              for r in fs.of(SEG.Placement.STRONG)[:1])
                  if p), None)
    if proof and parts:
        parts.append(proof)

    capture = _capture_gap(f)
    if capture:
        parts.append(capture)

    if c.get("current") is not None and m.get("current"):
        headroom = m["current"] - c["current"]
        if headroom > 0:
            share = (f", leaving {subject} on {s_['current']:.1f}% of the wallet"
                     if s_.get("current") is not None else "")
            point = _point_of_share(f)
            worth = (f", where every point of share is worth about {_money(point)}"
                     if point else "")
            parts.append(f"Of the {_money(m['current'])} Marsh book, {_money(headroom)} is "
                         f"placed with other carriers{share}{worth}.")
    gap, point = _peer_share_gap(f), _point_of_share(f)
    if gap is not None and point:
        parts.append(f"Closing the {U.points(gap)} gap to the top-5 peer average would add "
                     f"roughly {_money(gap * point)} of GWP at today's market size.")
    if (m.get("pct") or 0) > 0 and (c.get("pct") is not None) and m["pct"] > c["pct"]:
        parts.append(f"Marsh demand grew {_mag(m['pct'])} year on year, so holding share "
                     f"flat would still leave premium on the table, and capture rate is "
                     f"the lever.")
    return parts


def _capture_gap(f: Dict[str, Any]) -> Optional[str]:
    """Where Marsh demand grew hardest and the carrier took least of it.

    A comparison needs something to compare: a scope holding one value on the driver
    dimension has no widest gap, only its own total again.
    """
    rows = f.get("pool") or []
    pool = [x for x in rows if (x.get("delta") or 0) > 0]
    if len(rows) < 2 or not pool:
        return None
    mine = {x["name"]: (x.get("delta") or 0.0) for x in (f.get("movers") or [])}
    worst = max(pool, key=lambda x: x["delta"] - mine.get(x["name"], 0.0))
    if worst["name"] not in mine:
        return None
    captured = mine[worst["name"]]
    if captured >= worst["delta"]:
        return None
    took = (f"{_subject(f)} took only {_money(captured)} of it" if captured > 0
            else f"{_subject(f)} gave back {_money(captured)}")
    return (f"{worst['name']} added {_money(worst['delta'])} of Marsh premium year on year "
            f"while {took}, the widest capture gap in the portfolio.")


def _key_messages_points(f: Dict[str, Any]) -> List[str]:
    """Key messages: the four lines the account team should be able to say from memory.

    Opens on the STANCE (:mod:`studio.template_fill.stance`) rather than on a premium
    total: what the team needs to carry out of the room is what to do about this book, and
    the figures behind that call follow in the lines beneath it.
    """
    from studio.template_fill.stance import book_posture_point

    c, r, s, peer = f["carrier"], f["rank"], f["sow"], f.get("peer") or {}
    m = f.get("marsh") or {}
    parts: List[str] = []
    stance = book_posture_point(f)
    if stance:
        parts.append(stance)
    if c.get("current") is not None:
        year = f" in {int(c['current_year'])}" if c.get("current_year") else ""
        yoy = f", {_up_down(c['pct'])} on the year," if c.get("pct") is not None else ""
        market = (f" against a wider Marsh book that {_moved(m['pct'])}"
                  if m.get("pct") is not None else "")
        parts.append(f"{_subject(f, opening=True)} wrote {_money(c['current'])} with "
                     f"Marsh{year}{yoy}{market}.")
    pos: List[str] = []
    if r.get("current") is not None:
        pos.append(f"ranks {_rank_of(r)}")
    if s.get("current") is not None:
        moved = (f", {'up' if s['delta'] >= 0 else 'down'} {U.points_of_share(s['delta'])}"
                 if s.get("delta") is not None else "")
        # The peer average benchmarks the SHARE, so it hangs off the share clause â€” never
        # off a rank, which it says nothing about.
        against = (f", against a top-5 peer average of {peer['sow']:.1f}%"
                   if peer.get("sow") is not None else "")
        pos.append(f"holds {s['current']:.1f}% of the wallet{moved}{against}")
    if pos:
        parts.append(f"{_subject(f, opening=True)} " + _and(pos) + ".")
    risers = _named_moves(f.get("movers") or [], rising=True, floor=_material_floor(f))
    if risers:
        parts.append(f"Momentum sits with {risers}, so the renewal book there is what to "
                     f"protect first.")
    gap, point = _peer_share_gap(f), _point_of_share(f)
    if gap is not None and point:
        parts.append(f"Reaching peer parity means winning {U.points_of_share(gap)}, worth "
                     f"about {_money(gap * point)} of GWP.")
    return parts


def _thesis_points(f: Dict[str, Any]) -> List[str]:
    """The portfolio thesis: the one tension the rest of the deck exists to discuss.

    Every other column reports a part of the book. The summary page's job is different â€” it
    states where the account STANDS, as a single claim a leadership team can agree or argue
    with, and the tension in it is what the following pages then evidence. So this is a
    synthesis of two facts that are usually reported apart: how the book is growing against
    the Marsh pool, and how well it is penetrated against the peer benchmark. A book can be
    winning one and losing the other, and that gap is the thesis.
    """
    c, m = f.get("carrier") or {}, f.get("marsh") or {}
    s_, peer = f.get("sow") or {}, f.get("peer") or {}
    if c.get("current") is None or c.get("pct") is None or m.get("pct") is None:
        return []
    share, peer_share = s_.get("current"), peer.get("sow")
    outgrowing = c["pct"] > m["pct"]
    lead = (f"{_subject(f, opening=True)} grew {_mag(c['pct'])} to {_money(c['current'])} "
            f"against a Marsh book that {_moved(m['pct'])}")
    if share is None or peer_share is None:
        tail = (", so the book is taking share" if outgrowing
                else ", so the book is giving share back")
        return [lead + tail + "."]
    behind = peer_share - share
    if outgrowing and behind > 0:
        # The common shape, and the one worth arguing about: winning the year, still
        # under-represented on the book that matters.
        return [f"{lead}, but at {share:.1f}% of the wallet it is still "
                f"{U.points(behind)} behind the top-5 peer average of {peer_share:.1f}% â€” "
                f"the growth is real and the relevance is not yet."]
    if outgrowing:
        return [f"{lead}, and at {share:.1f}% of the wallet it already writes above the "
                f"top-5 peer average of {peer_share:.1f}% â€” the question is holding that, "
                f"not winning it."]
    if behind > 0:
        return [f"{lead}, and at {share:.1f}% of the wallet it sits {U.points(behind)} "
                f"behind the top-5 peer average of {peer_share:.1f}% â€” the book is losing "
                f"ground from a position already behind its peers."]
    return [f"{lead}, though at {share:.1f}% of the wallet it still writes above the "
            f"top-5 peer average of {peer_share:.1f}% â€” a strong position growing slower "
            f"than the book around it."]


def _highlights_points(f: Dict[str, Any]) -> List[str]:
    """The one-cell "Key Highlights:" table â€” its heading line, then one point per theme."""
    themes = (points("working", f), points("challenges", f), points("growth", f))
    leads = [t[0] for t in themes if t]
    return ["Key Highlights:"] + leads if leads else []


# â”€â”€ fallbacks: a commentary cell must never ship blank â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Each composer answers its question only from the figures that support it, so a book with
# nothing negative to report leaves "What's not" empty â€” and a blank column on a carrier's
# page reads as an oversight rather than as an absence of bad news. A fallback answers the
# SAME question from the position the book actually holds. None of them invents a negative
# or softens one: every fallback still carries the figure it is built on, and a book with a
# real challenge never reaches them, because the primary composer already spoke.


def _recent_gain(f: Dict[str, Any]) -> Optional[str]:
    """A share position won inside one year is new rather than established.

    The distinct thing to say about a book with no bad news: how much of its standing is
    one year old. Both figures are the share facts already on the page, but the claim â€”
    that the position is young â€” is one no other column makes.
    """
    s = f.get("sow") or {}
    cur, delta = s.get("current"), s.get("delta")
    if cur is None or delta is None or delta <= 0:
        return None
    return (f"{U.points(delta)} of the {cur:.1f}% share was won in the last year alone, so "
            f"the position is newly held rather than established.")


def _defending_lead(f: Dict[str, Any]) -> Optional[str]:
    """Above the peer benchmark, the exposure is holding the lead, not closing a gap."""
    mine = (f.get("sow") or {}).get("current")
    theirs = (f.get("peer") or {}).get("sow")
    if mine is None or theirs is None or mine <= theirs:
        return None
    return (f"At {mine:.1f}% share of wallet the book sits {U.points(mine - theirs)} above "
            f"the top-5 peer average of {theirs:.1f}%, so the task here is defending a lead "
            f"rather than closing a gap.")


def _unplaced_headroom(f: Dict[str, Any]) -> Optional[str]:
    """Even a leading book leaves most of the Marsh pool with other carriers."""
    c, m = f.get("carrier") or {}, f.get("marsh") or {}
    if c.get("current") is None or not m.get("current"):
        return None
    headroom = m["current"] - c["current"]
    if headroom <= 0:
        return None
    return (f"{_money(headroom)} of the {_money(m['current'])} Marsh book is still placed "
            f"with other carriers.")


def _absent_segments(f: Dict[str, Any]) -> Optional[str]:
    """Where the book writes nothing at all - a better answer than undirected headroom."""
    from studio.template_fill import segment_prose as P

    return P.absence_summary(_segments(f), _subject(f))


def _tracking_note(f: Dict[str, Any]) -> Optional[str]:
    """A scope shaped like its parent says so, instead of restating the parent's findings.

    Worth a line on its own: knowing there is no local anomaly to chase is a finding a
    leadership team can use, and it is honest in a way that inventing a local difference
    to fill the column is not.
    """
    from studio.template_fill import segment_prose as P

    return (P.tracking_note(share=(f.get("sow") or {}).get("current"))
            if _tracks_parent(f) else None)


def _marsh_demand(f: Dict[str, Any]) -> Optional[str]:
    """Where the pool itself is growing, the pool is the opportunity."""
    m = f.get("marsh") or {}
    if m.get("pct") is None or m["pct"] <= 0 or not m.get("current"):
        return None
    return (f"Marsh demand grew {_mag(m['pct'])} year on year to {_money(m['current'])}, so "
            f"the pool to win from is getting larger.")


def _book_held(f: Dict[str, Any]) -> Optional[str]:
    """The last thing that is always true: the size of the book itself."""
    c = f.get("carrier") or {}
    if c.get("current") is None:
        return None
    return f"{_subject(f, opening=True)} holds {_money(c['current'])} of Marsh premium here."


# Kind â†’ the fallbacks to try, in order, when its composer produced nothing.
_FALLBACKS: Dict[str, Tuple[Callable[[Dict[str, Any]], Optional[str]], ...]] = {
    "working": (_book_held,),
    "challenges": (_recent_gain, _defending_lead, _unplaced_headroom, _book_held),
    "growth": (_absent_segments, _tracking_note, _unplaced_headroom,
               _marsh_demand, _book_held),
    "key_messages": (_book_held,),
    "thesis": (_book_held,),
    "highlights": (),
}


def _fallback_points(kind: str, f: Dict[str, Any]) -> List[str]:
    """The first fallback for ``kind`` that its figures can carry, as a one-point list."""
    for build in _FALLBACKS.get(kind, ()):
        line = build(f)
        if line:
            return [line]
    return []


_COMPOSERS: Dict[str, Callable[[Dict[str, Any]], List[str]]] = {
    "working": _working_points,
    "challenges": _challenges_points,
    "growth": _growth_points,
    "key_messages": _key_messages_points,
    "thesis": _thesis_points,
    "highlights": _highlights_points,
}


# The fact families that say their own lines. Each owns its family end to end — how the
# fact is loaded and how it is said — and each decides which panels its lines belong to, so
# adding a family is a new module in this tuple rather than an edit to five composers.
#
# They are APPENDED to the composer's own points, never substituted: the composer answers
# the panel's question, and these deepen the answer. That matters to the ledger, which
# thins a page whose claims are already spoken for — a bigger pool is the fix, and a pool
# bucketed per column is the only kind that measured better (see ``stance.PortfolioExtras``).
_FACT_FAMILIES = (facts_mix, facts_trend)


def points(kind: str, f: Dict[str, Any]) -> List[str]:
    """The sentences a panel of ``kind`` is built from — ``[]`` for a KPI callout.

    Falls back to :func:`_fallback_points` when the composer's own question has no figures
    behind it, so a commentary cell is never rendered blank.

    Public because the summary page's prose columns ask the same questions of the same
    facts as these panels do (:mod:`studio.template_fill.commentary`), and the deck should
    answer them in one voice rather than two.
    """
    composer = _COMPOSERS.get(kind)
    if composer is None:
        return []
    said = list(composer(f))
    for family in _FACT_FAMILIES:
        said += [line for line in family.lines_for(kind, f) if line not in said]
    return said or _fallback_points(kind, f)


def facts_for(result) -> Dict[str, Any]:
    """The fact set behind a panel, for ``result``'s own scope and reporting year."""
    return _facts(result, _reporting_filters(result))


def _compose(kind: str, f: Dict[str, Any], limit: int, ledger=None, extras=None) -> str:
    """One commentary cell's bullet list — the composer's points, trimmed to ``limit``.

    Goes through :func:`points` rather than the composer directly, so a cell whose own
    question has no figures behind it still ships its fallback instead of a blank. With a
    :class:`~studio.template_fill.ledger.ClaimLedger` the points are taken through it, so a
    claim an earlier page already made gives way to this page's next-best one.
    """
    from studio.template_fill.openings import vary_openings

    if kind not in _COMPOSERS:
        return _kpi_cell(kind, f)
    said = points(kind, f)
    if extras is not None:
        said = said + [line for line in extras.for_topic(kind) if line not in said]
    if ledger is not None:
        said = ledger.take(said, limit=limit)
    # Every composer opens on the subject, because every one is written to stand alone.
    # Stacked into a cell they read as a roll-call, so all but the first are turned back
    # into "the book" — the same rule the LLM rewrite is held to.
    return _bullets(vary_openings(said[:limit], str(f.get("subject") or "")), limit)


# ── value resolution ─────────────────────────────────────────────────────────


def _reporting_filters(result) -> Dict[str, Any]:
    """The result's filters with the reporting year pinned (max pin, else latest in scope)."""
    from studio.template_fill.bindings import reporting_filters

    return reporting_filters(result)


def _countries_in_scope(result) -> List[str]:
    """Countries by premium (biggest first) — the order the ``Country (n)`` labels use."""
    from studio.template_fill.bindings import _country_breakdown

    return [r["name"] for r in _country_breakdown(result) if r.get("name")]


def _polish(text: str, kind: str, style: Optional[str], subject: str = "",
            facts: Optional[Dict[str, Any]] = None) -> str:
    """LLM re-write behind the faithfulness verifier; KPI cells stay deterministic.

    The cell's ``kind`` IS its commentary topic, so it selects the same per-column brief the
    summary page's columns use (``commentary._TOPIC_BRIEF``) — a country page's Challenges
    cell is asked the same question, of a narrower book.
    """
    if kind not in _COMPOSERS or kind == "highlights" or not text:
        return text
    from studio.template_fill.commentary import plan_rewrite

    return plan_rewrite(text, node=f"feedback-{kind}", style=style, topic=kind,
                        subject=subject, facts=facts)


def _extras(result):
    """This run's portfolio lines — empty for a single-product scope, so a product page
    never describes a portfolio it is only one line of."""
    from studio.template_fill.stance import portfolio_extras

    return portfolio_extras(result)


def with_ledger(ledger, extras=None, *, defer_rewrites: bool = False):
    """This provider bound to a deck's :class:`~studio.template_fill.ledger.ClaimLedger`.

    The provider list is uniform ``(template, result)`` callables, so the per-deck ledger
    is injected here rather than threaded through every provider's signature.
    """
    def provider(template: Template, result) -> Dict[str, Any]:
        return values(template, result, ledger=ledger, extras=extras,
                      defer_rewrites=defer_rewrites)

    provider.__module__ = __name__
    return provider


def values(template: Template, result, *, ledger=None, extras=None,
           defer_rewrites: bool = False) -> Dict[str, Any]:
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
            # A feedback-table row shares its cell with five KPI callouts; a quadrant panel
            # owns a whole column of the slide and can carry the fuller argument.
            limit = _CELL_BULLETS if ordn is not None else _PANEL_BULLETS
            if t["kind"] == "highlights":
                limit = _HIGHLIGHT_BULLETS
            text = _compose(t["kind"], facts_for(country), limit, ledger,
                            extras if extras is not None else _extras(result))
            text_cache[key] = _polish(text, t["kind"], style,
                                      str(getattr(result, "subject", "") or ""),
                                      facts_for(country))
        # KPI callouts always write (a blank beats a stale "$xx.xM" placeholder);
        # an empty commentary keeps the template's ellipsis as a visible fill-me cue.
        if text_cache[key] or t["kind"] not in _COMPOSERS:
            out[role] = text_cache[key]
    logger.info("feedback: resolved %d table cell value(s)", len(out))
    # Every cell above holds either a finished KPI string or a PendingRewrite. The deck
    # writes them all together (``assemble``); a lone caller writes its own here.
    return out if defer_rewrites else rewrites.write_now(out)
