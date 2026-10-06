"""What an answer's reader sees first: its sections, and its numbers at a glance.

Two pure readings of things the answer already contains — nothing here writes a
sentence or computes a figure the evidence does not hold:

    split_sections   the Markdown answer as (intro, titled sections), each with
                     a TONE, so the card can lay the analysis out as numbered
                     takeaways and set "what it means" apart as the next step
    badge_for        the one figure a takeaway turns on (a change, a rank
                     move) or "Watch-out", for the chip beside it — read off
                     the section's own words, never computed
    scorecards       the headline KPIs per market, read off the position tables
                     the answer was written from (sums and one ratio of their
                     own columns), so the summary band states the numbers a
                     leader looks for before reading a word

Dash-free, so both are unit-testable on strings and dicts.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── Sections ────────────────────────────────────────────────────────────────

DEFAULT, ACTION, RISK = "default", "action", "risk"

_ACTION = re.compile(r"what it means|so what|implication|recommend|what to do|next step|"
                     r"talking point|actions?\b|the moves", re.I)
_RISK = re.compile(r"watch|risk|caveat|limitation|what the data does not|could not", re.I)

#: An icon per kind of section, read off its title.
_ICONS: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (_ACTION, "bi bi-lightning-charge"),
    (_RISK, "bi bi-exclamation-triangle"),
    (re.compile(r"product|line|industry|segment|mix", re.I), "bi bi-box-seam"),
    (re.compile(r"moved|drove|driver|growth|change|offset|trend|quarter|timing", re.I), "bi bi-activity"),
    (re.compile(r"position|peer|rank|wallet|standing|market position|against", re.I), "bi bi-trophy"),
    (re.compile(r"broker|survey|sentiment", re.I), "bi bi-chat-quote"),
    (re.compile(r"\bmarkets?\b|countr|region|geograph", re.I), "bi bi-globe2"),
    (re.compile(r"concentrat|book", re.I), "bi bi-pie-chart"),
)


@dataclass(frozen=True)
class Section:
    title: str
    body: str
    tone: str = DEFAULT
    icon: str = "bi bi-dot"

    @property
    def points(self) -> int:
        """How many list points the section holds."""
        return sum(1 for line in self.body.splitlines()
                   if line.lstrip()[:2] in ("- ", "* ", "+ ") or line.lstrip()[:3].rstrip(".").isdigit())

    @property
    def has_table(self) -> bool:
        return any(line.lstrip().startswith("|") for line in self.body.splitlines())


def icon_for(title: str) -> str:
    for pattern, icon in _ICONS:
        if pattern.search(title):
            return icon
    return "bi bi-geo-alt" if _looks_like_place(title) else "bi bi-dot"


def _looks_like_place(title: str) -> bool:
    """A one-to-three-word proper name ("Singapore", "Hong Kong") is a market."""
    words = title.split()
    return 1 <= len(words) <= 3 and all(w[:1].isupper() for w in words)


def tone_for(title: str) -> str:
    if _ACTION.search(title):
        return ACTION
    if _RISK.search(title):
        return RISK
    return DEFAULT


_HEADING = re.compile(r"^\s{0,3}#{2,3}\s+(.+?)\s*#*\s*$")


def split_sections(markdown: str) -> Tuple[str, List[Section]]:
    """(the text before the first ## / ### heading, [titled sections]).

    A heading with nothing under it is dropped. Text with no headings is all
    intro, and renders exactly as before.
    """
    intro: List[str] = []
    sections: List[Tuple[str, List[str]]] = []
    for line in (markdown or "").splitlines():
        match = _HEADING.match(line)
        if match:
            sections.append((match.group(1).strip().strip("*"), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            intro.append(line)
    out = [
        Section(title, "\n".join(body).strip(), tone_for(title), icon_for(title))
        for title, body in sections
        if "\n".join(body).strip()
    ]
    return "\n".join(intro).strip(), out


# ── Takeaway badges ─────────────────────────────────────────────────────────

UP, DOWN, WARN = "up", "down", "warn"

_PCT = r"\d[\d,]*(?:\.\d+)?%"
#: "up"/"down" count only as "up by 4%": "make up 72.6% of premium" is a share,
#: not a rise.
_RISE_WORDS = r"grew|grows|rose|rises|increased|increases|gained|gains|up(?=\s+by\b)"
_FALL_WORDS = r"fell|falls|dropped|drops|declined|declines|decreased|shrank|lost|down(?=\s+by\b)"
_FALLS = frozenset("fell falls dropped drops declined declines decreased shrank lost down".split())
#: The capitalised name just before a movement verb ("Property grew 60%").
_SUBJECT = r"(?P<subject>[A-Z][\w&/-]*(?:\s[A-Z][\w&/-]*){0,2})\s+(?:premium\s+)?"
_VERBED = re.compile(
    rf"(?:{_SUBJECT})?\b(?P<verb>{_RISE_WORDS}|{_FALL_WORDS})\s+(?:by\s+)?(?P<figure>{_PCT})")
#: "+14.2%", "▼ 3.1%" — a sign attached to a figure, never a range or a dash.
_SIGNED = re.compile(rf"(?<![\w.$])(?P<sign>[+\-−▲▼])\s?(?P<figure>{_PCT})")
_RANK_MOVE = re.compile(r"from\s+(?:#)?(?P<before>\d+)(?:st|nd|rd|th)?\s+to\s+(?:#)?(?P<after>\d+)"
                        r"(?:st|nd|rd|th)?\b")


#: A point that leads with its subject in bold: "**Property** — $8.2M ▲ 14.2%".
_LEAD_SUBJECT = re.compile(r"^\*\*([^*]+)\*\*")


@dataclass(frozen=True)
class Badge:
    """The chip beside a takeaway: its text and how it reads (up/down/warn)."""

    text: str
    tone: str


def _change_badge(text: str) -> Optional[Badge]:
    verbed, signed = _VERBED.search(text), _SIGNED.search(text)
    first = min((m for m in (verbed, signed) if m), key=lambda m: m.start(), default=None)
    if first is None:
        return None
    if first is verbed:
        up = first.group("verb").lower() not in _FALLS
        subject = (first.group("subject") or "").strip()
    else:
        up = first.group("sign") in "+▲"
        lead = _LEAD_SUBJECT.match(_POINT.sub("", text.strip(), count=1))
        subject = lead.group(1).strip() if lead and len(lead.group(1)) <= 24 else ""
    arrow = "▲" if up else "▼"
    label = f"{subject} {arrow} {first.group('figure')}".strip()
    return Badge(label, UP if up else DOWN)


def _rank_badge(text: str) -> Optional[Badge]:
    match = _RANK_MOVE.search(text)
    if not match or not re.search(r"\brank|\bplace|among|\d(?:st|nd|rd|th)\b", text, re.I):
        return None
    before, after = int(match.group("before")), int(match.group("after"))
    if before == after:
        return None
    return Badge(f"Rank #{before} → #{after}", UP if after < before else DOWN)


def badge_for(section: Section) -> Optional[Badge]:
    """The chip for one takeaway, or None when its words carry no clear figure.

    A watch-out says so; otherwise the FIRST movement the section states — a
    percentage change, else a rank move. Only figures already in the text are
    used, and a section with none gets no chip rather than an invented one.
    """
    if section.tone == RISK:
        return Badge("Watch-out", WARN)
    # The chip belongs to the line the reader sees: the section's lead point.
    points = split_points(section.body)
    lead = points[0] if points else section.body
    return _change_badge(lead) or _rank_badge(lead)


_POINT = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+")
#: "### By product", "### By market", "### By industry" — a per-line list the
#: position table already holds, so it is detail, not a takeaway.
_PER_LINE = re.compile(r"^by\s+\w+", re.I)


def split_points(body: str) -> List[str]:
    """A section body as its points, in order: list items, paragraphs, tables.

    A list item keeps its continuation lines; a table stays one block. Markers
    are stripped — the caller decides how the points are drawn.
    """
    blocks: List[List[str]] = []
    kind = ""  # "point" | "para" | "table" — what the open block is
    for line in (body or "").splitlines():
        stripped = line.strip()
        if not stripped:
            kind = "" if kind != "point" else "point-gap"
            continue
        if _POINT.match(line):
            blocks.append([_POINT.sub("", line, count=1)])
            kind = "point"
        elif stripped.startswith("|"):
            if kind == "table":
                blocks[-1].append(stripped)
            else:
                blocks.append([stripped])
                kind = "table"
        elif kind in ("point", "para"):
            blocks[-1].append(stripped)
        else:
            blocks.append([stripped])
            kind = "para"
    return ["\n".join(b) if b[0].startswith("|") else " ".join(b) for b in blocks]


def is_per_line(section: Section) -> bool:
    """A "By product" / "By market" list: one point per line of the table."""
    return bool(_PER_LINE.match(section.title))


def takeaways_and_next_steps(sections: Sequence[Section]) -> Tuple[List[Section], List[Section]]:
    """(the findings, in order) and (the "what it means / what to do" parts)."""
    findings = [s for s in sections if s.tone != ACTION]
    steps = [s for s in sections if s.tone == ACTION]
    return findings, steps


# ── Scorecards ──────────────────────────────────────────────────────────────

CARRIER, MARSH, YOY, SOW, SOP = (
    "Carrier premium", "Marsh premium", "YoY %", "Share of wallet", "Share of portfolio")


@dataclass(frozen=True)
class Scorecard:
    """The headline numbers for one market (or the one scope)."""

    market: str = ""
    premium: Optional[float] = None
    unit: str = ""
    yoy: Optional[float] = None
    share_of_wallet: Optional[float] = None
    top_line: str = ""
    top_share: Optional[float] = None
    lines: int = 0
    #: The line whose premium moved most, among lines big enough to matter.
    mover_line: str = ""
    mover_yoy: Optional[float] = None
    is_market_view: bool = False
    extras: Dict[str, Any] = field(default_factory=dict)


def _number(value: Any) -> Optional[float]:
    """A cell as a float; None for blank, text, or NaN (an absent figure)."""
    try:
        number = None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None
    return None if number is None or math.isnan(number) else number


def scorecard_from(label: str, columns: Sequence[str], records: Sequence[Dict[str, Any]],
                   unit: str = "") -> Optional[Scorecard]:
    """One market's KPIs from its position table, or None when it is not one.

    Premium and the Marsh book are SUMS of their columns; YoY is the total
    against each line's prior value recovered from its own YoY %; share of
    wallet is the carrier total over the book total. Arithmetic on the table,
    stated as totals of it — nothing the table does not already hold.
    """
    if not records or not columns:
        return None
    first = columns[0]
    market = "" if label in ("", "Position") else label
    if CARRIER not in columns:
        if MARSH not in columns:
            return None
        values = [(r.get(first), _number(r.get(MARSH))) for r in records]
        values = [(n, v) for n, v in values if v is not None]
        if not values:
            return None
        total = sum(v for _, v in values)
        top = max(values, key=lambda item: item[1])
        return Scorecard(market=market, premium=total, unit=unit, top_line=str(top[0]),
                         top_share=(top[1] / total * 100) if total else None,
                         lines=len(values), is_market_view=True)
    current = prior = carrier_total = marsh_total = 0.0
    top_line, top_value, top_share, lines = "", None, None, 0
    for row in records:
        premium = _number(row.get(CARRIER))
        if premium is None:
            continue
        lines += 1
        carrier_total += premium
        marsh = _number(row.get(MARSH))
        if marsh is not None:
            marsh_total += marsh
        yoy = _number(row.get(YOY))
        if yoy is not None and yoy > -100:
            current += premium
            prior += premium / (1 + yoy / 100)
        if top_value is None or premium > top_value:
            top_line, top_value, top_share = str(row.get(first)), premium, _number(row.get(SOP))
    if not lines:
        return None
    mover_line, mover_yoy = biggest_mover(records, first, carrier_total)
    return Scorecard(
        market=market, premium=carrier_total, unit=unit,
        yoy=((current - prior) / prior * 100) if prior else None,
        share_of_wallet=(carrier_total / marsh_total * 100) if marsh_total else None,
        top_line=top_line, top_share=top_share, lines=lines,
        mover_line=mover_line, mover_yoy=mover_yoy,
    )


#: A line under this share of the carrier's premium cannot be the headline
#: mover: +300% on a sliver is noise beside -10% on the biggest line.
MATERIAL_SHARE = 0.05


def biggest_mover(records: Sequence[Dict[str, Any]], first: str,
                  total: float) -> Tuple[str, Optional[float]]:
    """(line, YoY %) with the largest absolute change among material lines."""
    best: Tuple[str, Optional[float]] = ("", None)
    for row in records:
        premium, yoy = _number(row.get(CARRIER)), _number(row.get(YOY))
        if premium is None or yoy is None or not total or premium / total < MATERIAL_SHARE:
            continue
        if best[1] is None or abs(yoy) > abs(best[1]):
            best = (str(row.get(first)), yoy)
    return best


def _is_market_tab(label: str) -> bool:
    """A tab named after a market ("Singapore"), not a cut ("By product")."""
    return bool(label) and label != "Position" and not label.startswith("By ")


def scorecards(views: Sequence[Any]) -> List[Scorecard]:
    """One scorecard per MARKET table; otherwise one for the whole scope.

    A "By country" and a "By product" table are two cuts of the same book —
    they total the same, so one card states it once.
    """
    tables = [v for v in views or []
              if CARRIER in (getattr(v, "column_kinds", None) or {})
              or MARSH in (getattr(v, "column_kinds", None) or {})]
    markets = [v for v in tables if _is_market_tab(getattr(v, "label", ""))]
    if markets:
        cards = [_card(v, market=True) for v in markets[:4]]
        return [c for c in cards if c is not None]
    # One scope: the KPIs come from the cut by product (or industry); a table
    # cut by country adds WHERE the book is — the largest market.
    geography = [v for v in tables if _first_column(v) in _GEOGRAPHY]
    lines = [v for v in tables if _first_column(v) not in _GEOGRAPHY]
    card = _card((lines or geography)[0]) if tables else None
    if card is None:
        return []
    if lines and geography:
        where = _card(geography[0])
        if where is not None and where.top_line:
            card = replace(card, extras={"top_market": where.top_line,
                                         "top_market_share": where.top_share})
    return [card]


_GEOGRAPHY = frozenset({"Country", "Market", "Region"})


def _first_column(view: Any) -> str:
    columns = list(getattr(view, "columns", []) or [])
    return str(columns[0]) if columns else ""


def _card(view: Any, market: bool = False) -> Optional[Scorecard]:
    label = getattr(view, "label", "")
    return scorecard_from(label if market else "", list(getattr(view, "columns", [])),
                          list(getattr(view, "records", [])), getattr(view, "unit", ""))
