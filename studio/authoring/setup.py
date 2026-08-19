"""Setup callbacks: turn the form into a selection, then snapshot a deck.

``generate`` reads every Setup control, builds a selection, snapshots the
deterministic deck into a fresh document, and jumps to the canvas.
``scope_preview`` shows cheap headline figures as the filters change.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Sequence

from dash import ALL, MATCH, Input, Output, State, no_update

from logger import get_logger
from studio.compute import FILTER_COLUMN
from studio.data import cascade_options, peer_members
from studio.page import authoring as A
from studio.page import document as D
from studio.template_fill import registry

from studio.authoring.config import BLANK, BREAKDOWNS, engine
from studio.authoring.generate import (
    _generated_assembled_tdoc,
    _generated_deck,
    _generated_tdoc,
)

log = get_logger(__name__)


def _scope_template_path(scope):
    """A concrete template ``.pptx`` for the tdoc fallback, derived from the scope choice.

    The assembled preview drives the canvas; this path only feeds the single-template
    fallback (``new_template_doc``), so a specific axis maps to its template and "all"
    maps to the overall template.
    """
    from studio.template_fill.binding_map import available, template_path

    axes = set(available())
    axis = scope if scope in {"overall", "product", "country"} else "overall"
    if axis not in axes:
        axis = "overall" if "overall" in axes else (sorted(axes)[0] if axes else None)
    try:
        return template_path(axis) if axis else registry.active_template_path()
    except Exception:  # noqa: BLE001 — fall back to whatever the registry considers active
        return registry.active_template_path()


def generation_block_reason(dataset_store, record) -> str:
    """Why Generate must not run for this data source, or "" when it may.

    A deck is premium-derived end to end (totals, YoY, rank, share of wallet),
    so custom data without a money measure can't produce one. This also stops
    the silent fallback where "My uploaded data" is selected but nothing has
    been submitted — that used to build a governed-DB deck instead.
    """
    from studio.dataset.model import premium_mapped
    from studio.dataset.repository import get_repository

    if (dataset_store or {}).get("source") != "custom":
        return ""
    if record is not None:
        return "" if premium_mapped(record) else (
            "This dataset has no Premium column and no primary measure. "
            "Map one on the Data page, then submit it."
        )
    active = (dataset_store or {}).get("active")
    saved = get_repository().get(active or "")
    if saved is None:
        return "Upload a dataset on the Data page, or switch back to the existing database."
    if not premium_mapped(saved):
        return (
            f"“{saved.name}” has no Premium column and no primary measure. "
            "Map one on the Data page, then submit it."
        )
    return f"“{saved.name}” isn't in use yet — open the Data page and choose “Use this data for the deck”."


# Filters that must NOT narrow the peer candidate list: the carrier is the subject
# (never its own peer) and the year would drop a peer just for having a quiet year.
_PEER_SCOPE_SKIP = ("carrier", "year")


def carriers_in_scope(filters, record) -> list:
    """`[{label, value}]` for every carrier that writes under the current filters.

    This is what makes the peer choices *correct*: country, region, product line and
    the rest all narrow the list, and the selected carrier is removed from it.
    """
    where = {
        FILTER_COLUMN[c]: v
        for c, v in (filters or {}).items()
        if c not in _PEER_SCOPE_SKIP and c in FILTER_COLUMN
    }
    opts = _cascade(record, ("Carrier_Group",), where).get("Carrier_Group", [])
    subject = str((filters or {}).get("carrier") or "").lower()
    return [o for o in opts if str(o.get("value", "")).lower() != subject]


# ── the three things a filter change re-derives ──────────────────────────────

# The GPR columns the Setup form filters on, in form order.
_FILTER_COLUMNS = tuple(FILTER_COLUMN.values())


def _cascade(record, columns, selected) -> dict:
    """``{column: options}`` from whichever source is in use (dataset wins over the DB)."""
    from studio.dataset.source import dataset_cascade_options

    if record is not None:
        return dataset_cascade_options(record.dataset_id, columns, selected)
    return cascade_options("gpr", columns, selected)


def option_digest(options) -> str:
    """A short, stable digest of one dropdown's option list."""
    import hashlib

    payload = repr([(o.get("label"), o.get("value")) for o in (options or [])])
    return hashlib.blake2s(payload.encode("utf-8"), digest_size=8).hexdigest()


def changed_options(options: dict, signature, token: str) -> tuple:
    """``(per-column value-or-no_update, new signature)`` — only what the browser lacks.

    A cascade recomputes all ten lists, but a filter change usually moves two or three of
    them; the rest are byte-identical to what the dropdowns already show. Re-sending those
    costs payload on the way down and a re-render on arrival, and both grow with the
    vocabulary — on a warehouse with thousands of carriers the unchanged carrier list was the
    bulk of every response. Comparing digests keeps the callback's answer to what changed.

    ``token`` identifies the rendering of the form these dropdowns belong to
    (:func:`studio.page.authoring.setup.form_token`). A re-render rebuilds them from the
    UNFILTERED lists, so a signature from a previous rendering describes something that is no
    longer on screen and every list is sent afresh.
    """
    signature = signature or {}
    previous = signature.get("digests", {}) if signature.get("token") == token else {}
    digests = {col: option_digest(opts) for col, opts in options.items()}
    fresh = {col: (options[col] if digests[col] != previous.get(col) else no_update)
             for col in options}
    return fresh, {"token": token, "digests": digests}


def cascade_filter_options(selected: dict, record) -> dict:
    """``{form filter id: options}`` — every dropdown narrowed to what the others allow.

    Pick a region and only its countries/carriers remain; pick a carrier and only the
    products, cover lines, industries and segments it writes in remain; and so on. One
    cached pass over the filter cube answers all ten columns
    (:func:`studio.data.cascade_options`).
    """
    where = {FILTER_COLUMN[c]: v for c, v in (selected or {}).items() if c in FILTER_COLUMN}
    by_column = _cascade(record, _FILTER_COLUMNS, where)
    return {fid: by_column[col] for fid, col in FILTER_COLUMN.items() if col in by_column}


# ── the peer group, market by market ─────────────────────────────────────────
#
# The Peers table keys a peer group on (carrier, COUNTRY): Zurich is benchmarked against a
# different set in Singapore than in Japan, which is the whole point of a country-scoped
# group. A run over several markets therefore has several groups, and showing their union as
# one row of chips claimed a benchmark set that exists in no market at all. Each is shown
# under its own country instead — the same read-out the deck's per-country pages will use.


def peer_groups(flow: str, carrier: str, selected: dict, record) -> list:
    """``[(country, [peer…])]`` — the peer group for each selected market, in form order.

    Every group is narrowed to the carriers that actually write IN THAT COUNTRY under the
    REST of the selection (region, product line, segment…), so a peer listed for a market it
    has since left is not offered as a benchmark there. One cascade per country, answered
    from the cached filter cube.
    """
    out = []
    for country in _as_tuple((selected or {}).get("country")):
        writing = {str(o.get("value", "")).lower()
                   for o in carriers_in_scope({**(selected or {}), "country": country}, record)}
        members = peer_members(flow, carrier, country=str(country))
        out.append((str(country), [m for m in members if str(m).lower() in writing]))
    return out


def custom_peer_groups(selected: dict, record, chosen: dict | None = None) -> list:
    """``[(country, options, kept)]`` — one custom-peer picker per selected market.

    Each market offers only the carriers that write THERE under the rest of the selection,
    so a carrier absent from Japan is never offered as a Japanese peer. A selection already
    made for a market survives a filter change as long as those names still qualify.

    With no country pinned there is one picker keyed ``""`` — the run has one market
    (all of them), so it has one peer set.
    """
    chosen = chosen or {}
    countries = _as_tuple((selected or {}).get("country"))
    if not countries:
        return [("", carriers_in_scope(selected, record), _kept(chosen.get(""), ()))]
    out = []
    for country in countries:
        opts = carriers_in_scope({**(selected or {}), "country": country}, record)
        offered = {str(o.get("value", "")) for o in opts}
        out.append((country, opts, _kept(chosen.get(country), offered)))
    return out


def _kept(chosen, offered) -> list:
    """The peers still worth keeping: the ones this market still offers (``()`` = all)."""
    names = [str(p) for p in (chosen or []) if p]
    return [p for p in names if p in offered] if offered else names


def peer_panel_state(selected: dict, mode, record, options: dict, chosen: dict | None = None):
    """``(custom-peer picker, wrapper style, existing-peer read-out)`` for the peer panel.

    Existing mode shows ONLY the carrier's peer group from the Peers table, as names —
    there is nothing to choose, so the custom picker is hidden; with several countries in
    scope it shows one group per country (see :func:`peer_groups`). Custom mode shows one
    picker PER MARKET, each holding the carriers that actually write there under the
    current filters — never the whole database and never the subject itself. The Peers
    table is governed, so a custom dataset has no existing group and is told to pin its own.
    """
    carrier = (selected or {}).get("carrier")
    country = (selected or {}).get("country")
    opts = carriers_in_scope(selected, record)
    shown = {str(o.get("value", "")).lower() for o in opts}
    hidden = {"display": "none"}
    groups = custom_peer_groups(selected, record, chosen)
    picker = A.custom_peer_picker(groups)

    if mode == "custom":
        note = (f"Pick at least {A.MIN_CUSTOM_PEERS} carriers per market — the deck shows "
                f"the aggregate only, never a name." if len(groups) > 1 else
                f"Pick at least {A.MIN_CUSTOM_PEERS} carriers to benchmark against — the "
                f"deck shows the aggregate only.")
        return picker, {}, A.peer_set_body((), note)
    if not carrier:
        return picker, hidden, A.peer_set_body((), "Select a carrier to see its existing peers.")
    if record is not None:
        return picker, hidden, A.peer_set_body(
            (), "Your data has no governed peer group — switch to Custom peers to benchmark.",
            tone="warn",
        )
    countries = _as_tuple(country)
    if len(countries) > 1:
        existing = peer_groups("gpr", carrier, selected, record)
        if not any(members for _, members in existing):
            return picker, hidden, A.peer_set_body(
                (), f"No peer group exists for {carrier} in these markets — switch to "
                    f"Custom peers.", tone="warn")
        return picker, hidden, A.peer_set_body(
            groups=existing,
            note="One peer group per market, from the Peers table — each country page "
                 "benchmarks against its own.")

    members = peer_members("gpr", carrier, country=_hashable(country))
    if not members:
        return picker, hidden, A.peer_set_body(
            (), f"No peer group exists for {carrier} — switch to Custom peers.", tone="warn",
        )
    # The Peers table is scope-free, so a listed peer may write nothing in the
    # chosen country/product scope. Show who counts, and name who drops out.
    in_scope = [m for m in members if str(m).lower() in shown]
    absent = [m for m in members if str(m).lower() not in shown]
    if not in_scope:
        return picker, hidden, A.peer_set_body(
            members, "None of these peers write in the current scope — widen the "
                     "filters or switch to Custom peers.", tone="warn",
        )
    note = f"{len(in_scope)} peer{'s' if len(in_scope) > 1 else ''} from the Peers table."
    if absent:
        note += f" Not writing in this scope: {', '.join(absent)}."
    return picker, hidden, A.peer_set_body(in_scope, note)


# ── the survey selections ────────────────────────────────────────────────────
#
# The survey book keeps its own carrier vocabulary, so the deck resolves the premium
# subject into it (``studio.template_fill.survey.identity``). The author is the one who can
# see both lists, so Setup shows the match it found and lets them override it — and pins
# survey peers in the same vocabulary, because a peer set pinned on the premium side names
# carrier groups this book has never heard of.

_SURVEY_HIDDEN = {"display": "none"}


def _survey_result():
    """A bare result the survey lookups can run against — they need only the engine.

    Studio's own engine, explicitly (the one every other panel on this form queries), and
    always the GOVERNED one: the survey book is not something a user uploads, so an
    uploaded dataset is answered before we get here.
    """
    from studio.compute import OverallResult
    from studio.data import get_engine

    return OverallResult(subject=None, flow="survey", engine=get_engine())


def _on_survey_basis(basis) -> bool:
    from studio.compute import DATA_BASIS_WITH_SURVEY

    return str(basis or "") == DATA_BASIS_WITH_SURVEY


def changed_ids() -> set:
    """Which controls fired this callback — a filter's ``col`` for the pattern-matched ones.

    The survey panel needs this because "the author chose this carrier" and "the form
    matched it last time round" arrive as the SAME value in a ``State``. Only the trigger
    tells them apart, and without it a match made for one carrier outlived the carrier: pick
    Zurich, then pick AIG, and the survey panel still said Zurich.
    """
    try:
        from dash import ctx

        triggered = ctx.triggered_prop_ids or {}
    except Exception:  # noqa: BLE001 — called outside a callback (tests, first render)
        return set()
    out = set()
    for ident in triggered.values():
        if isinstance(ident, dict):
            if ident.get("type") == "studio-filter":
                out.add(str(ident.get("col")))
        else:
            out.add(str(ident))
    return out


def survey_panel_state(selected: dict, basis: str, pinned_carrier, record, *,
                       keep_pin: bool = True):
    """``(section style, carrier options, carrier value, note)`` for SURVEY CARRIER.

    The carrier list is the survey book's own, narrowed to the countries in scope. The
    value is what the author pinned, else the match the deck would make on its own — shown
    rather than hidden, so a wrong match is visible BEFORE the deck is built.

    ``keep_pin=False`` throws the pin away and matches afresh. The caller passes it when the
    SUBJECT carrier is what changed: a pin is an override of the match for one carrier, and
    it means nothing once the deck is about a different one.
    """
    from studio.template_fill.survey import identity

    if not _on_survey_basis(basis):
        return _SURVEY_HIDDEN, [], None, A.survey_note("")
    if record is not None:
        return {}, [], None, A.survey_note(
            "The survey book is governed data — an uploaded dataset has no survey pages.",
            tone="warn")

    carrier = (selected or {}).get("carrier")
    countries = (selected or {}).get("country")
    result = _survey_result()
    names = _safe_survey(identity.carrier_options, result, _as_tuple(countries))
    options = [{"label": n, "value": n} for n in names]
    if not names:
        return {}, [], None, A.survey_note(
            "No survey book for this scope — the survey pages will be skipped.", tone="warn")

    value = pinned_carrier if (keep_pin and pinned_carrier in names) else None
    if value is None and carrier:
        from dataclasses import replace

        value = _safe_survey(identity.resolve_carrier,
                             replace(result, subject=str(carrier)), _as_tuple(countries))
    return {}, options, value, _survey_note_for(carrier, value)


def survey_peer_group(result, carrier: str, country: str) -> list:
    """One market's survey peer group, in the SURVEY book's own names (``""`` = every market).

    ``Peers.Carrier`` scoped to ``Country`` — the survey flow's own ``peer_columns``
    (``core/registry/flows.yaml``). NOT ``Carrier_Group``: that is the premium key, and it
    groups entities this book records separately, so looking a group up here returns either
    nothing or another carrier's peers. Names the book does not survey in this market are
    dropped, since they cannot be ranked there.
    """
    from studio.data import peer_members
    from studio.template_fill.survey import identity

    surveyed = set(_safe_survey(identity.carrier_options, result, (country,)) or ())
    members = _safe_peers(peer_members, "survey", str(carrier), country=(str(country),)) or []
    return [str(m) for m in members if str(m) in surveyed and str(m) != carrier]


def survey_peer_state(selected: dict, basis: str, survey_carrier, chosen, record, *,
                      keep_choice: bool = True):
    """``([(country, options, peers)], read-out)`` for SURVEY PEERS — from the Peers table.

    The same promise the premium peer panel makes: the author sees the group the deck WILL
    rank against before generating it, and can edit it. Showing it is the fix for a panel
    that started empty and therefore said nothing about which peers the survey page used.

    Each market gets its OWN group, pre-filled, offering only the carriers the book surveys
    there. One flat dropdown could pin a single set for the whole run, so it had to be left
    empty when several countries were in scope — pre-filling the union would have ranked
    Japan's page against Singapore's peers. Per market there is a right answer everywhere,
    so every market shows one. Clearing a market falls back to that market's own group
    (:func:`studio.template_fill.survey.facts._peer_carriers`).

    ``chosen`` is ``{country: [peer…]}`` from the form. ``keep_choice=False`` discards it —
    the caller passes it when the carrier changed, because a peer group belongs to the
    carrier it was chosen for.
    """
    from studio.template_fill.survey import identity

    if not _on_survey_basis(basis) or record is not None or not survey_carrier:
        return [], A.peer_set_body()
    result = _survey_result()
    countries = _as_tuple((selected or {}).get("country")) or ("",)
    chosen = chosen if keep_choice else {}

    groups, filled = [], []
    for country in countries:
        names = _safe_survey(identity.carrier_options, result, (country,) if country else ())
        options = [{"label": n, "value": n} for n in (names or ()) if n != survey_carrier]
        offered = {o["value"] for o in options}
        kept = _kept((chosen or {}).get(country), offered)
        group = survey_peer_group(result, str(survey_carrier), country)
        groups.append((country, options, kept or group))
        filled.append((country, group))

    if not any(peers for _, _o, peers in groups):
        where = "these markets" if len(countries) > 1 else "this scope"
        return groups, A.peer_set_body(
            (), f"No survey peer group for {survey_carrier} in {where} — pick peers, or "
                f"each page ranks it against every carrier surveyed there.", tone="warn")
    if len(groups) > 1:
        return groups, A.peer_set_body(
            groups=[(c, peers) for c, _o, peers in groups],
            note="One peer group per market, from the Peers table — each survey page "
                 "benchmarks against its own. Edit a market to override just that page.")

    _country, _options, peers = groups[0]
    source = "the Peers table" if list(peers) == list(filled[0][1]) else "your selection"
    return groups, A.peer_set_body(peers, _peer_count(len(peers), source))


# ── reading the per-market pickers back off the form ─────────────────────────


def peers_by_country(ids, values) -> dict:
    """``{country: [peer…]}`` from the pattern-matched pickers (empty markets dropped)."""
    out = {}
    for ident, value in zip(ids or [], values or []):
        chosen = [str(p) for p in (value or []) if p]
        if chosen:
            out[str((ident or {}).get("country") or "")] = chosen
    return out


def picker_markets(ids) -> list:
    """The markets the form is currently showing a picker for, in form order."""
    return [str((ident or {}).get("country") or "") for ident in (ids or [])]


def flatten_peers(by_country: dict) -> list:
    """Every pinned peer across the markets, de-duplicated, in form order.

    The overall block reports on the whole selection, so it benchmarks against the whole
    pinned field; the per-country blocks narrow back to their own market.
    """
    out = []
    for chosen in (by_country or {}).values():
        out.extend(p for p in chosen if p not in out)
    return out


def short_markets(by_country: dict, *, countries: Sequence[str] = ()) -> list:
    """The markets whose custom peer set is under the minimum — ``[]`` when all are fine.

    A market with NO picker answer at all counts as short: an empty selection is what an
    author sees before they choose, and it must not build a deck with no benchmark.
    """
    keys = [str(c) for c in countries] or list((by_country or {}).keys()) or [""]
    return [c for c in keys
            if len([p for p in ((by_country or {}).get(c) or []) if p]) < A.MIN_CUSTOM_PEERS]


def _short_peer_warning(short: Sequence[str]):
    """The red "pick more peers" line Generate refuses with, naming the thin markets."""
    from dash import html

    named = [c for c in short if c]
    where = f" ({', '.join(named)})" if len(named) > 1 else (f" for {named[0]}" if named else "")
    return html.Span(f"{A.MIN_PEERS_MESSAGE}{where}.", className="qs-map-hint warn")


def _peer_count(count: int, source: str) -> str:
    return f"{count} peer{'s' if count != 1 else ''} from {source}."


def _safe_peers(fn, *args, **kwargs):
    """A peer lookup must never take the Setup form down with it."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — a form that still renders beats a blank page
        log.warning("survey peers: lookup failed: %s", exc)
        return []


def _survey_note_for(carrier, matched):
    """How the survey identity was resolved, in one line the author can act on."""
    if not carrier:
        return A.survey_note("Select a carrier to match it against the survey book.")
    if matched is None:
        return A.survey_note(
            f"{carrier} could not be matched in the survey book — pick the surveyed "
            f"carrier, or the survey pages will be skipped.", tone="warn")
    if str(matched).strip().lower() == str(carrier).strip().lower():
        return A.survey_note(f"Surveyed as {matched}.")
    return A.survey_note(f"{carrier} is surveyed as {matched} — change it if that is wrong.")


def _safe_survey(fn, *args):
    """A survey lookup must never take the Setup form down with it."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 — a form that still renders beats a blank page
        log.warning("survey panel: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return () if fn.__name__ == "carrier_options" else None


def _as_tuple(value):
    if isinstance(value, (list, tuple, set)):
        return tuple(str(v) for v in value if v not in BLANK)
    return (str(value),) if value not in BLANK else ()


def _hashable(value):
    """A selection in a form a cache key accepts (Dash hands multi-selects over as lists)."""
    return tuple(value) if isinstance(value, list) else value


def scope_preview_body(selected: dict, record):
    """The live headline tiles for the current filters (empty until a carrier is picked)."""
    if not (selected or {}).get("carrier"):
        return A.scope_preview_empty()
    key = tuple(sorted((c, _hashable(v)) for c, v in selected.items()))
    try:
        items = _scope_figures(key, record.dataset_id if record else None)
    except Exception as exc:  # noqa: BLE001 — preview is best-effort, never blocks Setup
        log.warning("scope preview failed: %s", exc)
        return A.scope_preview_empty("Preview unavailable for this scope.")
    return A.scope_preview_card(items) if items else A.scope_preview_empty()


@lru_cache(maxsize=256)
def _scope_figures(key: tuple, dataset_id):
    """The preview's four figures, cached per scope.

    A total and a market rank that are pure functions of the selection, so revisiting a
    scope — which happens constantly while a user tries filter combinations — costs nothing
    the second time. Both come from the pre-aggregated rollup (:mod:`studio.scope`), so the
    first visit to a scope does not scan the fact table either.
    """
    from studio.compute import _CARRIER_COL, _resolve_filters
    from studio.dataset.source import dataset_engine
    from studio.page.format import money
    from studio.scope import scope_figures

    filters = {c: (list(v) if isinstance(v, tuple) else v) for c, v in key}
    eng = dataset_engine(dataset_id) if dataset_id else engine
    resolved = _resolve_filters(filters)
    subject = resolved.get(_CARRIER_COL)
    figures = scope_figures(resolved, flow="gpr", engine=eng, dataset_id=dataset_id)

    country = filters.get("country")
    n_countries = len(country) if isinstance(country, (list, tuple)) else (1 if country else "All")
    year_val = filters.get("year")
    if isinstance(year_val, (list, tuple, set)):
        years = sorted(str(y) for y in year_val if str(y).strip())
        year_disp = ", ".join(years) if years else "All"
    else:
        year_disp = str(year_val) if year_val else "All"
    return (
        {"label": "Total GWP", "value": money(figures.total), "sub": str(subject)},
        {"label": "Market rank", "value": figures.rank_rendered},
        {"label": "Countries", "value": str(n_countries)},
        {"label": "Year", "value": year_disp},
    )


def _busy(flag: str):
    """``running=`` for a Setup callback: raise ``flag`` while it works, drop it after.

    The full-page overlay watches every flag at once, so a change answered by several
    callbacks stays covered until the last of them finishes
    (:func:`studio.page.authoring.setup.busy_overlay`).
    """
    return [(Output(flag, "className"), A.BUSY_FLAG_ON, A.BUSY_FLAG_CLASS)]


def _generation_blocked(dataset_store, record):
    """The block reason as a rendered warning, or None when generation may run."""
    from dash import html

    reason = generation_block_reason(dataset_store, record)
    return html.Span(reason, className="qs-map-hint warn") if reason else None


def _register_busy_overlay(app):
    """Follow every Setup busy flag at once and drive the full-page spinner from them.

    Clientside because the only job is holding the overlay up for a minimum time
    (``assets/studio_busy.js``); a round trip to the server to decide whether to show a
    "we are talking to the server" spinner would be self-defeating.
    """
    from dash import ClientsideFunction

    app.clientside_callback(
        ClientsideFunction(namespace="qsBusy", function_name="track"),
        Output("qs-setup-busy", "data-busy"),
        Input(A.BUSY_FORM, "className"),
        Input(A.BUSY_PREVIEW, "className"),
        Input(A.BUSY_SECTIONS, "className"),
    )


def register_setup(app):
    """Wire the Generate + scope-preview callbacks onto ``app``."""
    _register_busy_overlay(app)

    @app.callback(
        Output("qs-selection", "data"),
        Output("qs-doc", "data", allow_duplicate=True),
        Output("qs-tdoc", "data", allow_duplicate=True),
        Output("qs-view", "data", allow_duplicate=True),
        Output("qs-generating", "data"),
        Output("studio-setup-msg", "children"),
        Input("studio-generate", "n_clicks"),
        State({"type": "studio-filter", "col": ALL}, "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State({"type": "studio-cut", "name": ALL}, "value"),
        State({"type": "studio-cut", "name": ALL}, "id"),
        State("studio-peer-mode", "value"),
        State({"type": "studio-peer-custom", "country": ALL}, "value"),
        State({"type": "studio-peer-custom", "country": ALL}, "id"),
        State("studio-audience", "value"),
        State("studio-commentary-style", "value"),
        State("studio-template", "value"),
        State("studio-data-basis", "value"),
        State("studio-survey-carrier", "value"),
        State({"type": "studio-survey-peer", "country": ALL}, "value"),
        State({"type": "studio-survey-peer", "country": ALL}, "id"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def generate(n, fvals, fids, cut_vals, cut_ids, peer_mode, peer_vals, peer_ids,
                 audience, style, template_scope, data_basis,
                 survey_carrier, survey_peer_vals, survey_peer_ids, dataset_store):
        if not n:
            return no_update, no_update, no_update, no_update, no_update, no_update
        from studio.dataset.source import dataset_in_use

        filters = {i["col"]: v for i, v in zip(fids or [], fvals or []) if v not in BLANK}
        cuts = [i["name"] for i, v in zip(cut_ids or [], cut_vals or []) if v]
        # Custom peers apply directly: the authoring Setup has no ANALYSES
        # checkboxes, so gating on a "peer_average" cut left the panel dead —
        # peer benchmarks in the filled template use this pinned set (or the
        # Peers table when the mode is "existing").
        by_country = peers_by_country(peer_ids, peer_vals) if peer_mode == "custom" else {}
        # Every market ON THE FORM is checked, not just the ones with an answer: a run over
        # two countries with peers pinned in one of them is exactly the case a check over
        # the answers alone would wave through.
        short = short_markets(by_country, countries=picker_markets(peer_ids)) \
            if peer_mode == "custom" else []
        if short:
            return (no_update, no_update, no_update, no_update, no_update,
                    _short_peer_warning(short))
        peers = flatten_peers(by_country) or None
        survey_by_country = peers_by_country(survey_peer_ids, survey_peer_vals)
        # A submitted custom dataset pins its id into the selection: every cached
        # build (deck / tdoc / assembled) then keys and computes on THAT data.
        record = dataset_in_use(dataset_store)
        blocked = _generation_blocked(dataset_store, record)
        if blocked:
            return no_update, no_update, no_update, no_update, no_update, blocked
        selection = {
            # Full QBR is the only deliverable, so the Setup form no longer asks.
            "report": "qbr",
            "filters": filters,
            # The breakdown control was removed from Setup; the deck keeps the deterministic
            # default breakdowns so the on-screen DeckSpec still has its sections.
            "breakdowns": BREAKDOWNS,
            "cuts": cuts,
            "peers": peers,
            # …and the same pin market by market. The overall block benchmarks against the
            # union above; each country block narrows to its own market's set
            # (``studio.template_fill.bindings.scope_to_country``), because a peer group
            # chosen for Singapore says nothing about Japan.
            "peers_by_country": by_country or None,
            "audience": audience or "executive",
            "meeting_length": "standard",
            "style": style or "balanced",
            # AI assist is no longer a Setup control — the narrative IS the deck, and the
            # commentary is faithfulness-verified against the same facts either way.
            "ai": True,
            "template_scope": template_scope or "all",
            "template_path": _scope_template_path(template_scope),
            # Which books the deck draws on ("premium" | "premium_survey"). Carried into
            # every cached build so a change re-keys them (see A.DATA_BASIS_OPTIONS).
            "data_basis": data_basis or A.DATA_BASIS_DEFAULT,
            # Who the subject and its peers are IN THE SURVEY BOOK. Both are the author's
            # override of the match the deck would make itself; absent, it resolves them
            # (studio.template_fill.survey.identity).
            "survey_carrier": survey_carrier or None,
            "survey_peers": flatten_peers(survey_by_country) or None,
            "survey_peers_by_country": survey_by_country or None,
            "dataset_id": record.dataset_id if record else None,
            # …and its revision, so re-shaping or re-mapping the SAME dataset re-keys
            # every cached build. Without it, fixing a mapping and generating again
            # re-served the deck built from the mapping that was wrong.
            "dataset_rev": (dataset_store or {}).get("rev") if record else None,
        }
        deck = _generated_deck(selection)
        doc = D.new_document(deck) if deck else None
        # Preview the ASSEMBLED deck (overall + per product + per country); fall back to the
        # single-template doc only if assembly can't run.
        tdoc = _generated_assembled_tdoc(selection) or _generated_tdoc(selection)
        return selection, doc, tdoc, {"mode": "canvas", "idx": 0, "tab": "setup"}, n, ""

    # A filter change used to fire THREE callbacks that each re-queried the warehouse. They
    # are now split by COST, not by panel:
    #
    #   * the form itself — options + peer panel — is answered from the cached filter cube,
    #     so it is a couple of milliseconds and needs no spinner;
    #   * the scope preview runs two real aggregates (a total and a market rank), which no
    #     cube can shortcut, so it stays a SEPARATE callback. The browser runs the two
    #     concurrently, and the slow one can never hold up the fast one — merging them made
    #     every dropdown wait on the rank query.
    @app.callback(
        Output({"type": "studio-filter", "col": ALL}, "options"),
        Output("studio-peer-custom-wrap", "children"),
        Output("studio-peer-custom-wrap", "style"),
        Output("studio-peer-msg", "children"),
        Output("qs-filter-sig", "data"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        Input("studio-peer-mode", "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State({"type": "studio-peer-custom", "country": ALL}, "value"),
        State({"type": "studio-peer-custom", "country": ALL}, "id"),
        State("qs-dataset", "data"),
        State("qs-filter-sig", "data"),
        State("qs-form-token", "data"),
        running=_busy(A.BUSY_FORM),
    )
    def refresh_form(values, mode, ids, peer_vals, peer_ids, dataset_store, signature, token):
        """Re-derive every dropdown's options and the peer panel — one cube pass.

        Only the FILTER lists that changed are sent back; the rest answer ``no_update``,
        which leaves the dropdown showing what it already has (:func:`changed_options`).

        The custom-peer pickers are rebuilt wholesale instead, because the SET of them is
        itself derived: add a country and a picker appears for it. What the author already
        chose per market is read back in and re-seeded, so a rebuild is not a reset.
        """
        from studio.dataset.source import dataset_in_use

        ids = ids or []
        selected = {i["col"]: v for i, v in zip(ids, values or []) if v not in BLANK}
        record = dataset_in_use(dataset_store)
        options = cascade_filter_options(selected, record)
        chosen = peers_by_country(peer_ids, peer_vals)
        picker, peer_style, peer_msg = peer_panel_state(selected, mode, record, options, chosen)
        fresh, signature = changed_options(options, signature, token)
        return ([fresh.get(i["col"], no_update) for i in ids],
                picker, peer_style, peer_msg, signature)

    # The "at least five" check is its own tiny per-market callback: it is a function of ONE
    # picker's value, so MATCH answers only the market the author just touched — folding it
    # into refresh_form would rebuild every picker (and close the menu) on each pick.
    @app.callback(
        Output({"type": "studio-peer-min", "country": MATCH}, "children"),
        Input({"type": "studio-peer-custom", "country": MATCH}, "value"),
    )
    def check_peer_minimum(chosen):
        """The red "Please select atleast 5 peers" line under one market's picker."""
        return A.peer_min_note(chosen)

    # The survey panel is its own callback, not part of refresh_form: it queries a DIFFERENT
    # book, and only on the survey basis, so folding it in would make every premium-only
    # filter change pay for a lookup it never uses.
    @app.callback(
        Output("studio-survey-section", "style"),
        Output("studio-survey-carrier", "options"),
        Output("studio-survey-carrier", "value"),
        Output("studio-survey-msg", "children"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        Input("studio-data-basis", "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State("studio-survey-carrier", "value"),
        State("qs-dataset", "data"),
        running=_busy(A.BUSY_FORM),
    )
    def refresh_survey(values, basis, ids, pinned, dataset_store):
        """Match the selected carrier into the survey book.

        A pin made for the PREVIOUS carrier is dropped: it was an override of that carrier's
        match, and keeping it left the survey panel naming a carrier the deck is no longer
        about.
        """
        from studio.dataset.source import dataset_in_use

        selected = {i["col"]: v for i, v in zip(ids or [], values or []) if v not in BLANK}
        return survey_panel_state(selected, basis, pinned, dataset_in_use(dataset_store),
                                  keep_pin="carrier" not in changed_ids())

    # Peers are their own callback so the SURVEY CARRIER above can drive them: a component
    # cannot be both an Input and an Output of one callback, and the peer group is a
    # function of the carrier — change who the subject is and the group has to follow.
    @app.callback(
        Output("studio-survey-peer-wrap", "children"),
        Output("studio-survey-peer-msg", "children"),
        Input("studio-survey-carrier", "value"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        Input("studio-data-basis", "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State({"type": "studio-survey-peer", "country": ALL}, "value"),
        State({"type": "studio-survey-peer", "country": ALL}, "id"),
        State("qs-dataset", "data"),
        running=_busy(A.BUSY_FORM),
    )
    def refresh_survey_peers(survey_carrier, values, basis, ids, peer_vals, peer_ids,
                             dataset_store):
        """Read each market's survey peer group off the Peers table, keyed on the carrier.

        A selection made for the previous carrier is discarded for the same reason the
        carrier's own pin is: a peer group belongs to the carrier it was chosen for.
        """
        from studio.dataset.source import dataset_in_use

        selected = {i["col"]: v for i, v in zip(ids or [], values or []) if v not in BLANK}
        changed = changed_ids()
        groups, note = survey_peer_state(
            selected, basis, survey_carrier, peers_by_country(peer_ids, peer_vals),
            dataset_in_use(dataset_store),
            keep_choice=not ({"carrier", "studio-survey-carrier"} & changed))
        return A.survey_peer_picker(groups), note

    @app.callback(
        Output("studio-scope-preview", "children"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State("qs-dataset", "data"),
        running=_busy(A.BUSY_PREVIEW),
    )
    def scope_preview(values, ids, dataset_store):
        """The live headline figures — the one panel that genuinely queries on each change."""
        from studio.dataset.source import dataset_in_use

        selected = {i["col"]: v for i, v in zip(ids or [], values or []) if v not in BLANK}
        return scope_preview_body(selected, dataset_in_use(dataset_store))
