"""The scope bar — named context pills stating the analytical scope of an answer.

One renderer, three surfaces: at the head of each chat answer, at the top of a
Boardroom document, and (as a single line, via :func:`core.scope.scope_line`) on
every exported slide. Because they share this module, the three can never drift.

Pure presentation: the chips are derived in :mod:`core.scope` and arrive here as
plain dicts, so this module needs no application state.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from dash import html

from core.scope import ScopeChip, chips_from_dicts

_EMPTY_HINT = "Scope appears here once you ask a question"


def scope_pill(chip: ScopeChip, *, compact: bool = False):
    """One pill: what it constrains, and the value it is constrained to."""
    classes = ["scope-pill", f"scope-{chip.key}"]
    if compact:
        classes.append("compact")
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


def scope_bar(
    scope: Optional[Sequence[Mapping[str, Any]]],
    *,
    compact: bool = False,
    show_empty: bool = False,
    trailing: Optional[list] = None,
):
    """The full bar. Returns ``None`` when there is no scope and no empty state.

    ``trailing`` takes extra controls that belong on the same line.

    Every chip is shown. The bar used to fold past four behind a ``+N``, because
    stacked above the composer six chips read as a wall between the reader and
    the input. On the answer there is nothing below them to reach, so folding
    only hid facts behind a click.
    """
    chips = chips_from_dicts(scope)
    if not chips and not trailing:
        if not show_empty:
            return None
        return html.Div(
            [html.I(className="bi bi-crosshair scope-empty-icon"), html.Span(_EMPTY_HINT)],
            className="scope-bar is-empty",
        )
    children = [
        html.Span(
            [html.I(className="bi bi-crosshair"), html.Span("Scope")],
            className="scope-bar-eyebrow",
        )
    ]
    children.extend(scope_pill(chip, compact=compact) for chip in chips)
    children.extend(trailing or [])
    return html.Div(children, className="scope-bar" + (" compact" if compact else ""))
