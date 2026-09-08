"""One busy overlay per area of the app, raised by whichever callback is working.

The problem this solves is that most of what makes the user wait here is a *callback*,
not a background job: a mode switch rebuilds the whole Studio body, a filter change
re-derives four panels, an upload parses a spreadsheet, Export fills a template. None of
those has anything to show while it runs, so the screen simply sat there.

The shape is deliberately the one Setup already proved out:

  * every callback that can make the user wait raises its OWN flag (``running=``) — one
    shared flag would race, because the fastest callback's "finished" would lower the
    overlay while a slower sibling was still working;
  * the overlay watches all of its scope's flags at once and comes down when the last
    one settles;
  * a clientside tracker holds it up for a minimum time (``assets/va_busy.js``), so work
    answered in 90ms reads as progress rather than as a flash.

``dcc.Loading`` is not used for this: it decides for itself whether a subtree is loading
and consistently missed the FIRST change after a page load — the one a user is least
sure about. ``running=`` is declared per callback, so it always fires.

A scope is data (:class:`BusyScope`), so adding a new one is a scope + a mount + a
``register_busy`` call, and adding a new reason to wait is one more :class:`BusyFlag`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple

from dash import ClientsideFunction, Input, Output, State, html

#: Resting class of a flag; ``is-busy`` is added while its callback runs.
FLAG_CLASS = "va-busy-flag"
FLAG_ON = f"{FLAG_CLASS} is-busy"

#: How much work every flag tolerates before its overlay appears at all.
#:
#: This is not a cosmetic delay, it is what makes the mechanism usable at all. Dash
#: re-runs a callback whenever the component carrying its Input is MOUNTED, not only
#: when someone acts — and Studio renders its entire body from a callback, so one mode
#: switch re-fires the Data page's handlers, Export's and Setup's cascade, each of which
#: answers ``no_update`` immediately. Measured on the running app those take 33-90ms;
#: real work takes hundreds. 150ms sits between the two with room either side.
#:
#: The dwell in ``assets/va_busy.js`` then holds a shown overlay for long enough to read,
#: so the pair reads as: say nothing about work that finished before you noticed it, and
#: say it properly about work that did not.
DEFAULT_GRACE_MS = 150


@dataclass(frozen=True)
class BusyFlag:
    """One reason the app can be busy: a DOM id to raise, and what to say while it is up.

    The label travels with the flag rather than with the overlay because "Loading…" is
    not worth interrupting someone for — "Reading your data…" is.

    ``grace_ms`` is how much work to tolerate before the overlay appears — see
    :data:`DEFAULT_GRACE_MS` for why every flag has one. Raise it for a callback that
    ALSO re-runs on something incidental and more often: Studio's master render is
    re-run by every keystroke in the component-library search, where even the default
    would flash an overlay per character.
    """

    id: str
    label: str
    grace_ms: int = DEFAULT_GRACE_MS


@dataclass(frozen=True)
class BusyScope:
    """The overlay for one area of the app, and every flag that raises it."""

    overlay_id: str
    flags: Tuple[BusyFlag, ...]

    def flag_ids(self) -> Tuple[str, ...]:
        return tuple(f.id for f in self.flags)


def busy_overlay(scope: BusyScope) -> html.Div:
    """The spinner for ``scope``, plus the hidden flags its callbacks raise.

    Mount this somewhere that is NOT rebuilt by the callbacks it covers — a flag inside
    a subtree that a mode switch replaces would be gone at the moment it is needed.
    """
    return html.Div(
        [
            *(_flag(flag) for flag in scope.flags),
            html.Div(
                [
                    html.Div(className="qs-page-spinner"),
                    html.Div("", className="va-busy-label", id=f"{scope.overlay_id}-label"),
                ],
                className="qs-page-loader va-busy-overlay",
                id=scope.overlay_id,
            ),
        ],
        className="qs-busy-host",
    )


def _flag(flag: BusyFlag) -> html.Div:
    """A hidden marker div. The data attributes are static; only the className changes."""
    return html.Div(
        id=flag.id,
        className=FLAG_CLASS,
        **{"data-label": flag.label, "data-grace": str(int(flag.grace_ms))},
    )


def busy_running(*flag_ids: str) -> List[Tuple[Any, str, str]]:
    """The ``running=`` argument that raises ``flag_ids`` for the length of a callback.

    Returned as a list of ``(Output, during, after)`` so a callback can raise more than
    one flag, and so the resting value is the plain class rather than a blank string —
    the flag has to stay findable between runs.
    """
    return [(Output(fid, "className"), FLAG_ON, FLAG_CLASS) for fid in flag_ids]


def register_busy(app, scope: BusyScope) -> None:
    """Follow every flag in ``scope`` at once and drive its overlay from them.

    Clientside, because the only work is holding the overlay up for a minimum time: a
    round trip to the server to decide whether to show a "talking to the server" spinner
    would be self-defeating. The overlay's own ``id`` is passed as State so one JS
    function serves every scope.
    """
    app.clientside_callback(
        ClientsideFunction(namespace="vaBusy", function_name="track"),
        Output(scope.overlay_id, "data-busy"),
        [Input(fid, "className") for fid in scope.flag_ids()],
        State(scope.overlay_id, "id"),
    )


# ── the shell's own scope ────────────────────────────────────────────────────
#
# Two waits happen above the workspaces and so cannot be covered by any of them.
#
# Signing in is the longer one by far: the gate builds ALL FOUR workspaces at once (that
# is what lets a half-built deck survive a trip to the Chatbot), which means one click
# lists the user's conversations, generates their starter questions, reads the Studio
# stores and composes Studio's whole body. It used to sit on the sign-in card, unchanged,
# for as long as that took.
#
# Switching workspace is the shorter one — the panes are already mounted, so it is a
# class flip — but it still round-trips, so it gets a grace and shows only if the server
# is slow enough for the click to feel dropped.
BUSY_SIGNIN = "va-busy-signin"
BUSY_TAB = "va-busy-tab"

SHELL_BUSY = BusyScope(
    overlay_id="va-shell-busy",
    flags=(
        BusyFlag(BUSY_SIGNIN, "Setting up your workspace…"),
        BusyFlag(BUSY_TAB, "Switching workspace…", grace_ms=250),
    ),
)


__all__ = [
    "BusyFlag", "BusyScope", "FLAG_CLASS", "FLAG_ON", "DEFAULT_GRACE_MS",
    "SHELL_BUSY", "BUSY_SIGNIN", "BUSY_TAB",
    "busy_overlay", "busy_running", "register_busy",
]
