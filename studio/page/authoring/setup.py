"""Setup mode — the real build form, wired to the DB.

``setup_body`` composes the scope/filters, report, template, audience, sections,
peers and AI-assist sections plus the live scope-preview aside and Generate button.
The scope-preview cards and template-sections panel are refreshed by app callbacks.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence, Tuple

import dash_bootstrap_components as dbc
from dash import dcc, html

from studio.compute import DATA_BASIS_PREMIUM, DATA_BASIS_WITH_SURVEY
from studio.page.layout import _filter_grid, _scope_toggle

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


def _setup_section(icon: str, title: str, subtitle: str, children: Any, *, span: bool = False) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div([html.I(className=f"bi {icon}"), title], className="qs-sec-title"),
                    html.Div(subtitle, className="qs-sec-sub") if subtitle else None,
                ],
                className="qs-sec-head",
            ),
            html.Div(children, className="qs-sec-body"),
        ],
        className="qs-setup-section" + (" span" if span else ""),
    )


def _radio_field(label: str, cid: str, options: Sequence[Mapping[str, str]], value: str) -> html.Div:
    return html.Div(
        [
            html.Div(label, className="studio-field-label"),
            dcc.RadioItems(
                id=cid, options=list(options), value=value,
                className="studio-report-radio", inputClassName="studio-report-input",
                labelClassName="studio-report-label",
            ),
        ],
        className="studio-field",
    )


def _setup_options() -> html.Div:
    """The compact 'options bar' — assembly scope, audience and commentary voice
    as segmented pills in one dense auto-fitting row (keeps the form short).

    There is no REPORT control: Full QBR is the only deliverable, so offering a
    one-option radio was pure noise. ``generate`` pins ``report="qbr"``.
    """
    return html.Div(
        [
            _template_control(),
            _radio_field("AUDIENCE", "studio-audience", [
                {"label": "Executive", "value": "executive"},
                {"label": "Deal team", "value": "deal_team"},
                {"label": "Board", "value": "board"},
            ], "executive"),
            # Commentary voice — words, not meeting minutes. Passed to the deck when the
            # qualitative prose is written (studio.template_fill.commentary).
            _radio_field("COMMENTARY STYLE", "studio-commentary-style", [
                {"label": "Concise", "value": "concise"},
                {"label": "Balanced", "value": "balanced"},
                {"label": "Detailed", "value": "detailed"},
            ], "balanced"),
        ],
        className="qs-options-grid",
    )


# Kept for backward-compat imports; the options now live in ``_setup_options``.
def _audience_length() -> html.Div:  # pragma: no cover - legacy shim
    return _setup_options()


def _ai_control() -> html.Div:
    """AI assist — ON by default; the narrative is the point of the deck.

    It stays a checkbox so a user can still fall back to the purely deterministic
    deck, but nobody should have to opt IN to the commentary."""
    return html.Div(
        [
            dbc.Checkbox(
                id="studio-ai-toggle",
                label="AI-assisted narrative & layout",
                value=True,
                class_name="studio-check qs-ai-check",
            ),
            html.Div(
                "Sharper commentary and slide layout — every number is checked against the "
                "source facts, and it falls back to the deterministic deck when AI is unavailable.",
                className="qs-ai-note",
            ),
        ],
        className="qs-ai-field",
    )


# ── peers ────────────────────────────────────────────────────────────────────


def peer_set_body(names: Sequence[str], note: str = "", *, tone: str = "") -> html.Div:
    """The peer-set read-out: the peer names as chips, plus one explanatory line.

    Used for BOTH modes — in "existing" it shows the carrier's peer group from the
    Peers table (names only, nothing to pick); in "custom" it shows the note that
    tells the user to pick from the dropdown below."""
    chips = [html.Span(str(n), className="qs-peer-chip") for n in names]
    return html.Div(
        [
            html.Div(chips, className="qs-peer-chips") if chips else None,
            html.Div(note, className="qs-peer-note" + (f" {tone}" if tone else "")) if note else None,
        ],
        className="qs-peer-body",
    )


def _peers_panel() -> html.Div:
    """Peer-set chooser.

    Existing peers are the carrier's group from the Peers table — names only, so the
    custom dropdown is HIDDEN in that mode rather than sitting there full of every
    carrier in the database. Custom peers pick carriers from the current scope.
    Both lists are populated by ``studio.authoring.setup.peer_panel``.
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
                dcc.Dropdown(
                    id="studio-peer-custom",
                    options=[],
                    value=[],
                    multi=True,
                    placeholder="Select peer carriers",
                    className="studio-dd sm",
                ),
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
            _radio_field("DATA SOURCE", "studio-data-source", [
                {"label": "Existing database", "value": "governed"},
                {"label": "My uploaded data", "value": "custom"},
            ], source),
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
    {"label": "Premium only", "value": DATA_BASIS_PREMIUM},
    {"label": "Premium + survey", "value": DATA_BASIS_WITH_SURVEY},
)


def _data_basis_control() -> html.Div:
    """DATA BASIS — the premium book alone, or the premium book plus broker survey.

    Segmented pills like DATA SOURCE above it: the two are the same kind of decision
    (what the deck is built FROM), so they read as one block.
    """
    return html.Div(
        [_radio_field("DATA BASIS", "studio-data-basis",
                      list(DATA_BASIS_OPTIONS), DATA_BASIS_DEFAULT)],
        className="qs-basis-field",
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


# Assembly-scope choices (Setup "Scope" dropdown). Value = the axis set to assemble;
# "all" is the full deck (overall + product + country). Only axes with a registered
# template are offered.
_SCOPE_LABELS = {
    "all": "All — overall + product + country",
    "overall": "Overall only",
    "product": "Product pages",
    "country": "Country pages",
}


def _scope_options() -> list:
    """The scope choices, gated to the axes whose fixed template is registered."""
    from studio.template_fill.binding_map import available

    axes = set(available())
    opts = [{"label": _SCOPE_LABELS["all"], "value": "all"}]
    for axis in ("overall", "product", "country"):
        if axis in axes:
            opts.append({"label": _SCOPE_LABELS[axis], "value": axis})
    return opts


def _template_control() -> html.Div:
    """Assembly scope — which fixed sub-decks to build and merge.

    Templates are a fixed, author-made set (``overall`` / ``product`` / ``country``), split
    by axis and merged per selection. This dropdown picks how much of the deck to assemble:
    everything, or just the overall / product / country pages.
    """
    options = _scope_options()
    return html.Div(
        [
            html.Div("SCOPE", className="studio-field-label"),
            dcc.Dropdown(
                id="studio-template",
                options=options,
                value="all",
                clearable=False,
                className="studio-dd",
            ),
        ],
        className="studio-field",
    )


# Section type → (friendly label, icon, how it's handled) for the template preview.
_SECTION_META: Mapping[str, Tuple[str, str, str]] = {
    "summary": ("Executive summary", "bi-grid-1x2", ""),
    "highlights": ("Highlights", "bi-stars", "Commentary auto-written"),
    "trading_summary": ("Trading summary", "bi-chat-square-text", "Commentary auto-written"),
    "portfolio": ("Portfolio analysis", "bi-pie-chart", ""),
    "feedback": ("Feedback", "bi-clipboard-heart", "Qualitative — filled by hand"),
    "ranking": ("Portfolio & ranking", "bi-trophy", "Chart edited in PowerPoint"),
    "growth": ("Growth quadrant", "bi-bullseye", "Chart edited in PowerPoint"),
    "swot": ("SWOT", "bi-grid-3x3", "Commentary auto-written"),
    "country_divider": ("Country divider", "bi-signpost-split", ""),
    "breakdown": ("Carrier breakdown", "bi-table", "Per-product, per-country"),
    "carrier_title": ("Section title", "bi-bookmark", ""),
    "other": ("Other", "bi-file-earmark", ""),
}


# Assembly axis → (label, icon, how often the sub-deck repeats). "all" builds all
# three and merges them, which is why the panel below is per-axis rather than one
# flat page count — the product/country sub-decks repeat per selected value.
_AXIS_META: Mapping[str, Tuple[str, str, str]] = {
    "overall": ("Overall", "bi-grid-1x2", "built once"),
    "product": ("Product", "bi-box-seam", "repeats per product line"),
    "country": ("Country", "bi-globe2", "repeats per country"),
}

# Scope choice → the axes it assembles, in deck order.
_SCOPE_AXES: Mapping[str, Tuple[str, ...]] = {
    "all": ("overall", "product", "country"),
    "overall": ("overall",),
    "product": ("product",),
    "country": ("country",),
}


def scope_axes(scope: Optional[str]) -> Tuple[str, ...]:
    """The registered axes a scope choice assembles (unregistered ones dropped)."""
    from studio.template_fill.binding_map import available

    registered = set(available())
    wanted = _SCOPE_AXES.get(scope or "all", _SCOPE_AXES["all"])
    return tuple(axis for axis in wanted if axis in registered)


def _section_counts(axis: str) -> Optional[List[Tuple[str, int]]]:
    """``[(section key, page count)]`` in reading order for an axis's template."""
    from studio.template_fill.binding_map import template_path
    from studio.template_fill.registry import derive_manifest
    from studio.template_fill.sections import classify_sections

    try:
        template, _ = derive_manifest(template_path(axis))
        secs = classify_sections(template)
    except Exception:  # noqa: BLE001 — a missing/odd template must not break Setup
        return None
    counts: dict = {}
    for idx in sorted(secs):
        key = secs[idx].value
        counts[key] = counts.get(key, 0) + 1
    return list(counts.items())


def _section_chips(counts: Sequence[Tuple[str, int]]) -> html.Div:
    chips = []
    for key, n in counts:
        label, icon, _ = _SECTION_META.get(key, (key.title(), "bi-file-earmark", ""))
        chips.append(
            html.Span(
                [
                    html.I(className=f"bi {icon}"),
                    html.Span(label, className="qs-tchip-label"),
                    html.Span(str(n), className="qs-tchip-n"),
                ],
                className="qs-tchip",
            )
        )
    return html.Div(chips, className="qs-tchip-row")


def _axis_block(axis: str, counts: Sequence[Tuple[str, int]]) -> html.Div:
    label, icon, repeat = _AXIS_META.get(axis, (axis.title(), "bi-file-earmark", ""))
    pages = sum(n for _, n in counts)
    return html.Div(
        [
            html.Div(
                [
                    html.I(className=f"bi {icon}"),
                    html.Span(label, className="qs-tsec-axis-name"),
                    html.Span(f"{pages} pages", className="qs-tsec-axis-n"),
                ],
                className="qs-tsec-axis-head",
            ),
            html.Div(repeat, className="qs-tsec-axis-note") if repeat else None,
            _section_chips(counts),
        ],
        className="qs-tsec-axis",
    )


def template_sections_panel(scope: Optional[str] = "all") -> html.Div:
    """The sections the CURRENT SCOPE will produce, one block per assembled axis.

    Selection is driven by the templates themselves, not a static list. "All" builds
    the overall, product and country sub-decks and merges them, so all three are
    listed — previewing only the overall template (the old behaviour) made switching
    Scope back to "All" look like nothing had happened.
    """
    axes = scope_axes(scope)
    blocks, base_pages = [], 0
    for axis in axes:
        counts = _section_counts(axis)
        if not counts:
            continue
        base_pages += sum(n for _, n in counts)
        blocks.append(_axis_block(axis, counts))
    if not blocks:
        return html.Div(
            [html.I(className="bi bi-exclamation-circle"), " No template registered for this scope."],
            className="qs-preview-empty",
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Span([html.B(str(base_pages)), " base pages"], className="qs-tsec-total"),
                    html.Span([html.B(str(len(blocks))), " sub-deck" + ("s" if len(blocks) > 1 else "")],
                              className="qs-tsec-total alt"),
                ],
                className="qs-tsec-summary",
            ),
            html.Div(blocks, className="qs-tsec-axes"),
        ],
        className="qs-tsec",
    )


def setup_body(
    cut_groups: Sequence[Mapping[str, Any]],
    *,
    filter_options: Mapping[str, Any] | None = None,
    filter_values: Mapping[str, Any] | None = None,
    dataset: Optional[Mapping[str, Any]] = None,
) -> html.Div:
    sections = html.Div(
        [
            _setup_section(
                "bi-database", "Data source",
                "Build from the governed database or your own dataset, and choose which "
                "books the deck draws on.",
                _data_source_control(dataset),
                span=True,
            ),
            _setup_section(
                "bi-funnel", "Scope & filters",
                "Every list narrows to what the selection above it writes in.",
                html.Div([_scope_toggle(), _filter_grid(filter_options, filter_values)], className="qs-sec-stack"),
                span=True,
            ),
            _setup_section(
                "bi-sliders", "Scope, audience & voice",
                "How much of the deck to assemble, and who it is written for.",
                _setup_options(), span=True,
            ),
            _setup_section(
                "bi-people", "Peers",
                "Confidential — aggregate benchmark only.",
                _peers_panel(),
            ),
            _setup_section(
                "bi-stars", "AI assist",
                "On by default; faithfulness-verified.",
                _ai_control(),
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
            # Deck sections live in the aside so the main form stays a single screen.
            html.Div(
                [
                    html.Div([html.I(className="bi bi-collection"), "Deck sections"],
                             className="qs-aside-card-head"),
                    html.Div(template_sections_panel("all"), id="studio-template-sections"),
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
                            html.Div([html.I(className="bi bi-database"), "Deck setup"], className="qs-setup-title"),
                            html.P(
                                "Choose the client, period and scope. Figures are computed "
                                "deterministically from the governed dataset — no LLM, no invented numbers.",
                                className="qs-setup-sub",
                            ),
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
    return html.Div([busy_overlay(), form], className="qs-setup-wrap")
