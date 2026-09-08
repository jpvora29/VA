"""The scope bar — named context pills stating the current analytical scope.

One renderer, three surfaces: above the chat composer, at the top of a Boardroom
document, and (as a single line, via :func:`core.scope.scope_line`) on every
exported slide. Because they share this module, the three can never drift.

Pure presentation: the chips are derived in :mod:`core.scope` and arrive here as
plain dicts, so this module needs no application state.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from dash import html

from core.scope import ScopeChip, chips_from_dicts

_EMPTY_HINT = "Scope appears here once you ask a question"


def scope_pill(chip: ScopeChip, *, compact: bool = False, extra_class: str = ""):
    """One pill: what it constrains, and the value it is constrained to.

    ``extra_class`` marks a pill without wrapping it — the chat bar tags folded
    chips this way so they stay direct siblings of the visible ones, which is
    what its ``+ .scope-pill`` separator rule needs.
    """
    classes = ["scope-pill", f"scope-{chip.key}"]
    if compact:
        classes.append("compact")
    if extra_class:
        classes.append(extra_class)
    return html.Div(
        [
            html.I(className=f"{chip.icon} scope-pill-icon"),
            html.Span(chip.label, className="scope-pill-label"),
            html.Span(chip.value, className="scope-pill-value"),
        ],
        className=" ".join(classes),
        title=f"{chip.label}: {chip.value} — {chip.source}",
        **{"data-scope-key": chip.key},
    )


def overflow_pill(hidden: Sequence[ScopeChip]):
    """The ``+N`` chip standing in for scope that did not fit on one line.

    Its title spells out everything it hides, so the scope is never actually
    concealed — only folded. A clientside toggle in :mod:`ui.callbacks` expands
    the bar in place when it is clicked.
    """
    return html.Button(
        f"+{len(hidden)}",
        id="scope-overflow-toggle",
        n_clicks=0,
        className="scope-pill scope-overflow",
        title=" · ".join(f"{chip.label}: {chip.value}" for chip in hidden),
    )


def scope_bar(
    scope: Optional[Sequence[Mapping[str, Any]]],
    *,
    compact: bool = False,
    show_empty: bool = False,
    trailing: Optional[list] = None,
    max_visible: Optional[int] = None,
):
    """The full bar. Returns ``None`` when there is no scope and no empty state.

    ``trailing`` takes extra controls that belong on the same line (the chat
    passes its custom-peers edit/clear buttons, which act on the scope rather
    than merely describing it).

    ``max_visible`` folds everything past the first N chips behind a ``+N``
    button. A turn can resolve six filters at once, and six chips stacked above
    the composer read as a wall the user has to look past to reach the input —
    which is the opposite of what stating the scope is for. The chips are all
    still there; the ones past the cut are marked and hidden by CSS until the
    button expands them.
    """
    chips = chips_from_dicts(scope)
    if not chips and not trailing:
        if not show_empty:
            return None
        return html.Div(
            [html.I(className="bi bi-crosshair scope-empty-icon"), html.Span(_EMPTY_HINT)],
            className="scope-bar is-empty",
        )
    shown, hidden = _split_at(chips, max_visible)
    children = [
        html.Span(
            [html.I(className="bi bi-crosshair"), html.Span("Scope")],
            className="scope-bar-eyebrow",
        )
    ]
    children.extend(scope_pill(chip, compact=compact) for chip in shown)
    if hidden:
        children.extend(
            scope_pill(chip, compact=compact, extra_class="scope-pill-folded")
            for chip in hidden
        )
        children.append(overflow_pill(hidden))
    children.extend(trailing or [])
    return html.Div(children, className="scope-bar" + (" compact" if compact else ""))


def _split_at(
    chips: Sequence[ScopeChip], max_visible: Optional[int]
) -> tuple[list, list]:
    """``(shown, folded)`` — everything shown when there is no limit to apply.

    A limit that would fold a single chip is not applied: replacing one chip with
    a ``+1`` button saves no space and costs the reader a click.
    """
    if not max_visible or len(chips) <= max_visible + 1:
        return list(chips), []
    return list(chips[:max_visible]), list(chips[max_visible:])
