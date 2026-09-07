"""Setup mode — the real build form, wired to the DB.

``setup_body`` composes the voice questions, the data source, the scope filters, the peer
sets and the survey identities, plus the live scope-preview aside, the Generate button and
"What's in your QBR" — the per-page include/exclude list that decides the deck's shape
(:mod:`studio.template_fill.deck_slides`). The scope-preview cards, the peer pickers and
that page list are refreshed by app callbacks.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence, Tuple
from uuid import uuid4

import dash_bootstrap_components as dbc
from dash import dcc, html

from studio.compute import DATA_BASIS_PREMIUM, DATA_BASIS_WITH_SURVEY
from studio.page.layout import _filter_grid

# ── the Setup busy overlay ───────────────────────────────────────────────────
#
# Every control on this page re-derives something server-side — the option cascade, the
# peer panel, the scope figures, the deck-section list — and a single change is answered by
# several callbacks at once. The overlay is raised while ANY of them is in flight and drops
# when the last one settles.
#
# Each callback owns its own FLAG, and the overlay watches all of them (see the
# ``:has(.qs-busy-flag.is-busy)`` rule). One shared flag would race: the fastest callback's
# "finished" would lower the overlay while a slower sibling was still running.
#
# `dcc.Loading` was the obvious tool and does not work here: it decides on its own whether a
# subtree is loading, and it consistently missed the FIRST change after a page load — the
# one a user is least sure about. `running` is declared per callback, so it always fires.
BUSY_FLAG_CLASS = "qs-busy-flag"
BUSY_FLAG_ON = f"{BUSY_FLAG_CLASS} is-busy"

# The flag each Setup callback raises. Named for the panel it re-derives, so a new panel
# adds a name here and a `running=` on its own callback — nothing else changes.
BUSY_FORM = "qs-busy-form"              # option cascade + peer panel
BUSY_PREVIEW = "qs-busy-preview"        # the live scope figures
BUSY_SECTIONS = "qs-busy-sections"      # the deck-section list
# Generating has no flag here. It is a background build rather than a callback, so a
# `running=` would come down milliseconds in; and a full-page overlay is the wrong cue for
# something that takes minutes — it would lock the author out of the app while they wait.
# The build reports itself instead, through ``generate_progress`` in the Studio pane.


def form_token() -> dcc.Store:
    """A fresh id for THIS rendering of the form.

    The cascade re-sends only the option lists that changed since its last answer
    (``studio.authoring.setup.changed_options``), which is only sound while the dropdowns on
    screen are the ones it last answered. A re-render rebuilds them from the unfiltered
    lists, so the token changes with the DOM and the next cascade knows to send everything.
    It travels WITH the form rather than as a separate write, so there is no ordering race
    between "the form was rebuilt" and "here is what the form should show".
    """
    return dcc.Store(id="qs-form-token", data=uuid4().hex)


def busy_overlay() -> html.Div:
    """The full-page spinner, plus the per-callback flags that raise it."""
    return html.Div(
        [
            *(html.Div(id=flag, className=BUSY_FLAG_CLASS)
              for flag in (BUSY_FORM, BUSY_PREVIEW, BUSY_SECTIONS)),
            html.Div(html.Div(className="qs-page-spinner"), className="qs-page-loader",
                     id="qs-setup-busy"),
        ],
        className="qs-busy-host",
    )


def _elapsed(seconds: int) -> str:
    """A running time an author can read at a glance — "40s", "3m 12s"."""
    seconds = max(0, int(seconds))
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60:02d}s"


def generate_progress(state: Optional[Mapping[str, Any]]) -> Any:
    """What the build in flight is doing: the phase, the bar, and how long it has run.

    Rendered into a host that is mounted for as long as Studio is (see
    ``studio.authoring.layout.generate_progress_host``), NOT into the Setup form: a build
    takes minutes, and the author is free to walk the last deck's canvas while it runs.

    Nothing at all before the first build and after a finished one — the deck itself is
    the report then, and a "100%" bar left on screen only asks to be clicked again.
    """
    if not state or (state.get("done") and not state.get("error")):
        return ""
    if state.get("error"):
        # A refusal that a re-run could clear reads differently from a configuration
        # mistake, and saying "try again" to the second sends the author round a loop
        # that cannot close (see ``studio.commentary_mode.CommentaryUnavailable``).
        again = " Re-running the same selection may succeed." if state.get("retryable") else ""
        return html.Div(
            [html.I(className="bi bi-exclamation-triangle"),
             html.Span(f"The deck could not be built: {state['error']}{again}")],
            className="qs-gen-progress is-failed",
        )
    percent = int(state.get("percent") or 0)
    return html.Div(
        [
            html.Div(
                [
                    html.Span(state.get("step") or "Working", className="qs-gen-step"),
                    html.Span(str(state.get("scope") or ""), className="qs-gen-scope"),
                    html.Span(_elapsed(int(state.get("elapsed") or 0)),
                              className="qs-gen-elapsed"),
                ],
                className="qs-gen-head",
            ),
            html.Div(html.Div(className="qs-gen-fill", style={"width": f"{percent}%"}),
                     className="qs-gen-track"),
            html.P(state.get("message") or "", className="qs-gen-msg"),
        ],
        className="qs-gen-progress",
    )


def info_tip(tip_id: str, text: str) -> html.Span:
    """A small ⓘ beside a label that says, in plain words, what the control decides.

    Every question on this form is a modelling choice with consequences downstream — which
    books the figures come from, which pages get built, who the deck is written for — and
    none of that is guessable from a three-word label. The explanation is a hover away
    rather than a paragraph on the page, so the form stays a single screen.
    """
    return html.Span(
        [
            html.I(className="bi bi-info-circle", id=tip_id, tabIndex="0"),
            dbc.Tooltip(text, target=tip_id, placement="top", class_name="qs-tip"),
        ],
        className="qs-info",
    )


def _label(text: str, *, tip_id: str = "", tip: str = "",
           className: str = "studio-field-label qs-question") -> html.Div:
    """A field label, asked as a question, with its ⓘ when the answer needs explaining.

    ``qs-question`` drops the all-caps micro-label styling: a shouted question reads as
    an instruction rather than something being asked.
    """
    return html.Div(
        [html.Span(text), info_tip(tip_id, tip) if (tip_id and tip) else None],
        className=className,
    )


def _setup_section(icon: str, title: str, subtitle: str, children: Any, *,
                   span: bool = False, tip_id: str = "", tip: str = "") -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className=f"bi {icon}"),
                            html.Span(title),
                            info_tip(tip_id, tip) if (tip_id and tip) else None,
                        ],
                        className="qs-sec-title",
                    ),
                    html.Div(subtitle, className="qs-sec-sub") if subtitle else None,
                ],
                className="qs-sec-head",
            ),
            html.Div(children, className="qs-sec-body"),
        ],
        className="qs-setup-section" + (" span" if span else ""),
    )


def _radio_field(label: str, cid: str, options: Sequence[Mapping[str, str]], value: str,
                 *, tip_id: str = "", tip: str = "") -> html.Div:
    return html.Div(
        [
            _label(label, tip_id=tip_id, tip=tip),
            dcc.RadioItems(
                id=cid, options=list(options), value=value,
                className="studio-report-radio", inputClassName="studio-report-input",
                labelClassName="studio-report-label",
            ),
        ],
        className="studio-field",
    )


def _setup_options() -> html.Div:
    """The two questions that decide the VOICE of the deck, asked as questions.

    They come first on the form because they are the ones an author answers from the
    brief — for whom, in what voice — before touching a filter. "AUDIENCE / COMMENTARY
    STYLE" named the control rather than the decision, which is exactly the label that
    needs a footnote; the question does not.

    There is no REPORT control: Full QBR is the only deliverable, so offering a
    one-option radio was pure noise. ``generate`` pins ``report="qbr"``.

    There is no SCOPE control either. "How much of the deck should we build?" offered four
    answers to a question authors have page by page, and the panel that listed the deck's
    pages could only read it back. The pages are now the control — see
    :func:`template_sections_panel`.
    """
    return html.Div(
        [
            # The two audiences this deck is actually written for. "Executive /
            # Deal team / Board" described a corporate-finance reader who does not
            # exist here: a QBR is taken by a Marsh regional team to a carrier's
            # own team. Both values are from `report_plan.AUDIENCES`, so the
            # selection policy already understands them.
            _radio_field(
                "Who is this deck for?", "studio-audience", [
                    {"label": "Regional", "value": "marsh_regional"},
                    {"label": "Carrier team", "value": "carrier_leadership"},
                ], "carrier_leadership",
                tip_id="qs-tip-audience",
                tip="The reader the commentary is pitched at. Carrier team is the "
                    "client-facing read — the carrier's own underwriting and "
                    "distribution leads. Regional is the internal Marsh view, which "
                    "may weigh placement and pipeline the carrier would not see.",
            ),
            # Commentary voice — words, not meeting minutes. Passed to the deck when the
            # qualitative prose is written (studio.template_fill.commentary).
            _radio_field(
                "How should the commentary read?", "studio-commentary-style", [
                    {"label": "Concise", "value": "concise"},
                    {"label": "Balanced", "value": "balanced"},
                    {"label": "Detailed", "value": "detailed"},
                ], "balanced",
                tip_id="qs-tip-style",
                tip="How much prose each slide carries. Concise is one or two sentences "
                    "per panel, Detailed explains the drivers behind every movement. "
                    "Every number stays checked against the source facts either way.",
            ),
        ],
        className="qs-options-grid",
    )


# Kept for backward-compat imports; the options now live in ``_setup_options``.
def _audience_length() -> html.Div:  # pragma: no cover - legacy shim
    return _setup_options()


# ── peers ────────────────────────────────────────────────────────────────────
#
# A peer group is a PER-MARKET statement: Zurich is benchmarked against a different set in
# Singapore than in Japan, and the Peers table keys on (carrier, country) for exactly that
# reason. Both halves of this panel therefore separate by market when a run covers several —
# the existing groups are listed under their own country, and the custom picker is one
# dropdown per country rather than one flat set silently applied to every page.

# A benchmark of one or two carriers is not an aggregate — it is close enough to naming
# them, which carrier-facing output may not do. Five is the floor the disclosure rule needs
# and the smallest set an average means anything over.
MIN_CUSTOM_PEERS = 5
MIN_PEERS_MESSAGE = "Please select atleast 5 peers"


def peer_min_note(values: Sequence[str]) -> str:
    """The red under-minimum warning for one market's custom peer set (``""`` when fine)."""
    chosen = [v for v in (values or []) if v]
    return MIN_PEERS_MESSAGE if len(chosen) < MIN_CUSTOM_PEERS else ""


# ``[(country, options, chosen)]`` — what both market pickers below are built from.
PeerGroups = Sequence[Tuple[str, Sequence[Mapping[str, Any]], Sequence[str]]]


def _market_pickers(groups: PeerGroups, kind: str, placeholder, *,
                    minimum: bool = False) -> html.Div:
    """One multi-select per market, headed by its country when there are several.

    ``kind`` is the id ``type`` the callbacks pattern-match on, and ``placeholder`` is
    called with ``(country, per_market)``. With ``minimum`` the picker also carries the
    per-market "at least five" line, which its own MATCH callback rewrites.

    ``country`` is ``""`` when the run pins no country; the ids stay pattern-matched either
    way, so a callback reads one shape whether the run covers one market or five.
    """
    groups = list(groups) or [("", [], [])]
    per_market = len(groups) > 1
    blocks = [
        html.Div(
            [
                html.Div(str(country), className="qs-peer-market-name") if per_market else None,
                dcc.Dropdown(
                    id={"type": kind, "country": str(country)},
                    options=list(options),
                    value=[str(c) for c in (chosen or [])],
                    multi=True,
                    placeholder=placeholder(country, per_market),
                    className="studio-dd sm",
                ),
                html.Div(peer_min_note(chosen),
                         id={"type": "studio-peer-min", "country": str(country)},
                         className="qs-peer-min") if minimum else None,
            ],
            className="qs-peer-market",
        )
        for country, options, chosen in groups
    ]
    return html.Div(blocks, className="qs-peer-markets" + (" per-market" if per_market else ""))


def custom_peer_picker(groups: PeerGroups = ()) -> html.Div:
    """One custom-peer dropdown per market, each with its own minimum.

    With several countries in scope, each gets its own picker under its own heading and its
    own candidate list — a carrier that writes nothing in Japan is not offered as a Japanese
    peer. A single flat dropdown could only pin one set for the whole run, so Japan's page
    ranked against carriers chosen for Singapore.
    """
    return _market_pickers(
        groups, "studio-peer-custom",
        lambda country, per_market: f"Select at least {MIN_CUSTOM_PEERS} peer carriers"
                                    + (f" in {country}" if per_market else ""),
        minimum=True,
    )


def _peer_chips(names: Sequence[str]) -> Optional[html.Div]:
    return (html.Div([html.Span(str(n), className="qs-peer-chip") for n in names],
                     className="qs-peer-chips") if names else None)


def _peer_group_row(country: str, names: Sequence[str]) -> html.Div:
    """One market's peer group: the country, then its own peers."""
    return html.Div(
        [
            html.Div(str(country), className="qs-peer-group-name"),
            _peer_chips(names) or html.Div("No peer group in this market.",
                                           className="qs-peer-note warn"),
        ],
        className="qs-peer-group",
    )


def peer_set_body(names: Sequence[str] = (), note: str = "", *, tone: str = "",
                  groups: Sequence[Tuple[str, Sequence[str]]] = ()) -> html.Div:
    """The peer-set read-out: the peer names as chips, plus one explanatory line.

    Used for BOTH modes — in "existing" it shows the carrier's peer group from the
    Peers table (names only, nothing to pick); in "custom" it shows the note that
    tells the user to pick from the dropdown below.

    ``groups`` is ``[(country, [peer…])]`` and takes over the chip area when a run covers
    several markets. The Peers table holds a group PER COUNTRY, so a multi-country run has
    several of them, and one flat row of chips claimed a single benchmark set that exists in
    no market at all — the author could not see that Singapore and Japan rank against
    different carriers.
    """
    return html.Div(
        [
            html.Div([_peer_group_row(c, n) for c, n in groups], className="qs-peer-groups")
            if groups else _peer_chips(names),
            html.Div(note, className="qs-peer-note" + (f" {tone}" if tone else "")) if note else None,
        ],
        className="qs-peer-body",
    )


def _peers_panel() -> html.Div:
    """Peer-set chooser — existing groups to read, or one custom set per market to pick.

    Existing peers are the carrier's group from the Peers table — names only, so the
    custom pickers are HIDDEN in that mode rather than sitting there full of every carrier
    in the database; with several countries in scope it lists one group per market. Custom
    peers get one picker per market, each scoped to the carriers that write there. Both are
    populated by :func:`studio.authoring.setup.peer_panel_state`.
    """
    return html.Div(
        [
            dcc.RadioItems(
                id="studio-peer-mode",
                options=[
                    {"label": "Existing peers", "value": "existing"},
                    {"label": "Custom peers", "value": "custom"},
                ],
                value="existing",
                className="studio-report-radio",
                inputClassName="studio-report-input",
                labelClassName="studio-report-label",
            ),
            html.Div(
                peer_set_body((), "Select a carrier to see its existing peers."),
                id="studio-peer-msg",
                className="studio-peer-msg",
            ),
            html.Div(
                custom_peer_picker(),
                id="studio-peer-custom-wrap",
                style={"display": "none"},
            ),
        ],
        className="studio-field qs-peer-field",
    )


def _data_source_control(dataset_state: Optional[Mapping[str, Any]]) -> html.Div:
    """DATA SOURCE — governed DB vs the user's own uploaded dataset.

    Mutually exclusive, so segmented pills (not checkboxes). Choosing "My data"
    routes to the Data page; once a dataset is submitted there, a status chip
    names it here and every figure below derives from it."""
    from studio.dataset.repository import get_repository

    state = dataset_state or {}
    source = state.get("source") or "governed"
    record = get_repository().get(state.get("active") or "") if source == "custom" else None
    if source != "custom":
        status = None
    elif record and record.status == "submitted":
        status = html.Span(
            [html.I(className="bi bi-check-circle-fill"),
             f"Using “{record.name}” — {record.n_rows:,} rows. Filters and figures below come from your data."],
            className="qs-source-status ok",
        )
    else:
        status = html.Span(
            [html.I(className="bi bi-arrow-right-circle"),
             "Finish upload, mapping and submit on the Data page to use your data here."],
            className="qs-source-status",
        )
    return html.Div(
        [
            _radio_field(
                "Where should the numbers come from?", "studio-data-source", [
                    {"label": "GPR / Survey", "value": "governed"},
                    {"label": "Custom data", "value": "custom"},
                ], source,
                tip_id="qs-tip-source",
                tip="GPR / Survey is the governed warehouse — the premium book and the "
                    "carrier survey book behind it. Custom data builds the same deck from "
                    "a spreadsheet you upload and map on the Data page.",
            ),
            status,
            _data_basis_control(),
        ],
        className="qs-source-field",
    )


# Which books the deck draws on. "premium_survey" appends a Carrier Survey page to each
# country block and keeps the summary page's overall survey-score tile (see
# studio.template_fill.assemble.plan_subdecks). The VALUES come from studio.compute, which
# is where the choice is read again — the form must not spell them a second time.
DATA_BASIS_DEFAULT = DATA_BASIS_PREMIUM
DATA_BASIS_OPTIONS = (
    {"label": "GPR", "value": DATA_BASIS_PREMIUM},
    # "GPR + Carrier Survey" clipped to "GPR + Carrier Surv" in an equal-width
    # segmented control — the tooltip on the question already names the survey in
    # full, so the chip does not have to.
    {"label": "GPR + Survey", "value": DATA_BASIS_WITH_SURVEY},
)


def _data_basis_control() -> html.Div:
    """Which BOOKS the deck draws on — GPR alone, or GPR plus the carrier survey.

    Segmented pills like the source question above it: the two are the same kind of
    decision (what the deck is built FROM), so they read as one block.
    """
    return html.Div(
        [_radio_field(
            "Which books should the deck draw on?", "studio-data-basis",
            list(DATA_BASIS_OPTIONS), DATA_BASIS_DEFAULT,
            tip_id="qs-tip-basis",
            tip="GPR is the premium book alone — totals, growth, share of wallet and "
                "rank. GPR + Carrier Survey adds a Carrier Survey page to each country "
                "block and the overall survey-score tile, sourced from the survey book.",
        )],
        className="qs-basis-field",
    )


# ── the survey selections ────────────────────────────────────────────────────


def survey_note(text: str, *, tone: str = "") -> html.Div:
    """The one line under the survey carrier — how the identity was resolved, or why not."""
    return html.Div(text, className="qs-peer-note" + (f" {tone}" if tone else "")) if text else html.Div()


def survey_peer_picker(groups: PeerGroups = ()) -> html.Div:
    """One survey-peer dropdown per market.

    The same per-market split the premium picker makes, for the same reason — a survey page
    ranks the subject against the field surveyed IN THAT COUNTRY. Each market's dropdown is
    pre-filled with its own group from the survey Peers table, so the author sees what each
    page will rank against and edits only the market that is wrong. A market with no group
    in the table stays empty, and its page ranks against every carrier surveyed there
    (:mod:`studio.template_fill.survey.facts`). No minimum here: this set is not the author's
    to invent — it is the surveyed field, and a market may hold only a handful of carriers.
    """
    return _market_pickers(
        groups, "studio-survey-peer",
        lambda country, per_market: "Ranked against the surveyed field"
                                    + (f" in {country}" if per_market else ""),
    )


def _survey_panel() -> html.Div:
    """SURVEY — who the subject and its peers are IN THE SURVEY BOOK.

    The survey book keeps its own carrier vocabulary: it records the entity that was
    surveyed ("Zurich Insurance Company Ltd") where the premium book groups ("Zurich"). The
    deck resolves the match itself, but the author is the one who can see both lists, so the
    resolution is shown and can be overridden here — a survey page reporting another
    carrier's scores under this carrier's name is the failure this panel prevents.

    Shown only on the "GPR + Carrier Survey" basis; the whole section is hidden otherwise.
    """
    return html.Div(
        [
            html.Div(
                [
                    _label(
                        "Who is this carrier in the survey book?",
                        tip_id="qs-tip-survey-carrier",
                        tip="The survey book records the entity that was surveyed "
                            "(\"Zurich Insurance Company Ltd\") where the premium book "
                            "groups (\"Zurich\"). The deck matches them itself — this is "
                            "the match it made, and your override if it is wrong.",
                    ),
                    dcc.Dropdown(
                        id="studio-survey-carrier", options=[], value=None,
                        placeholder="Matched from the survey book",
                        className="studio-dd sm",
                    ),
                    html.Div(survey_note(""), id="studio-survey-msg",
                             className="studio-peer-msg"),
                ],
                className="studio-field",
            ),
            html.Div(
                [
                    _label(
                        "Who should the survey pages rank it against?",
                        tip_id="qs-tip-survey-peers",
                        tip="The peer set in the SURVEY book's own names, one per market. "
                            "Pre-filled from the survey Peers table; clear a market and "
                            "that page ranks against every carrier surveyed there.",
                    ),
                    # Pre-filled from the survey Peers table (keyed on Carrier, scoped per
                    # country) as soon as a survey carrier is matched, so the author sees
                    # the group each page will rank against — and can edit it — before
                    # generating. Cleared, that page falls back to the whole surveyed field.
                    html.Div(survey_peer_picker(), id="studio-survey-peer-wrap"),
                    html.Div(survey_note(""), id="studio-survey-peer-msg",
                             className="studio-peer-msg"),
                ],
                className="studio-field",
            ),
        ],
        className="qs-survey-field",
    )


def scope_preview_empty(message: str = "Pick a carrier to preview this scope.") -> html.Div:
    return html.Div(
        [html.I(className="bi bi-binoculars"), html.Span(message)],
        className="qs-preview-empty",
    )


def scope_preview_card(items: Sequence[Mapping[str, Any]]) -> html.Div:
    """Render the live scope-preview KPI tiles (computed by the app callback)."""
    if not items:
        return scope_preview_empty()
    tiles = [
        html.Div(
            [
                html.Div(str(it["label"]).upper(), className="qs-prev-label"),
                html.Div(str(it["value"]), className="qs-prev-value"),
                html.Div(it.get("sub", ""), className="qs-prev-sub") if it.get("sub") else None,
            ],
            className="qs-prev-tile",
        )
        for it in items
    ]
    return html.Div(tiles, className="qs-prev-grid")


def _scope_preview() -> html.Div:
    return html.Div(
        [
            html.Div([html.I(className="bi bi-eye"), "Scope preview"], className="qs-preview-head"),
            html.P("Live headline figures for the current filters.", className="qs-preview-note"),
            # No spinner of its own: the page-level one already covers this panel, and two
            # spinners for one change read as two things happening.
            html.Div(scope_preview_empty(), id="studio-scope-preview"),
        ],
        className="qs-scope-preview",
    )


# Section type → (friendly label, icon, how it's handled) for the slide list.
_SECTION_META: Mapping[str, Tuple[str, str, str]] = {
    "cover": ("Cover", "bi-file-earmark-richtext", ""),
    "summary": ("Executive summary", "bi-grid-1x2", ""),
    "highlights": ("Highlights", "bi-stars", "Commentary auto-written"),
    "trading_summary": ("Trading summary", "bi-chat-square-text", "Commentary auto-written"),
    "gwp_performance": ("GWP performance", "bi-graph-up-arrow", ""),
    "portfolio": ("Portfolio analysis", "bi-pie-chart", ""),
    "feedback": ("Feedback", "bi-clipboard-heart", "Qualitative — filled by hand"),
    "ranking": ("Portfolio & ranking", "bi-trophy", "Chart edited in PowerPoint"),
    "growth": ("Growth quadrant", "bi-bullseye", "Chart edited in PowerPoint"),
    "swot": ("SWOT", "bi-grid-3x3", "Commentary auto-written"),
    "country_divider": ("Country divider", "bi-signpost-split", ""),
    "breakdown": ("Carrier breakdown", "bi-table", "Per-product, per-country"),
    "carrier_title": ("Section title", "bi-bookmark", ""),
    "survey": ("Carrier Survey", "bi-clipboard-data", "Sourced from the survey book"),
    "back_cover": ("Back cover", "bi-file-earmark-check", ""),
    "other": ("Other", "bi-file-earmark", ""),
}


# Assembly axis → (label, icon, how often the sub-deck repeats). A full deck builds all
# of them and merges them, which is why the panel below is per-axis rather than one flat
# page count — the product/country sub-decks repeat per selected value.
_AXIS_META: Mapping[str, Tuple[str, str, str]] = {
    "overall": ("Overall", "bi-grid-1x2", "built once"),
    "product": ("Product", "bi-box-seam", "repeats per product line"),
    "country": ("Country", "bi-globe2", "repeats per country"),
    "survey": ("Carrier Survey", "bi-clipboard-data", "repeats per country"),
    "end": ("Back cover", "bi-file-earmark-check", "closes every deck"),
}


def registered_axes() -> Tuple[str, ...]:
    """The deck axes whose fixed template is registered, in deck order."""
    from studio.template_fill.binding_map import available
    from studio.template_fill.deck_slides import DECK_AXES

    names = set(available())
    return tuple(axis for axis in DECK_AXES if axis in names)


def deck_axes(basis: Optional[str] = None, slides: Optional[Any] = None) -> Tuple[str, ...]:
    """The sub-decks this selection assembles, in deck order.

    Mirrors :func:`studio.template_fill.assemble.deck_shape`, which is where the deck is
    really built. Two things gate an axis, and they are different questions:

    * the author's own page ticks — an axis with every page unticked is not built, which is
      what replaced the old four-way scope choice;
    * the DATA BASIS — the Carrier Survey block is not a page choice but a basis one, so it
      is gated separately and rides along with whichever country blocks are being built.
    """
    from studio.template_fill.deck_slides import DeckSlides

    chosen = slides if slides is not None else DeckSlides.everything()
    axes = chosen.axes(registered_axes())
    with_survey = str(basis or DATA_BASIS_DEFAULT) == DATA_BASIS_WITH_SURVEY
    if with_survey and "country" in axes and "survey" in axes:
        return axes
    return tuple(axis for axis in axes if axis != "survey")


def _slide_meta(entry) -> Tuple[str, str, str]:
    """``(label, icon, note)`` for one page — its section, named for a reader.

    A section the classifier does not know still gets a row: its own name, title-cased. The
    page list is driven by the templates, so it has to survive a template that grows a kind
    of page this table has never seen.
    """
    return _SECTION_META.get(entry.section,
                             (entry.section.replace("_", " ").title(),
                              "bi-file-earmark", ""))


def _slide_preview(entry, url: Optional[str], label: str) -> html.Div:
    """The hover card: the TEMPLATE's own rendering of this page.

    Rendered from the template file, so it shows the layout rather than this carrier's
    numbers — which is the point. The deck the author is deciding about does not exist yet;
    the page they are deciding about does.

    A thumbnail that is not rendered yet (a machine with no PowerPoint, or the first seconds
    after start-up) falls back to naming the page. The row stays usable either way — the
    preview helps the decision, it is not the decision.
    """
    body = (
        html.Img(src=url, className="qs-slide-shot", alt=f"{entry.title or entry.section} slide")
        if url else
        html.Div([html.I(className="bi bi-image"), html.Span("Preview not rendered yet")],
                 className="qs-slide-shot empty")
    )
    return html.Div(
        [body, html.Div(entry.title or label, className="qs-slide-cap")],
        className="qs-slide-pop",
    )


def _slide_row(entry, *, included: bool, url: Optional[str]) -> html.Div:
    """One template page, with the tick that decides whether the deck carries it."""
    label, icon, note = _slide_meta(entry)
    return html.Div(
        [
            dbc.Checkbox(
                id={"type": "qs-slide", "axis": entry.axis, "idx": entry.index},
                value=included,
                class_name="qs-slide-check",
            ),
            html.I(className=f"bi {icon} qs-slide-icon"),
            html.Div(
                [
                    html.Span(label, className="qs-slide-name"),
                    html.Span(note, className="qs-slide-note") if note else None,
                ],
                className="qs-slide-text",
            ),
            html.I(className="bi bi-eye qs-slide-eye",
                   title="Hover to preview this page from the template"),
            _slide_preview(entry, url, label),
        ],
        className="qs-slide-row" + ("" if included else " is-off"),
    )


def _axis_block(axis: str, slides) -> Optional[html.Div]:
    """One sub-template: its pages, each with its own tick, and what the block costs.

    The header counts what is STILL in the deck — pages and the commentary fields a model
    will be asked to write — because that is the number an author is trading against when
    they untick a page. A build's minutes are spent writing commentary, so the count moves
    as they choose rather than after they press Generate.
    """
    from studio.template_fill import slide_previews
    from studio.template_fill.commentary_fields import fields_for_axis
    from studio.template_fill.deck_slides import catalog

    entries = catalog(axis)
    if not entries:
        return None
    label, icon, repeat = _AXIS_META.get(axis, (axis.title(), "bi-file-earmark", ""))
    urls = slide_previews.urls(axis)
    kept = [e for e in entries if slides.includes(axis, e.index)]
    written = fields_for_axis(axis, hidden=slides.hidden(axis))
    return html.Div(
        [
            html.Div(
                [
                    html.I(className=f"bi {icon}"),
                    html.Span(label, className="qs-tsec-axis-name"),
                    html.Span(f"{len(kept)}/{len(entries)} page"
                              + ("s" if len(entries) != 1 else ""),
                              className="qs-tsec-axis-n"),
                    html.Span(f"{written} written",
                              className="qs-tsec-axis-ai",
                              title="Commentary fields a model writes for each block of "
                                    "this axis — the number that sets how long the build "
                                    "takes.") if written else None,
                ],
                className="qs-tsec-axis-head",
            ),
            html.Div(repeat, className="qs-tsec-axis-note") if repeat else None,
            html.Div(
                [_slide_row(e, included=slides.includes(axis, e.index),
                            url=urls[e.index] if e.index < len(urls) else None)
                 for e in entries],
                className="qs-slide-list",
            ),
        ],
        className="qs-tsec-axis" + ("" if kept else " is-dropped"),
    )


def template_sections_panel(basis: Optional[str] = None,
                            slides: Optional[Any] = None) -> html.Div:
    """"What's in your QBR" — every template page, with the tick that includes it.

    This is the deck's shape control, not a read-out of one. Selection is driven by the
    TEMPLATES themselves, so a page added to a template appears here (ticked) with no code
    change, and unticking every page of a sub-template is how a deck is built without it.

    The data basis still gates the Carrier Survey block: it is sourced from a different book
    entirely, so it appears only when the run draws on that book (see :func:`deck_axes`).
    """
    from studio.template_fill.deck_slides import DeckSlides

    chosen = slides if slides is not None else DeckSlides.everything()
    # Every registered axis is LISTED, so an axis can be ticked back on; only the survey
    # block — which is the basis's decision, not the author's — is left out when off.
    blocks = [b for b in (_axis_block(axis, chosen) for axis in _listable(basis))
              if b is not None]
    if not blocks:
        return html.Div(
            [html.I(className="bi bi-exclamation-circle"), " No template registered."],
            className="qs-preview-empty",
        )
    built = deck_axes(basis, chosen)
    pages = sum(len(chosen.kept(axis)) for axis in built)
    return html.Div(
        [
            html.Div(
                [
                    html.Span([html.B(str(pages)), " base pages"], className="qs-tsec-total"),
                    html.Span([html.B(str(len(built))),
                               " sub-deck" + ("s" if len(built) != 1 else "")],
                              className="qs-tsec-total alt"),
                ],
                className="qs-tsec-summary",
            ),
            html.Div("Untick a page to leave it out. Hover one to see it.",
                     className="qs-tsec-hint"),
            html.Div(blocks, className="qs-tsec-axes"),
        ],
        className="qs-tsec",
    )


def _listable(basis: Optional[str]) -> Tuple[str, ...]:
    """Which axes the panel SHOWS — every registered one bar an out-of-basis survey block.

    Different from :func:`deck_axes`, which answers what gets BUILT. An axis the author has
    unticked entirely still has to be on screen, or there would be no way to tick it back.
    """
    axes = registered_axes()
    if str(basis or DATA_BASIS_DEFAULT) == DATA_BASIS_WITH_SURVEY:
        return axes
    return tuple(a for a in axes if a != "survey")


def setup_body(
    cut_groups: Sequence[Mapping[str, Any]],
    *,
    filter_options: Mapping[str, Any] | None = None,
    filter_values: Mapping[str, Any] | None = None,
    dataset: Optional[Mapping[str, Any]] = None,
    slides: Optional[Any] = None,
) -> html.Div:
    # Order follows how a deck is actually briefed: what shape is it and who is it for,
    # then where the numbers come from, then which slice of them, then the benchmarks.
    sections = html.Div(
        [
            _setup_section(
                "bi-sliders", "Audience & voice",
                "Who reads this deck, and how it should read.",
                _setup_options(), span=True,
                tip_id="qs-tip-sec-shape",
                tip="Answer these from the brief. They decide who the commentary is "
                    "pitched at and how much prose each slide carries. WHICH pages the "
                    "deck carries is the list on the right.",
            ),
            _setup_section(
                "bi-database", "Data source",
                "Which data the figures are computed from.",
                _data_source_control(dataset),
                span=True,
                tip_id="qs-tip-sec-source",
                tip="Every figure in the deck is computed from the source chosen here, "
                    "and every cached build re-keys when it changes.",
            ),
            _setup_section(
                "bi-funnel", "Scope & filters",
                "Every list narrows to what the selection above it writes in.",
                # No DATA SCOPE toggle here. It rendered two chips no callback ever read,
                # directly under the basis question — which is the real "GPR or GPR +
                # survey" choice — so the form showed the same decision twice and only one
                # of them worked. (The chips still exist for the standalone demo rail.)
                _filter_grid(filter_options, filter_values),
                span=True,
                tip_id="qs-tip-sec-filters",
                tip="The slice of the book the deck reports on. The lists cascade, so "
                    "each one only offers values that exist under the others. Country "
                    "and Year accept several values; several countries build several "
                    "country blocks — and several peer groups.",
            ),
            _setup_section(
                "bi-people", "Peers",
                "Confidential — aggregate benchmark only.",
                _peers_panel(),
                tip_id="qs-tip-sec-peers",
                tip="Who the carrier is benchmarked against. Existing peers come from "
                    "the governed Peers table, one group per market; custom peers are "
                    "yours to pin, per market, with at least "
                    f"{MIN_CUSTOM_PEERS} carriers each so the benchmark stays an "
                    "aggregate. No peer is ever named in carrier-facing output.",
            ),
            html.Div(
                _setup_section(
                    "bi-clipboard-data", "Survey",
                    "The survey book names carriers its own way — check the match.",
                    _survey_panel(),
                    tip_id="qs-tip-sec-survey",
                    tip="The survey book is a separate flow with its own carrier names "
                        "and its own peer groups. Shown only when the deck draws on it, "
                        "so a survey page never reports another carrier's scores.",
                ),
                id="studio-survey-section",
                style={"display": "none"},          # shown on the GPR + Carrier Survey basis
            ),
        ],
        className="qs-setup-sections",
    )
    aside = html.Div(
        [
            _scope_preview(),
            html.Button(
                [html.I(className="bi bi-stars"), "Generate deck"],
                id="studio-generate",
                className="qs-generate-btn",
            ),
            # Why a Generate click was refused (no money measure, dataset not
            # submitted). Written by the generate callback.
            html.Div(id="studio-setup-msg", className="qs-setup-msg"),
            # The deck's page list lives in the aside so the main form stays a single
            # screen. It is a CONTROL, not a summary: each page carries the tick that
            # decides whether the deck includes it, and the deck's shape is read back off
            # those ticks (``studio.template_fill.deck_slides``).
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="bi bi-collection"), "What's in your QBR",
                            info_tip(
                                "qs-tip-pages",
                                "Every page of every sub-template, with the tick that "
                                "decides whether your deck carries it. Untick a page and "
                                "it is not built, not filled and not written — a "
                                "sub-template with nothing ticked is left out of the deck "
                                "entirely. Hover a page to see it as the template draws "
                                "it; the preview is the template's own example, not this "
                                "carrier's numbers.",
                            ),
                        ],
                        className="qs-aside-card-head"),
                    html.Div(template_sections_panel(basis=DATA_BASIS_DEFAULT, slides=slides),
                             id="studio-template-sections"),
                ],
                className="qs-aside-card",
            ),
        ],
        className="qs-setup-aside",
    )
    form = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("QBR Studio", className="qs-setup-eyebrow"),
                            html.Div([html.I(className="bi bi-magic"), "QBR Creator"],
                                     className="qs-setup-title"),
                        ],
                        className="qs-setup-head-text",
                    ),
                    html.Span(
                        [html.I(className="bi bi-shield-check"), "Governed data"],
                        className="qs-govern-chip",
                        title="Every figure traces to the governed dataset; commentary is verified against it.",
                    ),
                ],
                className="qs-setup-head",
            ),
            html.Div([sections, aside], className="qs-setup-layout"),
        ],
        className="qs-setup-card",
    )
    return html.Div([busy_overlay(), form_token(), form], className="qs-setup-wrap")
