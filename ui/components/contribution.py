"""What drove the movement — the read first, then the evidence for it.

The panel used to open with a chart, which makes the reader derive the conclusion
from a picture. The conclusion is one sentence and it is computable, so the panel
states it, and the bars are what you look at to check it.

**Then it drew the same bars every time**, which is the report this version
answers: the fourth visit looked exactly like the first, so the panel stopped
being read. A decline carried by two countries and a decline spread across eleven
product lines are different findings and must not look alike. So the LEAD changes
with the shape of the result (:mod:`core.answers.shape`):

    single        the slice, stated, with its share of everything that moved
    concentrated  a stacked bar: these few against the rest
    offsetting    three cards — lost, gained, net — because the net is the lie
    broad         a strip of every slice, shaded, because the spread IS the point
    mixed         no clean pattern; the ranked bars lead on their own

The ranked bars stay UNDER all of them. The lead is what changed; the evidence is
what is checkable, and swapping the evidence out per shape would mean the reader
could not compare two answers. Under that, when the rows carry enough history,
"what changed unexpectedly" — the slice that is small but has just turned, which
a ranking by size can never surface (:mod:`core.answers.unusual`).

Percentages of the move can exceed 100 and can go negative — see
:mod:`core.answers.contribution`. They are printed as computed, because a slice
that fell further than the whole is exactly the finding worth showing.

Pure presentation; the arithmetic is in core.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from dash import html

from core.answers import shape as shape_mod
from core.boardroom.money import format_money

# Widest a bar gets, as a percentage of the WHOLE track.
#
# A bar grows from the centre line outwards, so half the track is all it has:
# at 96 the biggest mover ran off the panel and over the row label. 48 leaves a
# hair of margin at the edge.
_MAX_BAR_PCT = 48.0

# Slices shown before the tail is folded into one row. Beyond this the list stops
# being a finding and becomes a data dump.
_MAX_DRIVERS = 8


def _pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    # "+0%" and "-0%" are both wrong for a slice that did not move, and "-0%" is
    # what a tiny negative rounds to. Zero is zero.
    return "0%" if round(number) == 0 else f"{number:+.0f}%"


def _signed_money(value: Any) -> str:
    """A movement with its sign OUTSIDE the currency: -$3.1m, not $-3.1m.

    `format_money` puts the symbol first and lets the number carry the sign,
    which reads as a negative currency rather than a fall.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if number < 0 else "+" if number > 0 else ""
    return f"{sign}{format_money(abs(number))}"


def _share_column(payload: Dict[str, Any]):
    """The heading for the last column, and the text for each slice.

    Normally a slice's share of the TOTAL movement. But on an offsetting result
    the net is tiny by definition, so dividing by it produced "+3100%" and
    "-2900%" — arithmetically correct, and a share of the very number the lead
    has just said to ignore. There the share is taken of the gross movement
    instead, which is the quantity the finding is actually about.
    """
    profile = payload.get("profile") or {}
    gross = float(profile.get("gross") or 0.0)
    if str(payload.get("shape") or "") != shape_mod.OFFSETTING or not gross:
        return "Of total", {
            str(d.get("name")): _pct(d.get("share_pct")) for d in (payload.get("drivers") or [])
        }
    return "Of movement", {
        str(d.get("name")): f"{abs(float(d.get('delta') or 0.0)) / gross * 100:.0f}%"
        for d in (payload.get("drivers") or [])
    }


# ── the lead, one per shape ──────────────────────────────────────────────────
#
# Each takes the payload and returns the picture that makes ITS finding obvious.
# They are siblings, picked from a dict below — never a chain of ifs inside one
# function, because adding a shape should be adding a row, not editing a branch.


def _leaders_and_drivers(payload: Dict[str, Any]):
    """The slices the lead names, and every driver keyed by name."""
    profile = payload.get("profile") or {}
    leaders = [str(n) for n in (profile.get("leaders") or [])]
    by_name = {str(d.get("name")): d for d in (payload.get("drivers") or [])}
    return profile, leaders, by_name


def _concentration_bar(payload: Dict[str, Any]):
    """These few, against everything else — one bar, split.

    The finding is a proportion, and a proportion wants one bar rather than a
    ranked list the reader has to add up in their head.
    """
    profile, leaders, by_name = _leaders_and_drivers(payload)
    covered = float(profile.get("covered_pct") or 0.0)
    gross = float(profile.get("gross") or 0.0) or 1.0
    segments = [
        html.Div(
            className="conc-seg lead",
            style={"width": f"{abs(float(by_name[n].get('delta') or 0)) / gross * 100:.1f}%"},
            title=f"{n}: {_signed_money(by_name[n].get('delta'))}",
        )
        for n in leaders
        if n in by_name
    ]
    rest = max(0.0, 100.0 - covered)
    if rest > 0:
        segments.append(
            html.Div(
                className="conc-seg rest",
                style={"width": f"{rest:.1f}%"},
                title=f"everything else: {rest:.0f}% of the movement",
            )
        )
    others = int(profile.get("total_slices") or 0) - len(leaders)
    return html.Div(
        [
            html.Div(segments, className="conc-bar"),
            html.Div(
                [
                    html.Span(f"{', '.join(leaders)} — {covered:.0f}%",
                              className="conc-key lead"),
                    html.Span(f"the other {others} — {rest:.0f}%" if others > 0 else "",
                              className="conc-key rest"),
                ],
                className="conc-keys",
            ),
        ],
        className="contrib-lead conc",
    )


def _gains_losses_cards(payload: Dict[str, Any]):
    """Lost, gained, net — because on an offsetting result the net is the lie.

    "Premium was flat" is technically true and completely misleading when $3.1m
    of falls cancelled $2.9m of growth. Three cards put the two real numbers
    either side of the small one they produced.
    """
    profile = payload.get("profile") or {}
    cards = (
        ("Lost", float(profile.get("lost") or 0.0), "down"),
        ("Gained", float(profile.get("gained") or 0.0), "up"),
        ("Net", float(profile.get("net") or 0.0), "net"),
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Span(label, className="gl-label"),
                    html.Span(_signed_money(value), className=f"gl-value {tone}"),
                ],
                className=f"gl-card {tone}",
            )
            for label, value, tone in cards
        ],
        className="contrib-lead gains-losses",
    )


def _spread_strip(payload: Dict[str, Any]):
    """Every slice as one shaded cell — the point is that they nearly all moved.

    A ranked bar chart of eleven near-equal movements is a picture of nothing.
    A strip is a picture of "all of it", which is the finding.
    """
    drivers = list(payload.get("drivers") or [])
    widest = max((abs(float(d.get("delta") or 0.0)) for d in drivers), default=0.0) or 1.0
    cells = []
    for driver in drivers:
        delta = float(driver.get("delta") or 0.0)
        # Opacity carries magnitude; the floor keeps a barely-moved slice visible
        # rather than blank, which would read as missing data.
        strength = 0.22 + 0.78 * (abs(delta) / widest)
        tone = "up" if delta > 0 else "down" if delta < 0 else "flat"
        cells.append(
            html.Div(
                html.Span(str(driver.get("name") or ""), className="spread-name"),
                className=f"spread-cell {tone}",
                style={"opacity": f"{strength:.2f}"},
                title=f"{driver.get('name')}: {_signed_money(delta)}",
            )
        )
    return html.Div(
        [
            html.Div(cells, className="spread-grid"),
            html.Div("Shaded by size of move · red fell, green grew", className="spread-key"),
        ],
        className="contrib-lead spread",
    )


def _single_callout(payload: Dict[str, Any]):
    """One slice is the story, so it is stated at size rather than ranked."""
    profile, leaders, by_name = _leaders_and_drivers(payload)
    if not leaders or leaders[0] not in by_name:
        return None
    delta = float(by_name[leaders[0]].get("delta") or 0.0)
    covered = min(100.0, float(profile.get("covered_pct") or 0.0))
    tone = "up" if delta >= 0 else "down"
    return html.Div(
        [
            html.Div(
                [
                    html.Span(leaders[0], className="single-name"),
                    html.Span(_signed_money(delta), className=f"single-delta {tone}"),
                ],
                className="single-headline",
            ),
            html.Div(
                html.Div(className=f"single-fill {tone}", style={"width": f"{covered:.1f}%"}),
                className="single-track",
            ),
            html.Div(f"{covered:.0f}% of everything that moved", className="single-key"),
        ],
        className="contrib-lead single",
    )


# Shape -> the picture that makes its finding obvious. A shape with no entry has
# no lead visual and falls through to the ranked bars, which is the honest
# default rather than a wrong picture.
_LEADS = {
    shape_mod.CONCENTRATED: _concentration_bar,
    shape_mod.OFFSETTING: _gains_losses_cards,
    shape_mod.BROAD: _spread_strip,
    shape_mod.SINGLE: _single_callout,
}


def _lead_visual(payload: Dict[str, Any]):
    """The picture for this result's shape, or None where the bars say it best."""
    draw = _LEADS.get(str(payload.get("shape") or ""))
    return draw(payload) if draw else None


def _unusual_row(item: Dict[str, Any]):
    delta = float(item.get("delta") or 0.0)
    icon = "bi bi-arrow-repeat" if item.get("kind") == "reversal" else "bi bi-graph-up-arrow"
    return html.Div(
        [
            html.I(className=icon),
            html.Span(str(item.get("name") or ""), className="odd-name"),
            html.Span(_signed_money(delta),
                      className="odd-delta " + ("up" if delta >= 0 else "down")),
            html.Span(str(item.get("reason") or ""), className="odd-reason"),
        ],
        className="odd-row" + (" told" if item.get("is_leader") else ""),
    )


def _unusual_section(payload: Dict[str, Any]):
    """What changed unexpectedly — silent unless the rows carry the history.

    The ranking above answers "what moved most", which the biggest part of the
    book wins every quarter. This answers the other one, and it is the half worth
    coming back for.
    """
    items = list(payload.get("unusual") or [])
    if not items:
        return None
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-lightbulb"),
                    html.Span("What changed unexpectedly", className="odd-title"),
                ],
                className="odd-head",
            ),
            html.Div([_unusual_row(i) for i in items], className="odd-rows"),
            html.Div(
                "Largest is not the same as unusual: each slice here is measured "
                "against its own history, not against the others.",
                className="odd-foot",
            ),
        ],
        className="contrib-odd",
    )


def _tone(delta: float) -> str:
    """A slice that did not move is not a rise — green on $0 reads as growth."""
    return "up" if delta > 0 else "down" if delta < 0 else "flat"


def _driver_row(
    driver: Dict[str, Any],
    widest: float,
    leaders: Sequence[str] = (),
    share: str = "—",
):
    """One slice's movement. A slice the lead sentence NAMED is marked, so the
    sentence and the evidence under it point at the same rows."""
    delta = float(driver.get("delta") or 0.0)
    named = str(driver.get("name") or "") in (leaders or ())
    width = min(_MAX_BAR_PCT, abs(delta) / widest * _MAX_BAR_PCT) if widest else 0.0
    positive = delta >= 0
    tone = _tone(delta)
    bar = html.Div(
        html.Div(
            className=f"contrib-bar-fill {'up' if positive else 'down'}",
            style={"width": f"{width:.1f}%", ("left" if positive else "right"): "50%"},
        ),
        className="contrib-bar-track",
        title=(
            f"{driver.get('name')}: {format_money(driver.get('prior'))} → "
            f"{format_money(driver.get('current'))}"
        ),
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Span(str(driver.get("name") or ""), className="contrib-name-text"),
                    html.Span(
                        f"{format_money(driver.get('prior'))} → {format_money(driver.get('current'))}",
                        className="contrib-name-sub",
                    ),
                ],
                className="contrib-name",
            ),
            bar,
            html.Span(_signed_money(delta), className=f"contrib-delta {tone}"),
            html.Span(share, className="contrib-share"),
        ],
        className="contrib-row" + (" is-lead" if named else ""),
    )


def _foot_note(payload: Dict[str, Any]) -> str:
    """What the last column means — which is not the same in every shape.

    The standing caveat explains a share ABOVE 100%, which only happens when the
    column is a share of the net. On an offsetting result it is a share of the
    gross instead and cannot exceed 100, so the caveat would be explaining
    something the reader is not looking at.
    """
    computed = "Computed from the rows behind the answer above"
    if str(payload.get("shape") or "") == shape_mod.OFFSETTING:
        return (
            f"{computed} — shares are of everything that moved, not of the net, "
            "which is close to zero here."
        )
    return (
        f"{computed} — share of move can pass 100% when one slice is offset "
        "by another."
    )


def contribution_panel(payload: Dict[str, Any] | None):
    """The decomposition, or the honest note saying why there isn't one."""
    payload = payload or {}
    drivers: List[Dict[str, Any]] = list(payload.get("drivers") or [])
    note = str(payload.get("note") or "").strip()

    if not drivers:
        if not note:
            return None
        return html.Div(
            [html.I(className="bi bi-info-circle"), html.Span(note)],
            className="message contrib-panel is-empty",
        )

    shown = drivers[:_MAX_DRIVERS]
    widest = max((abs(float(d.get("delta") or 0.0)) for d in shown), default=0.0)
    leaders = [str(n) for n in ((payload.get("profile") or {}).get("leaders") or [])]
    share_label, shares = _share_column(payload)
    move = payload.get("total_move")
    measure = str(payload.get("measure") or "the measure").replace("_", " ")
    dimension = str(payload.get("dimension") or "").replace("_", " ")

    header = html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-diagram-3 contrib-icon"),
                    html.Span("What drove the movement", className="contrib-title"),
                ],
                className="contrib-heading",
            ),
            html.Div(
                f"{measure} by {dimension} · {payload.get('prior_period')} → "
                f"{payload.get('current_period')}",
                className="contrib-basis",
            ),
        ],
        className="contrib-header",
    )

    # The finding, in words, before anything has to be read off a bar.
    headline = html.Div(str(payload.get("headline") or ""), className="contrib-headline")

    total = html.Div(
        [
            html.Span("Total", className="contrib-total-label"),
            html.Span(format_money(payload.get("prior_total")), className="contrib-total-from"),
            html.I(className="bi bi-arrow-right"),
            html.Span(format_money(payload.get("current_total")), className="contrib-total-to"),
            html.Span(
                _signed_money(move),
                className="contrib-total-move " + ("up" if (move or 0) >= 0 else "down"),
            ),
        ],
        className="contrib-total",
    )

    # Column headings, so a bar and a percentage are not left to be guessed at.
    legend = html.Div(
        [
            html.Span(str(payload.get("dimension_label") or "Slice"), className="contrib-name"),
            html.Span("Movement", className="contrib-col-bar"),
            html.Span("Change", className="contrib-col-delta"),
            html.Span(share_label, className="contrib-col-share"),
        ],
        className="contrib-row contrib-legend",
    )

    rows = [
        _driver_row(d, widest, leaders, shares.get(str(d.get("name")), "—"))
        for d in shown
    ]
    if len(drivers) > _MAX_DRIVERS:
        rest = len(drivers) - _MAX_DRIVERS
        rows.append(
            html.Div(
                f"+{rest} smaller slice{'s' if rest > 1 else ''} not shown",
                className="contrib-more",
            )
        )

    # Reading order: what kind of movement this is, the picture that proves it,
    # the totals, then the per-slice evidence, then what is out of character.
    # The lead changes with the shape; everything below it does not, so two
    # answers stay comparable.
    return html.Div(
        [
            header,
            headline,
            _lead_visual(payload),
            total,
            html.Div([legend] + rows, className="contrib-rows"),
            _unusual_section(payload),
            html.Div(
                [html.I(className="bi bi-calculator"), html.Span(_foot_note(payload))],
                className="contrib-foot",
            ),
        ],
        className=f"message contrib-panel shape-{payload.get('shape') or 'mixed'}",
    )
