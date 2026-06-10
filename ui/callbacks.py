import logging
import uuid
from pathlib import Path
from datetime import datetime
from io import BytesIO

import pandas as pd
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command
from typing_extensions import Any, Optional


from dash import (
    Input,
    Output,
    State,
    callback,
    callback_context,
    dcc,
    html,
    no_update,
    ctx,
    clientside_callback,
    ALL,
    MATCH,
    NoUpdate,
)


from dash import dash_table
import dash_bootstrap_components as dbc
from dash.development.base_component import Component

from ui.components.chatbot import (
    chatbot_page,
    clarify_card,
    clarify_questions_of,
    followup_suggestions,
    ai_message,
    chart_block,
    welcome_hero,
    pitch_builder_drawer,
    boardroom_mode_cue,
    custom_peers_modal,
    custom_peers_cue,
)

# Editable Boardroom builder package. Importing `boardroom_callbacks` registers all
# edit-mode callbacks (side effect). `render_boardroom_document` replaces the old
# read-only card; `build_boardroom_document` turns a digest into an editable doc.
from ui.boardroom.figures import figures_for_specs as boardroom_figures_for_specs
from ui.boardroom.render import render_document as render_boardroom_document
from ui.boardroom.builder import build_document_from_digest as build_boardroom_document
from ui.boardroom.editor import all_modals as boardroom_modals
from ui.boardroom import callbacks as boardroom_callbacks  # noqa: F401  (registers callbacks)

# Decision Board package. Importing `decision_callbacks` registers its CRUD +
# view-router callbacks (side effect). Separate from chat/agent memory by design.
from ui.decisions.render import decision_board_view, decision_modals
from ui.decisions import callbacks as decision_callbacks  # noqa: F401  (registers callbacks)
from ui.components.navbar import build_navbar
from ui.components.sidebar import (
    login_screen,
    app_sidebar,
    conversation_list_children,
)
from core.store.users import get_or_create_user
from core.store.conversations import (
    list_conversations,
    save_conversation,
    load_conversation,
    delete_conversation,
)
from core.memory.episodic import episodic_store
from core.memory import semantic
from core.memory.suggestions import (
    generate_starter_questions,
    invalidate as invalidate_suggestions,
)
from core.backend import (
    LangGraph,
    AgentState,
    PitchAgentState,
    GeneralFunctions,
    Initialization,
    PitchBuilderWorkflow,
)
from ui.chart_functions import generate_chart
from core.agents.common.chart_spec import normalize_chart_spec
from sqlalchemy import inspect, text
from document_builder.report_generator import (
    get_theme,
    frame_theme_questions,
    build_pitch_report_docx,
)

from logger import get_logger

from config.callbacks_config import (
    PITCH_COLUMN_MAP,
    PREFFERED_PITCH_CARRIER,
    PREFFERED_PITCH_COUNTRY,
)
from config.db_config import engine
from ui.helper import (
    distinct_pitch_countries,
    distinct_pitch_carriers,
    distinct_pitch_years,
    default_option_value,
    pitch_cache,
    pitch_cache_key,
    latest_option_value,
    has_pitch_filters,
    distinct_peer_countries,
    distinct_peer_carriers,
)

from document_builder.models import ReportConfig
from ui.jobs import Job, start_job, get_job, cancel_job, clear_job

#  ── Logger ────────────────────────────────────────────────────────────────────────────────────────

logger = get_logger(__name__)

# ── STATE OBJECT INITIALIZATION ──────────────────────────────────────────────────────────────────────

langgraph = LangGraph()
pitch_workflow = PitchBuilderWorkflow()


# ── JS TO AUTO SCROLL CHAT  ───────────────────────────────────────────────────────────────────────────

clientside_callback(
    """
    function(children, editMode) {
        // While the user is editing a Boardroom card, the chat repaints on every
        // tweak — don't yank the viewport to the bottom mid-edit.
        if (editMode) {
            return window.dash_clientside.no_update;
        }
        const el = document.getElementById('chat-box');
        if (el) {
            setTimeout(() => {el.scrollTop = el.scrollHeight;}, 30);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("chat-box", "data-scroll-anchor"),
    Input("chat-box", "children"),
    State("boardroom-edit-mode", "data"),
    prevent_initial_call=True,
)

# ── TOGGLE THINKING BAR + SEND/STOP BUTTON  ─────────────────────────────────────────────────────────────
# Instant, clientside: while a turn is streaming we reveal the status bar and the
# stop button, and hide the send button. No server round-trip so it feels snappy.
clientside_callback(
    """
    function(thinking) {
        const on = !!thinking;
        return [
            {display: on ? 'flex' : 'none'},
            {display: on ? 'none' : 'inline-flex'},
            {display: on ? 'inline-flex' : 'none'}
        ];
    }
    """,
    Output("thinking-bar", "style"),
    Output("send-btn", "style"),
    Output("stop-btn", "style"),
    Input("is-thinking", "data"),
)

# ── CHART ↔ DATA VIEW TOGGLE  ───────────────────────────────────────────────────────────────────────
# Instant, clientside: flip a chart between its figure and the underlying rows.
# Pairs each switch with its own chart via MATCH on the shared `idx`.
clientside_callback(
    """
    function(chartClicks, dataClicks) {
        const ctx = window.dash_clientside.callback_context;
        const trig = ctx.triggered.length ? ctx.triggered[0].prop_id : '';
        const showData = trig.indexOf('chart-toggle-data') !== -1;
        return [
            {display: showData ? 'none' : 'block'},
            {display: showData ? 'block' : 'none'},
            showData ? 'chart-view-btn' : 'chart-view-btn active',
            showData ? 'chart-view-btn active' : 'chart-view-btn',
        ];
    }
    """,
    Output({"type": "chart-fig", "idx": MATCH}, "style"),
    Output({"type": "chart-table", "idx": MATCH}, "style"),
    Output({"type": "chart-toggle-chart", "idx": MATCH}, "className"),
    Output({"type": "chart-toggle-data", "idx": MATCH}, "className"),
    Input({"type": "chart-toggle-chart", "idx": MATCH}, "n_clicks"),
    Input({"type": "chart-toggle-data", "idx": MATCH}, "n_clicks"),
    prevent_initial_call=True,
)

# ── PITCH BUILDER CALLBACKS  ───────────────────────────────────────────────────────────────────────────

# 1. -------------------------- TOOGLE PITCH BUILDER BTN ---------------------------------------


@callback(
    Output("pitch-builder-open", "data"),
    Input("menu-pitch-builder", "n_clicks", allow_optional=True),
    Input("pitch-close-btn", "n_clicks"),
    State("pitch-builder-open", "data"),
    prevent_initital_call=True,
)
def toggle_pitch_builder(
    open_clicks: int, close_clicks: int, is_open: bool
) -> bool | NoUpdate:
    """Open the Pitch Builder drawer from the composer "+" menu; close from its X."""

    triggered_id = ctx.triggered_id
    if triggered_id == "menu-pitch-builder" and open_clicks:
        return True
    if triggered_id == "pitch-close-btn" and close_clicks:
        return False
    return no_update


# 2. -------------------------- OPENS PITCH BUILDER SIDEBAR ---------------------------------------


@callback(
    Output("pitch-builder-drawer", "className"),
    Output("pitch-builder-drawer", "style"),
    Output("pitch-builder-backdrop", "style"),
    Output("pitch-builder-panel", "style"),
    Input("pitch-builder-open", "data"),
)
def set_pitch_builder_drawer_class(
    is_open: bool,
) -> tuple[str, dict[str, str], dict[str, str], dict[str, str]]:
    """Function that opens the Pitch Builder Sidebar on btn click"""

    class_name = "pitch-builder-drawer"
    drawer_style = {
        "position": "fixed",
        "inset": 0,
        "zIndex": 2000,
        "pointerEvents": "auto" if is_open else "none",
        "visibility": "visible" if is_open else "hidden",
    }
    backdrop_style = {
        "position": "absolute",
        "inset": 0,
        "background": "rgba(11, 19, 32, 0.32)",
        "opacity": 1 if is_open else 0,
        "transition": "opacitiy 260ms cubic-bezier(.4, .0, .2, 1)",
    }
    panel_style = {
        "position": "absolute",
        "top": 0,
        "right": 0,
        "width": "min(480px, 96vw)",
        "height": "100vh",
        "overflowY": "auto",
        "background": "linear-gradient(180deg, #ffffff 0%, #f6f8fc 100%)",
        "borderLeft": "1px solid rgba(12, 25, 58, 0.10)",
        "boxShadow": "-24px 0 60px rgba(10, 22, 54, 0.16)",
        "transform": "translate(0)" if is_open else "translateX(100%)",
        "transition": "transform 320ms cubic-bezier(.16, .84, .44, 1)",
    }

    if is_open:
        return (
            f"{class_name} pitch-builder-drawer-open",
            drawer_style,
            backdrop_style,
            panel_style,
        )

    return class_name, drawer_style, backdrop_style, panel_style


@callback(
    Output("boardroom-mode-store", "data"),
    Input("menu-boardroom-mode", "n_clicks", allow_optional=True),
    Input("boardroom-mode-clear", "n_clicks", allow_optional=True),
    State("boardroom-mode-store", "data"),
    prevent_initial_call=True,
)
def toggle_boardroom_mode(
    menu_clicks: int, clear_clicks: int, is_on: bool
) -> bool | NoUpdate:
    """Flip Boardroom Mode on/off from the composer menu (or the cue's clear button).

    When on, `launch_new_job` passes `boardroom_mode=True` into the graph and the
    terminal `boardroom_node` produces the dashboard digest for the next answer.
    """
    triggered_id = ctx.triggered_id
    if triggered_id == "boardroom-mode-clear" and clear_clicks:
        return False
    if triggered_id == "menu-boardroom-mode" and menu_clicks:
        return not bool(is_on)
    return no_update


@callback(
    Output("boardroom-mode-cue", "children"),
    Input("boardroom-mode-store", "data"),
)
def render_boardroom_mode_cue(is_on: bool):
    """Show a composer pill while Boardroom Mode is armed for the next answer."""
    return boardroom_mode_cue(bool(is_on))


# Multi-page boardroom card: a clientside slider pager. The slider value (the page
# index) shows that page and hides the rest. Pure clientside so paging never
# round-trips to the server or re-runs the graph. State carries the page ids so the
# function knows how many pages to toggle for this card (MATCH on idx).
clientside_callback(
    """
    function(value, pageIds) {
        const n = (pageIds || []).length;
        let active = (value === null || value === undefined) ? 0 : value;
        if (active < 0) active = 0;
        if (active > n - 1) active = n - 1;
        const styles = [];
        for (let i = 0; i < n; i++) {
            styles.push(i === active ? {} : {display: 'none'});
        }
        return styles;
    }
    """,
    Output({"type": "bm-page", "idx": MATCH, "page": ALL}, "style"),
    Input({"type": "bm-slider", "idx": MATCH}, "value"),
    State({"type": "bm-page", "idx": MATCH, "page": ALL}, "id"),
)


# ════════════════════════════ CUSTOM PEERS ════════════════════════════════════
# A session-scoped, hand-picked peer set. Opened from the composer "+" menu; the
# selection is stored inside chat-store ("custom_peers") so it persists per
# conversation via save_conversation/open_conversation. A composer cue shows it is
# active. The graph (see core.graph) injects it into peer SQL and runs a HITL gate
# when the user later asks about a different carrier.


@callback(
    Output("custom-peers-open", "data"),
    Input("menu-custom-peers", "n_clicks", allow_optional=True),
    Input("custom-peers-edit", "n_clicks", allow_optional=True),
    Input("custom-peers-cancel", "n_clicks", allow_optional=True),
    Input("custom-peers-apply", "n_clicks", allow_optional=True),
    State("custom-peers-open", "data"),
    prevent_initial_call=True,
)
def toggle_custom_peers_modal(
    open_clicks: int, edit_clicks: int, cancel_clicks: int, apply_clicks: int, is_open: bool
) -> bool | NoUpdate:
    """Open the Custom Peers dialog from the "+" menu or the cue; close on cancel/apply.

    Guard every branch on a *truthy* n_clicks: the `allow_optional` inputs fire a
    spurious callback as they mount, with `triggered_id` resolving to one of these
    ids but n_clicks still 0/None. Without the click guard that spurious fire would
    open the dialog on page load.
    """
    triggered = ctx.triggered_id
    if triggered == "menu-custom-peers" and open_clicks:
        return True
    if triggered == "custom-peers-edit" and edit_clicks:
        return True
    if triggered == "custom-peers-cancel" and cancel_clicks:
        return False
    if triggered == "custom-peers-apply" and apply_clicks:
        return False
    return no_update


@callback(
    Output("custom-peers-modal", "is_open"),
    Input("custom-peers-open", "data"),
    prevent_initial_call=True,
)
def render_custom_peers_modal_open(is_open: bool) -> bool:
    # prevent_initial_call so the dialog never writes `is_open` on first mount —
    # it relies on the component's own `is_open=False` default and only reacts to
    # genuine open/close events from the store.
    return bool(is_open)


@callback(
    Output("custom-peers-flow", "value"),
    Input("custom-peers-open", "data"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def seed_custom_peers_flow(is_open: bool, chat_history: dict[str, Any]) -> str | NoUpdate:
    """On open, default the data-source radio to the pinned set's flow if editing."""
    if not is_open:
        return no_update
    stored = (chat_history or {}).get("custom_peers") or {}
    return stored.get("flow") or "gpr"


def _peer_option_value(options: list[dict[str, str]], preferred: str | None) -> str | None:
    values = [opt["value"] for opt in options]
    if preferred:
        for value in values:
            if str(value).strip().lower() == str(preferred).strip().lower():
                return value
    return values[0] if values else None


@callback(
    Output("custom-peers-country", "options"),
    Output("custom-peers-country", "value"),
    Input("custom-peers-open", "data"),
    Input("custom-peers-flow", "value"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def load_custom_peer_countries(
    is_open: bool, flow: str, chat_history: dict[str, Any]
) -> tuple[Any, Any]:
    """Country options for the chosen data source; prefill the pinned country if editing."""
    if not is_open:
        return no_update, no_update
    options = distinct_peer_countries(flow)
    stored = (chat_history or {}).get("custom_peers") or {}
    preferred = stored.get("country") if stored.get("flow") == flow else None
    return options, _peer_option_value(options, preferred or PREFFERED_PITCH_COUNTRY)


@callback(
    Output("custom-peers-carrier", "options"),
    Output("custom-peers-carrier", "value"),
    Input("custom-peers-open", "data"),
    Input("custom-peers-flow", "value"),
    Input("custom-peers-country", "value"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def load_custom_peer_carriers(
    is_open: bool, flow: str, country: str | None, chat_history: dict[str, Any]
) -> tuple[Any, Any]:
    """Subject-carrier options for the country; prefill the pinned carrier if editing."""
    if not is_open or not country:
        return no_update, no_update
    options = distinct_peer_carriers(flow, country)
    stored = (chat_history or {}).get("custom_peers") or {}
    preferred = (
        stored.get("carrier")
        if stored.get("flow") == flow and stored.get("country") == country
        else None
    )
    return options, _peer_option_value(options, preferred or PREFFERED_PITCH_CARRIER)


@callback(
    Output("custom-peers-list", "options"),
    Output("custom-peers-list", "value"),
    Input("custom-peers-open", "data"),
    Input("custom-peers-flow", "value"),
    Input("custom-peers-country", "value"),
    Input("custom-peers-carrier", "value"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def load_custom_peer_list(
    is_open: bool,
    flow: str,
    country: str | None,
    carrier: str | None,
    chat_history: dict[str, Any],
) -> tuple[Any, Any]:
    """Every other carrier/group in the country as selectable peers (subject excluded)."""
    if not is_open or not country:
        return no_update, no_update
    all_carriers = distinct_peer_carriers(flow, country)
    subject = (carrier or "").strip().lower()
    options = [opt for opt in all_carriers if opt["value"].strip().lower() != subject]

    # On a fresh open while editing, restore the pinned peers; otherwise reset so a
    # carrier/country/flow change does not carry stale peers across.
    stored = (chat_history or {}).get("custom_peers") or {}
    is_open_event = ctx.triggered_id == "custom-peers-open"
    if (
        is_open_event
        and stored.get("flow") == flow
        and stored.get("country") == country
        and stored.get("carrier") == carrier
    ):
        valid = {opt["value"] for opt in options}
        return options, [p for p in (stored.get("peers") or []) if p in valid]
    return options, []


@callback(
    Output("custom-peers-apply", "disabled"),
    Output("custom-peers-count", "children"),
    Input("custom-peers-carrier", "value"),
    Input("custom-peers-list", "value"),
)
def toggle_custom_peers_apply(carrier: str | None, peers: list[str] | None) -> tuple[bool, str]:
    """Enable Apply only once a subject carrier and at least one peer are chosen."""
    peers = peers or []
    count = f" ({len(peers)} selected)" if peers else ""
    return (not (carrier and peers)), count


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("trigger-resume", "data", allow_duplicate=True),
    Output("is-thinking", "data", allow_duplicate=True),
    Input("custom-peers-apply", "n_clicks"),
    State("custom-peers-flow", "value"),
    State("custom-peers-country", "value"),
    State("custom-peers-carrier", "value"),
    State("custom-peers-list", "value"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def apply_custom_peers(
    n_clicks: int,
    flow: str,
    country: str | None,
    carrier: str | None,
    peers: list[str] | None,
    chat_history: dict[str, Any],
) -> tuple[Any, Any, Any]:
    """Pin the selected peer set into chat-store; if a mismatch HITL is pending,
    treat this as the "Pick new peers" answer and resume the paused thread."""
    if not n_clicks or not carrier or not peers:
        return no_update, no_update, no_update

    chat_history = chat_history or {}
    new_peers = {
        "flow": flow,
        "country": country,
        "carrier": carrier,
        "peers": list(peers),
    }
    chat_history["custom_peers"] = new_peers

    # "Pick new peers" path: a carrier-mismatch card is awaiting an answer — drop
    # it, record the choice, and resume the graph with the freshly chosen set.
    pending_card = next(
        (
            m
            for m in reversed(chat_history.get("messages", []))
            if m.get("type") == "ClarifyCard"
        ),
        None,
    )
    is_mismatch = (
        chat_history.get("awaiting_clarification")
        and pending_card
        and (pending_card.get("payload") or {}).get("kind") == "custom_peer_mismatch"
    )
    if is_mismatch:
        chat_history["messages"] = [
            m for m in chat_history.get("messages", []) if m.get("type") != "ClarifyCard"
        ]
        chat_history["messages"].append(
            {
                "type": "HumanMessage",
                "content": "Use my new custom peers",
                "rephrased_content": None,
            }
        )
        chat_history["pending_clarification_answer"] = {
            "action": "use_custom",
            "custom_peers": new_peers,
        }
        chat_history["followups"] = []
        return chat_history, True, True

    return chat_history, no_update, no_update


@callback(
    Output("custom-peers-cue", "children"),
    Input("chat-store", "data"),
)
def render_custom_peers_cue(chat_history: dict[str, Any]):
    """Show the composer pill whenever a custom peer set is pinned."""
    return custom_peers_cue((chat_history or {}).get("custom_peers"))


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Input("custom-peers-clear", "n_clicks"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def clear_custom_peers(n_clicks: int, chat_history: dict[str, Any]) -> Any:
    """The cue's ✕ clears the override; peer queries fall back to the Peers table."""
    if not n_clicks:
        return no_update
    chat_history = chat_history or {}
    chat_history.pop("custom_peers", None)
    return chat_history


# 3. -------------------------- LOAD COUNTRY OPTIONS AND VALUE ---------------------------------------


@callback(
    Output("pitch-country", "options"),
    Output("pitch-country", "value"),
    Output("pitch-options-cache", "data"),
    Input("pitch-builder-open", "data"),
    State("pitch-country", "value"),
    State("pitch-options-cache", "data"),
)
def load_pitch_country_options(
    is_open: bool, country: str | None, cache: dict[str, Any]
) -> tuple[list[str] | NoUpdate, str | NoUpdate, dict[str, Any] | NoUpdate]:
    """Updates the country options and selects PREFERRED_COUNTRY"""
    if not is_open:
        return no_update, no_update, no_update

    cache = pitch_cache(cache)
    country_options = cache.get("countries") or distinct_pitch_countries()
    cache["countries"] = country_options

    selection = cache["selection"]
    selected_country = default_option_value(
        country_options,
        country or selection.get("country"),
        PREFFERED_PITCH_COUNTRY,
    )
    selection["country"] = selected_country

    return country_options, selected_country, cache


# 4. -------------------------- LOAD CARRIER OPTIONS AND VALUE ---------------------------------------


@callback(
    Output("pitch-carrier", "options"),
    Output("pitch-carrier", "value"),
    Output("pitch-options-cache", "data", allow_duplicate=True),
    Input("pitch-builder-open", "data"),
    Input("pitch-country", "value"),
    State("pitch-carrier", "value"),
    State("pitch-options-cache", "data"),
    prevent_initial_call=True,
)
def load_pitch_carrier_options(
    is_open: bool, country: str | None, carrier: str | None, cache: dict[str, Any]
) -> tuple[list[str] | NoUpdate, str | NoUpdate, dict[str, Any] | NoUpdate]:
    """Updates the carrier options and selects PREFERRED_CARRIER"""
    if not is_open:
        return no_update, no_update, no_update

    cache = pitch_cache(cache)
    selection = cache["selection"]
    country = country or selection.get("country")
    if not country:
        return no_update, no_update, no_update

    carrier_key = pitch_cache_key(country)
    carrier_options = cache["carriers"].get(carrier_key) or distinct_pitch_carriers(
        country
    )
    cache["carriers"][carrier_key] = carrier_options

    selected_carrier = default_option_value(
        carrier_options,
        carrier or selection.get("carrier"),
        PREFFERED_PITCH_CARRIER,
    )

    selection.update({"country": country, "carrier": selected_carrier})

    return carrier_options, selected_carrier, cache


# 5. -------------------------- LOAD YEAR OPTIONS AND VALUE ---------------------------------------


@callback(
    Output("pitch-year", "options"),
    Output("pitch-year", "value"),
    Output("pitch-options-cache", "data", allow_duplicate=True),
    Input("pitch-builder-open", "data"),
    Input("pitch-country", "value"),
    Input("pitch-carrier", "value"),
    State("pitch-year", "value"),
    State("pitch-options-cache", "data"),
    prevent_initial_call=True,
)
def load_pitch_year_options(
    is_open: bool,
    country: str | None,
    carrier: str | None,
    year: int | None,
    cache: dict[str, Any],
) -> tuple[list[str] | NoUpdate, int | NoUpdate, dict[str, Any] | NoUpdate]:
    """Updates year options and selects the latest year"""
    if not is_open:
        return no_update, no_update, no_update

    cache = pitch_cache(cache)
    selection = cache["selection"]
    country = country or selection.get("country")
    carrier = carrier or selection.get("carrier")
    if not country:
        return no_update, no_update, no_update

    year_key = pitch_cache_key(country, carrier)
    year_options = cache["years"].get(year_key)
    if year_options is None:
        year_options = distinct_pitch_years(country=country, carrier=carrier)
        cache["years"][year_key] = year_options

    if not year_options and country:
        fallback_key = pitch_cache_key(country, "")
        year_options = cache["years"].get(fallback_key)
        if year_options is None:
            year_options = distinct_pitch_years(country=country)
            cache["years"][fallback_key] = year_options

    if not year_options:
        fallback_key = pitch_cache_key("", "")
        year_options = cache["years"].get(fallback_key)
        if year_options is None:
            year_options = distinct_pitch_years()
            cache["years"][fallback_key] = year_options

    selected_year = default_option_value(
        year_options, year or selection.get("year"), latest_option_value(year_options)
    )

    selection.update({"country": country, "carrier": carrier, "year": year})

    return year_options, selected_year, cache


# 6 . -------------------------- DISPLAYS THEME, THEME BASED QUESTIONS  ---------------------------------------


@callback(
    Output("pitch-theme-description", "children"),
    # Output("pitch-questions-heading", "children"),
    Output({"type": "pitch-question", "index": ALL}, "value"),
    Output("pitch-question-section", "style"),
    Input("pitch-theme", "value"),
    Input("pitch-country", "value"),
    Input("pitch-carrier", "value"),
    Input("pitch-year", "value"),
)
def update_pitch_theme(
    theme_key: str, country: str | None, carrier: str | None, year: int
) -> tuple[str, list[str], dict[str, str]]:
    """Displays theme name, and theme specific questions"""
    theme = get_theme(theme_key)
    is_ready = has_pitch_filters(country, carrier, year)
    questions = frame_theme_questions(
        theme_key,
        {"country": country, "carrier": carrier, "year": year},
    )
    section_style = {"display": "block"} if is_ready else {"display": "none"}
    return theme["description"], questions, section_style


# 7 . -------------------------- DISABLES REPORT GENERATION BTN ---------------------------------------


@callback(
    Output("pitch-generate-report-btn", "disabled"),
    Input("pitch-country", "value"),
    Input("pitch-carrier", "value"),
    Input("pitch-year", "value"),
)
def toggle_pitch_generated_button(
    country: str | None, carrier: str | None, year: int | None
) -> bool:
    """Disables the Report Generation btn until country, carrier and year are selected"""
    return not has_pitch_filters(country, carrier, year)


# 8 . -------------------------- UPDATES CACHE ---------------------------------------


@callback(
    Output("pitch-options-cache", "data", allow_duplicate=True),
    Input("pitch-country", "value"),
    Input("pitch-carrier", "value"),
    Input("pitch-year", "value"),
    State("pitch-options-cache", "data"),
    prevent_initial_call=True,
)
def cache_pitch_filter_selection(
    country: str | None, carrier: str | None, year: int | None, cache: dict[str, Any]
) -> dict[str, Any]:
    """Updates the cache data to preserve the selection even after page refresh"""
    cache = pitch_cache(cache)
    cache["selection"].update({"country": country, "carrier": carrier, "year": year})
    return cache


# 9 . -------------------------- REPORT DOWNLOAD AND BACKEND CALLING ---------------------------------------


@callback(
    Output("download-pitch-report", "data"),
    Output("pitch-report-status", "children", allow_duplicate=True),
    Output("pitch-builder-store", "data", allow_duplicate=True),
    Output("pitch-progress-interval", "disabled", allow_duplicate=True),
    Output("pitch-progress-fill", "style", allow_duplicate=True),
    Output("pitch-progress-label", "children", allow_duplicate=True),
    Input("pitch-generate-report-btn", "n_clicks"),
    State("pitch-theme", "value"),
    State("pitch-country", "value"),
    State("pitch-carrier", "value"),
    State("pitch-year", "value"),
    State({"type": "pitch-question", "index": ALL}, "value"),
    State("pitch-builder-store", "data"),
    prevent_initial_call=True,
)
def generate_pitch_report(
    n_clicks: int,
    theme_key: str,
    country: str | None,
    carrier: str | None,
    year: int | None,
    questions: list[str],
    builder_store: dict[str, Any],
) -> tuple[
    dict[str, Any] | NoUpdate,
    Component | NoUpdate,
    dict[str, Any] | NoUpdate,
    bool,
    dict[str, str],
    str,
]:
    # Guard against the spurious fire when the pitch drawer mounts dynamically
    # (it now lives inside the login-gated app shell, so its button appears after
    # the initial page load — and Dash's prevent_initial_call does NOT suppress
    # callbacks whose inputs are added dynamically). Only run on a real click.
    if not n_clicks:
        return no_update, no_update, no_update, no_update, no_update, no_update

    questions = [
        (question or f"Question {index + 1}").strip()
        for index, question in enumerate(questions or [])
    ]
    questions = [question for question in questions if question]

    if not questions:
        return (
            no_update,
            no_update,
            no_update,
            True,
            {"width": "0%"},
            "0% Ready",
        )

    # summary = summarize_filtered_rows(rows)
    filters = {"country": country, "carrier": carrier, "year": year}
    pitch_state = pitch_workflow.trigger_workflow(
        {
            "pitch_theme": theme_key,
            "pitch_theme_label": get_theme(theme_key)["label"],
            "pitch_filters": filters,
            "pitch_questions": questions,
            "pitch_answers": {},
            "pitch_question_results": [],
            "pitch_extracted_insights": [],
        }
    )

    pitch_state: PitchAgentState = {
        "pitch_thread_id": pitch_state.get("pitch_thread_id", ""),
        "pitch_theme": theme_key,
        "pitch_theme_label": get_theme(theme_key)["label"],
        "pitch_filters": filters,
        "messages": [],
        "pitch_answers": pitch_state.get("pitch_answers", {}),
        "pitch_question_results": pitch_state.get("pitch_question_results", []),
        "pitch_extracted_insights": pitch_state.get("pitch_extracted_insights", []),
    }

    pitch_state = pitch_workflow.trigger_report_workflow(pitch_state)

    logger.debug(f" Pitch KPIs : \n {pitch_state.get('pitch_top_kpis')}")

    report_ctx = ReportConfig(
        country=filters.get("country"),
        carrier=filters.get("carrier"),
        year=filters.get("year"),
        question_results=pitch_state.get("pitch_question_results", []),
        filters=pitch_state.get("pitch_filters", {}),
        report_summary=pitch_state.get("pitch_report_summary", ""),
        top_kpis=pitch_state.get("pitch_top_kpis"),
        filename=ReportConfig._safe_filename(f"{carrier}_{country}_{year}.docx"),
        output_path=Path(__file__).parent.parent / "generated_reports",
    )

    output_path = build_pitch_report_docx(ctx=report_ctx)
    logger.debug(f"Output Path is : {output_path}")

    builder_store = builder_store or {}
    builder_store.update(
        {
            "theme": theme_key,
            "filters": filters,
            "pitch_answers": pitch_state["pitch_answers"],
            # "pitch_report_prompt": pitch_state.get("pitch_report_prompt", ""),
            "pitch_report_summary": pitch_state.get("pitch_report_summary", ""),
            "report_path": str(output_path),
        }
    )

    import os

    return (
        dcc.send_file(output_path) if os.path.exists(output_path) else no_update,
        html.Div("Report generated and downloaded.", className="pitch-status-success"),
        builder_store,
        True,
        {"width": "100%"},
        "100% Complete",
    )


# 10. -------------------------- DISPLAY REPORT STATUS ---------------------------------------


@callback(
    Output("pitch-progress-interval", "disabled", allow_duplicate=True),
    Output("pitch-progress-fill", "style", allow_duplicate=True),
    Output("pitch-progress-label", "children", allow_duplicate=True),
    Input("pitch-generated-report-btn", "n_clicks"),
    Input("pitch-progress-interval", "n_intervals"),
    prevent_initial_call=True,
)
def update_pitch_progress(
    generate_clicks: int, ticks: int
) -> tuple[bool | NoUpdate, dict[str, str] | NoUpdate, str | NoUpdate]:
    """Function to update the report generation status bar"""

    triggered_id = ctx.triggered_id
    if triggered_id == "pitch-generate-report-btn" and generate_clicks:
        return False, {"width": "12%"}, "12% Starting"
    if triggered_id != "pitch-progress-interval":
        return no_update, no_update, no_update
    # Spurious fire when the interval mounts dynamically (ticks=0): don't enable
    # the bar or it would start animating on page refresh.
    if not ticks:
        return no_update, no_update, no_update

    pct = min(92, 18 + ((ticks or 0) * 9))
    label = "Reading data"
    if pct >= 42:
        label = "Generating insights"
    if pct >= 72:
        label = "Building report"
    if pct >= 90:
        label = "Finalizing"

    return False, {"width": f"{pct}%"}, f"{pct}% {label}"


# ── CHAT AREA SPECIFIC  ───────────────────────────────────────────────────────────────────────────


# 0. -------------------------- AUTH + APP SHELL ---------------------------------------


def _current_user(user_store: dict[str, Any] | None) -> tuple[Optional[int], str]:
    """Return (user_id, username) from the user-store, or (None, '')."""
    user_store = user_store or {}
    uid = user_store.get("id")
    try:
        uid = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid = None
    return uid, (user_store.get("username") or "")


def _app_shell(user_id: int, username: str) -> Component:
    """Full post-login layout: navbar + sidebar + chat + pitch drawer."""
    conversations = list_conversations(user_id)
    starters = generate_starter_questions(user_id)
    return html.Div(
        [
            build_navbar(),
            html.Div(
                [
                    app_sidebar(conversations, username, collapsed=False),
                    html.Div(
                        html.Div(
                            [
                                # Two panes share main-content; the view-router
                                # callback toggles visibility (chat keeps its DOM
                                # + stores instead of being torn down on switch).
                                html.Div(
                                    chatbot_page(username, starters),
                                    id="view-chat",
                                    className="view-pane",
                                ),
                                html.Div(
                                    decision_board_view(),
                                    id="view-board",
                                    className="view-pane view-hidden",
                                ),
                            ],
                            id="main-content",
                            className="main-content",
                        ),
                        className="main-container",
                    ),
                ],
                className="app-body",
            ),
            pitch_builder_drawer(),
            custom_peers_modal(),
            boardroom_modals(),
            decision_modals(),
        ],
        className="app-shell",
    )


@callback(
    Output("app-root", "children"),
    Input("user-store", "data"),
)
def render_app_root(user_store: dict[str, Any] | None) -> Component:
    """Login gate: show the sign-in screen until a username is chosen."""
    user_id, username = _current_user(user_store)
    if user_id is None:
        return login_screen()
    return _app_shell(user_id, username)


@callback(
    Output("user-store", "data"),
    Output("active-conversation", "data", allow_duplicate=True),
    Output("login-error", "children"),
    Input("login-submit", "n_clicks"),
    Input("login-username", "n_submit"),
    State("login-username", "value"),
    prevent_initial_call=True,
)
def handle_login(
    n_clicks: int, n_submit: int, username: str | None
) -> tuple[Any, Any, Any]:
    """Create-or-fetch the user, seed semantic profile, and sign them in."""
    username = (username or "").strip()
    if not username:
        return no_update, no_update, "Please enter a username."
    user = get_or_create_user(username)
    # Seed semantic memory so the welcome hero can greet by name.
    semantic.set_fact(user["id"], "username", user["username"])
    semantic.set_fact(user["id"], "display_name", user["username"])
    return {"id": user["id"], "username": user["username"]}, None, ""


@callback(
    Output("user-store", "data", allow_duplicate=True),
    Output("active-conversation", "data", allow_duplicate=True),
    Input("logout-btn", "n_clicks"),
    prevent_initial_call=True,
)
def handle_logout(n_clicks: int) -> tuple[Any, Any]:
    if not n_clicks:
        return no_update, no_update
    return None, None


# 1. -------------------------- SIDEBAR: LIST / NEW / OPEN / DELETE ---------------------------------------


@callback(
    Output("conversation-list", "children"),
    Input("chat-store", "data"),
    Input("active-conversation", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def refresh_sidebar(
    chat_history: dict[str, Any], active_id: str | None, user_store: dict[str, Any]
) -> Any:
    """Re-render the conversation list after a turn commits / open / delete."""
    user_id, _ = _current_user(user_store)
    if user_id is None:
        return no_update
    return conversation_list_children(list_conversations(user_id), active_id)


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("active-conversation", "data", allow_duplicate=True),
    Output("chat-box", "children", allow_duplicate=True),
    Input("new-chat-btn", "n_clicks"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def start_new_chat(n_clicks: int, user_store: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Reset to a fresh, empty conversation with the welcome hero."""
    if not n_clicks:
        return no_update, no_update, no_update
    user_id, username = _current_user(user_store)
    starters = generate_starter_questions(user_id) if user_id is not None else None
    # Empty ({}) chat-store is falsy, so render_chat leaves the hero we set here.
    return {}, None, [welcome_hero(username, starters)]


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("active-conversation", "data", allow_duplicate=True),
    Input({"type": "conv-item", "id": ALL}, "n_clicks"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def open_conversation(
    n_clicks_list: list[int | None], user_store: dict[str, Any]
) -> tuple[Any, Any]:
    """Load a saved conversation back into chat-store (transcript + thread_id)."""
    triggered = ctx.triggered_id
    triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None
    if not isinstance(triggered, dict) or not triggered_value:
        return no_update, no_update
    conv_id = triggered.get("id")
    user_id, _ = _current_user(user_store)
    if user_id is None or not conv_id:
        return no_update, no_update
    stored = load_conversation(user_id, conv_id)
    if stored is None:
        return no_update, no_update
    stored.setdefault("thread_id", conv_id)
    return stored, conv_id


@callback(
    Output("conversation-list", "children", allow_duplicate=True),
    Output("chat-store", "data", allow_duplicate=True),
    Output("active-conversation", "data", allow_duplicate=True),
    Output("chat-box", "children", allow_duplicate=True),
    Input({"type": "conv-del", "id": ALL}, "n_clicks"),
    State("user-store", "data"),
    State("active-conversation", "data"),
    prevent_initial_call=True,
)
def delete_conversation_cb(
    n_clicks_list: list[int | None],
    user_store: dict[str, Any],
    active_id: str | None,
) -> tuple[Any, Any, Any, Any]:
    """Delete a chat; if it was the open one, fall back to a fresh hero."""
    triggered = ctx.triggered_id
    triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None
    if not isinstance(triggered, dict) or not triggered_value:
        return no_update, no_update, no_update, no_update
    conv_id = triggered.get("id")
    user_id, username = _current_user(user_store)
    if user_id is None or not conv_id:
        return no_update, no_update, no_update, no_update

    delete_conversation(user_id, conv_id)
    items = conversation_list_children(list_conversations(user_id), active_id)

    if conv_id == active_id:
        starters = generate_starter_questions(user_id)
        return items, {}, None, [welcome_hero(username, starters)]
    return items, no_update, no_update, no_update


# 2. -------------------------- SIDEBAR COLLAPSE (clientside) ---------------------------------------

clientside_callback(
    """
    function(n_clicks, collapsed) {
        const next = !collapsed;
        const base = 'app-sidebar';
        return [next ? base + ' app-sidebar-collapsed' : base, next];
    }
    """,
    Output("app-sidebar", "className"),
    Output("sidebar-collapsed", "data"),
    Input("sidebar-collapse-btn", "n_clicks"),
    State("sidebar-collapsed", "data"),
    prevent_initial_call=True,
)


# 1b. -------------------------- RENDER PAGE (legacy nav link) ---------------------------------------


@callback(
    Output("nav-chatbot", "active"),
    Input("nav-chatbot", "n_clicks"),
    prevent_initial_call=True,
)
def render_page(chatbot_clicks: int) -> bool:
    # The single nav item stays active; the chat page is mounted by the app shell.
    return True


# 2. -------------------------- TRIGGER WOKFLOW + CHAT-STORE UPDATION ---------------------------------------


# --------- helper function ----------------------
def _update_messages(chat_history: dict[str, Any], messages: list[Any]) -> list[Any]:
    """Update the messages list with Rephrased/Original Query"""

    for msg in chat_history.get("messages", {}):
        if msg["type"] == "HumanMessage":
            (
                messages.append(HumanMessage(content=msg["rephrased_content"]))
                if msg.get("rephrased_content")
                else messages.append(HumanMessage(content=msg["content"]))
            )

    return messages


def _update_last_chat_message(
    chat_history: dict[str, Any], user_input: list[str], rephrased_query: str
) -> dict[str, Any]:
    """Update the last chat history message with rephrased query for next turn use"""
    for i in range(len(chat_history["messages"]) - 1, -1, -1):
        if chat_history["messages"][i]["type"] == "HumanMessage":
            chat_history["messages"][i] = {
                "type": "HumanMessage",
                "content": user_input,
                "rephrased_content": rephrased_query,
            }
            break

    return chat_history


def _append_chart_messages(
    chat_history: dict[str, Any], charts: list[dict[str, Any]]
) -> None:
    """Append one `SQLOutputForCharts` message per analyst chart spec."""
    logger.info("append_chart_messages: received %d analyst chart(s)", len(charts or []))
    for i, chart in enumerate(charts or []):
        rows = chart.get("rows")
        # Coerce a ChartOutput model / list-of-specs into a plain dict. A pydantic
        # model here is NOT JSON-serializable and would break the chat-store write
        # (and was being dropped by the dict-only checks downstream).
        chart_data = normalize_chart_spec(chart.get("chart_data"))
        logger.info(
            "append_chart_messages[%d]: rows=%s chart_type=%r keys=%s",
            i,
            (len(rows) if isinstance(rows, list) else type(rows).__name__),
            (chart_data or {}).get("chart_type") if isinstance(chart_data, dict) else type(chart_data).__name__,
            list(chart.keys()),
        )
        chat_history["messages"].append(
            {
                "type": "SQLOutputForCharts",
                "updated_query": rows,
                "chart_data": chart_data,
            }
        )


def _collect_dashboard_charts(
    updated_state: dict[str, Any], table: str
) -> list[dict[str, Any]]:
    """Gather the turn's chart specs as a flat [{rows, chart_data}] list.

    Mirrors the per-route chart selection used for the inline chat rendering, but
    returns the specs so the Boardroom card can lay them out inside the dashboard
    instead of appending separate chart blocks.
    """
    analyst_charts = updated_state.get("analyst_charts") or []
    if analyst_charts:
        return [
            {
                "rows": chart.get("rows"),
                "chart_data": normalize_chart_spec(chart.get("chart_data")),
            }
            for chart in analyst_charts
        ]

    specs: list[dict[str, Any]] = []
    if table == "survey":
        specs.append(
            {
                "rows": updated_state.get("survey_query_result"),
                "chart_data": normalize_chart_spec(updated_state.get("survey_chart")),
            }
        )
    elif table == "premium":
        specs.append(
            {
                "rows": updated_state.get("gpr_query_result"),
                "chart_data": normalize_chart_spec(updated_state.get("gpr_chart")),
            }
        )
    elif table == "both":
        specs.append(
            {
                "rows": updated_state.get("survey_query_result"),
                "chart_data": normalize_chart_spec(updated_state.get("survey_chart")),
            }
        )
        specs.append(
            {
                "rows": updated_state.get("gpr_query_result"),
                "chart_data": normalize_chart_spec(updated_state.get("gpr_chart")),
            }
        )
    # Keep only specs that have both a chart and rows to draw it from.
    return [s for s in specs if s.get("rows") and s.get("chart_data")]


def _update_chat_history(
    chat_history: dict[str, Any], updated_state: dict[str, Any], table: str
) -> dict[str, Any]:
    """Update the Chat History as per the query route"""

    # Boardroom Mode: the terminal boardroom_node distilled the answer into a
    # structured digest. Render the whole turn as a single inline dashboard card
    # (KPIs + commentary + charts) instead of plain commentary + chart blocks.
    # Gate on `boardroom_mode` too: the persistent checkpointer can carry a stale
    # digest from a previous turn, so only honour it when this turn ran in mode.
    boardroom = updated_state.get("boardroom") if updated_state.get("boardroom_mode") else None
    if boardroom:
        charts = _collect_dashboard_charts(updated_state, table)
        # Build the editable document ONCE and persist it on the message, so user
        # edits (values, layout, added widgets/pages) survive re-renders and save
        # with the conversation.
        doc = build_boardroom_document(boardroom, len(charts))
        chat_history["messages"].append(
            {
                "type": "Boardroom",
                "digest": boardroom,
                "doc": doc,
                "charts": charts,
            }
        )
        return chat_history

    # The analyst agent produces its own list of up to 3 charts (each with its own
    # rows). When present, render those instead of the single per-flow chart that
    # the deterministic rails attach.
    analyst_charts = updated_state.get("analyst_charts") or []
    logger.info(
        "update_chat_history: table=%r analyst_charts=%d", table, len(analyst_charts)
    )

    if table == "survey":

        if updated_state.get("survey_overflow", False):
            dataOverflowMsg = updated_state.get("survey_data_overflow_msg", None)
            chat_history["messages"].append(
                {
                    "type": "DataOverflow",
                    "content": dataOverflowMsg,
                    "has_data_overflow": True,
                    "query_result": updated_state["survey_query_result"],
                }
            )

        else:
            survey_response = updated_state.get("survey_response", "")
            sql_output = updated_state.get("survey_query_result")
            sql_output_updated_for_charts = sql_output
            survey_chart_data = normalize_chart_spec(updated_state.get("survey_chart"))

            chat_history["messages"].append(
                {
                    "type": "AIMessage",
                    "content": survey_response.strip(),
                    "has_data_overflow": False,
                }
            )
            if analyst_charts:
                _append_chart_messages(chat_history, analyst_charts)
            else:
                chat_history["messages"].append(
                    {
                        "type": "SQLOutputForCharts",
                        "updated_query": sql_output_updated_for_charts,
                        "chart_data": survey_chart_data,
                    }
                )

    elif table == "premium":
        gpr_response = updated_state.get("gpr_response", "")
        sql_output = updated_state.get("gpr_query_result", [])
        sql_output_updated_for_charts = sql_output
        gpr_chart_data = normalize_chart_spec(updated_state.get("gpr_chart"))

        chat_history["messages"].append(
            {
                "type": "AIMessage",
                "content": gpr_response.strip(),
                "has_data_overflow": False,
            }
        )

        if analyst_charts:
            _append_chart_messages(chat_history, analyst_charts)
        else:
            chat_history["messages"].append(
                {
                    "type": "SQLOutputForCharts",
                    "updated_query": sql_output_updated_for_charts,
                    "chart_data": gpr_chart_data,
                }
            )

        gimmi_response = updated_state.get("gimmi_response", "")
        if gimmi_response:
            chat_history["messages"].append(
                {
                    "type": "AIMessage",
                    "content": gimmi_response.strip(),
                    "has_data_overflow": False,
                }
            )

    elif table == "both":
        combined = (
            updated_state.get("combined_response")
            or updated_state.get("combined_result")
            or ""
        )
        survey_chart_data = normalize_chart_spec(updated_state.get("survey_chart"))
        gpr_chart_data = normalize_chart_spec(updated_state.get("gpr_chart"))
        survey_rows = updated_state.get("survey_query_result") or []
        gpr_rows = updated_state.get("gpr_query_result") or []

        chat_history["messages"].append(
            {
                "type": "AIMessage",
                "content": (combined or "").strip(),
                "has_data_overflow": False,
            }
        )

        # Attach charts for each lens when data is present.
        if analyst_charts:
            _append_chart_messages(chat_history, analyst_charts)
        else:
            if survey_rows and survey_chart_data:
                chat_history["messages"].append(
                    {
                        "type": "SQLOutputForCharts",
                        "updated_query": survey_rows,
                        "chart_data": survey_chart_data,
                    }
                )
            if gpr_rows and gpr_chart_data:
                chat_history["messages"].append(
                    {
                        "type": "SQLOutputForCharts",
                        "updated_query": gpr_rows,
                        "chart_data": gpr_chart_data,
                    }
                )

    elif table == "fallback":
        fallback = updated_state.get("out_of_scope_answer", None)
        chat_history["messages"].append(
            {
                "type": "AIMessage",
                "content": fallback.strip(),
                "has_data_overflow": False,
            }
        )

    return chat_history


# Friendly, human-readable labels for the live "Running X agent…" status line.
# Keys are the main-graph node names (see core.graph.main.create_workflow).
NODE_LABELS = {
    "context_filler": "Understanding your question",
    # clarify_decide / clarify_gate run on EVERY turn (they're pass-throughs when
    # nothing is ambiguous), so their label must stay neutral — otherwise the
    # status falsely reads "clarifying…" on turns that never ask anything. A real
    # clarification surfaces as its own card, not via this status line.
    "clarify_decide": "Analyzing your question",
    "clarify_gate": "Analyzing your question",
    "rephraser_agent": "Rephrasing the query",
    "router": "Routing to the right data",
    "survey_agent": "Querying broker-survey data",
    "gpr_agent": "Querying premium data",
    "combiner_agent": "Combining survey + premium",
    "analyst_agent": "Running the analyst agent",
    "fallback": "Composing a response",
    "survey_data_overflow": "Preparing the data export",
    "survey_insight": "Writing the insight",
    "gpr_insight": "Writing the insight",
    "gimmi_sqlagent_node": "Pulling GIMMI detail",
    "gimmi_execute_sql": "Pulling GIMMI detail",
    "gimmi_sql_fixer_agent": "Refining the query",
    "gimmi_insight": "Writing the GIMMI insight",
    "followup_node": "Suggesting follow-ups",
    "boardroom_node": "Building the boardroom view",
}


def _node_label(node: str | None) -> str:
    if not node:
        return "Thinking"
    return NODE_LABELS.get(node, f"Running {node.replace('_', ' ')}")


def _commit_turn(
    chat_history: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Fold a completed (non-interrupted) turn's final state into the transcript."""
    rephrased_query = state.get("rephrased_user_query")
    table = state.get("current_route")
    last_human = next(
        (
            m.get("content")
            for m in reversed(chat_history.get("messages", []))
            if m.get("type") == "HumanMessage"
        ),
        None,
    )
    if last_human is not None:
        chat_history = _update_last_chat_message(chat_history, last_human, rephrased_query)
    chat_history = _update_chat_history(chat_history, state, table)
    chat_history["followups"] = state.get("followup_questions") or []
    return chat_history


def _launch_job(thread_id: str, input_obj: Any) -> None:
    """Start a streaming graph run for `thread_id` in a background thread."""

    def worker(job: Job) -> None:
        for ev in langgraph.stream_workflow(
            input_obj, thread_id=thread_id, cancel=job.cancel
        ):
            if "interrupt" in ev:
                job.interrupt = ev["interrupt"] or {}
            elif "node" in ev:
                job.current_node = ev["node"]
        if job.cancel.is_set():
            job.cancelled = True
        else:
            # Pull the merged AgentState the UI renders from (route, results, …).
            job.state = langgraph.get_state_values(thread_id)

    start_job(thread_id, worker)


@callback(
    Output("trigger-gpt", "data", allow_duplicate=True),
    Output("job-poll", "disabled", allow_duplicate=True),
    Output("thinking-agent", "children", allow_duplicate=True),
    Input("trigger-gpt", "data"),
    State("chat-store", "data"),
    State("user-store", "data"),
    State("boardroom-mode-store", "data"),
    prevent_initial_call=True,
)
def launch_new_job(
    is_trigger: bool,
    chat_history: dict[str, Any],
    user_store: dict[str, Any],
    boardroom_mode: bool,
) -> tuple[bool, bool | NoUpdate, str | NoUpdate]:
    """Kick off a streaming run for a new user turn (non-blocking)."""
    if not is_trigger:
        return False, no_update, no_update

    chat_history = chat_history or {}
    thread_id = chat_history.get("thread_id") or uuid.uuid4().hex[:12]
    user_id, _ = _current_user(user_store)
    user_input = [
        msg for msg in chat_history["messages"] if msg["type"] == "HumanMessage"
    ][-1]["content"]

    custom_peers = chat_history.get("custom_peers") or None
    state_obj = AgentState(
        messages=[HumanMessage(content=user_input)],
        user_id=str(user_id) if user_id is not None else None,
        survey_attempts=0,
        gpr_attempts=0,
        gimmi_attempts=0,
        custom_peers=custom_peers,
        custom_peers_active=bool(custom_peers and custom_peers.get("peers")),
        boardroom_mode=bool(boardroom_mode),
        # Clear the previous turn's chart/result outputs. The graph runs on a
        # persistent checkpointer, and these channels have no reducer, so a turn
        # that doesn't run a given chart/SQL node would otherwise inherit the last
        # turn's value — which `_update_chat_history` then re-appends, surfacing a
        # stale chart on a turn that produced none. Seeding them empty overwrites.
        analyst_charts=[],
        analyst_evidence=[],
        survey_chart={},
        gpr_chart={},
        combined_chart={},
        survey_query_result=[],
        gpr_query_result=[],
        combined_result=[],
    )
    _launch_job(thread_id, state_obj)
    return False, False, "Starting…"


@callback(
    Output("trigger-resume", "data", allow_duplicate=True),
    Output("job-poll", "disabled", allow_duplicate=True),
    Output("thinking-agent", "children", allow_duplicate=True),
    Input("trigger-resume", "data"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def launch_resume_job(
    is_trigger: bool, chat_history: dict[str, Any]
) -> tuple[bool, bool | NoUpdate, str | NoUpdate]:
    """Kick off a streaming resume after the user answers a clarify card."""
    if not is_trigger:
        return False, no_update, no_update

    chat_history = chat_history or {}
    answer = chat_history.get("pending_clarification_answer")
    thread_id = chat_history.get("thread_id")
    if not answer or not thread_id:
        return False, no_update, no_update

    _launch_job(thread_id, Command(resume=answer))
    return False, False, "Resuming…"


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("is-thinking", "data", allow_duplicate=True),
    Output("job-poll", "disabled", allow_duplicate=True),
    Output("thinking-agent", "children", allow_duplicate=True),
    Output("thinking-elapsed", "children", allow_duplicate=True),
    Input("job-poll", "n_intervals"),
    State("chat-store", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def poll_job(
    n_intervals: int, chat_history: dict[str, Any], user_store: dict[str, Any]
) -> tuple[Any, Any, Any, Any, Any]:
    """Poll the running job each tick; on completion, commit and stop polling."""
    chat_history = chat_history or {}
    thread_id = chat_history.get("thread_id")
    job = get_job(thread_id)

    if job is None:
        return no_update, no_update, True, no_update, no_update

    elapsed = f"{job.elapsed_seconds()}s"

    # Still running — update the live status line, leave the transcript alone.
    if not job.done:
        return no_update, no_update, no_update, _node_label(job.current_node), elapsed

    # Finished: tear the job down and finalize the turn.
    clear_job(thread_id)
    chat_history.pop("pending_clarification_answer", None)
    chat_history["awaiting_clarification"] = False

    if job.cancelled:
        chat_history.setdefault("messages", []).append(
            {"type": "AIMessage", "content": "_Stopped._", "has_data_overflow": False}
        )
        chat_history["followups"] = []
        return chat_history, False, True, "", ""

    if job.error:
        logger.error("Chat job failed: %s", job.error)
        chat_history.setdefault("messages", []).append(
            {
                "type": "AIMessage",
                "content": "Sorry — something went wrong while answering. Please try again.",
                "has_data_overflow": False,
            }
        )
        chat_history["followups"] = []
        return chat_history, False, True, "", ""

    if job.interrupt is not None:
        chat_history.setdefault("messages", []).append(
            {"type": "ClarifyCard", "payload": job.interrupt}
        )
        chat_history["awaiting_clarification"] = True
        chat_history["followups"] = []
        return chat_history, False, True, "", ""

    chat_history = _commit_turn(chat_history, job.state)
    _persist_turn(user_store, chat_history, job.state)
    return chat_history, False, True, "", ""


def _generate_conversation_title(question: str) -> str:
    """A short, human-friendly sidebar label for a chat (e.g. "Zurich Share of
    Wallet · Canada"), generated once from the opening question.

    Uses the cheap summary client (gpt-4o-mini); best-effort — returns "" on any
    failure so the caller falls back to the truncated raw question.
    """
    q = (question or "").strip()
    if not q:
        return ""
    prompt = (
        "Generate a concise title (3-6 words, Title Case) describing the topic of "
        "this insurance-analytics question, for a chat sidebar. Return ONLY the "
        "title: no quotes, no surrounding text, no trailing punctuation.\n\n"
        f"Question: {q[:500]}"
    )
    try:
        resp = Initialization.llm_summary.invoke(prompt)
        text = (getattr(resp, "content", "") or "").strip()
        # Keep the first line, strip stray quotes / trailing punctuation.
        text = text.splitlines()[0].strip().strip("\"'").rstrip(".!?,;:").strip()
        return text[:60]
    except Exception:  # pragma: no cover - titling must never break a turn
        logger.exception("Failed to generate conversation title")
        return ""


def _persist_turn(
    user_store: dict[str, Any] | None,
    chat_history: dict[str, Any],
    state: dict[str, Any],
) -> None:
    """Save the transcript and record an episodic 'question' for this turn.

    Best-effort: persistence/memory failures must never break the chat turn.
    """
    user_id, _ = _current_user(user_store)
    if user_id is None:
        return
    thread_id = chat_history.get("thread_id")
    try:
        save_conversation(user_id, thread_id, chat_history)
        last_human = next(
            (
                m.get("content")
                for m in reversed(chat_history.get("messages", []))
                if m.get("type") == "HumanMessage"
            ),
            None,
        )
        if last_human:
            episodic_store.record_question(
                user_id, thread_id, last_human, state.get("current_route")
            )
            # New activity may change tailored suggestions on the next New chat.
            invalidate_suggestions(user_id)
    except Exception:  # pragma: no cover - never break a turn on persistence
        logger.exception("Failed to persist turn / record episode")


@callback(
    Output("persist-sink", "data"),
    Input("chat-store", "data"),
    State("user-store", "data"),
    State("is-thinking", "data"),
    prevent_initial_call=True,
)
def persist_chat_edits(
    chat_history: dict[str, Any], user_store: dict[str, Any], is_thinking: bool
) -> NoUpdate:
    """Persist out-of-turn edits to the transcript (e.g. Boardroom widget tweaks).

    Boardroom edit callbacks mutate the ``doc`` inside ``chat-store`` but never run
    a graph turn, so without this the changes only live in the in-memory store and
    vanish on reopen. We skip while a turn is streaming — poll_job persists the
    final transcript itself, and saving every poll tick would be wasteful.
    """
    if is_thinking:
        return no_update
    user_id, _ = _current_user(user_store)
    thread_id = (chat_history or {}).get("thread_id")
    if user_id is None or not thread_id:
        return no_update
    save_conversation(user_id, thread_id, chat_history)
    return no_update


@callback(
    Output("thinking-agent", "children", allow_duplicate=True),
    Input("stop-btn", "n_clicks"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def stop_job(n_clicks: int, chat_history: dict[str, Any]) -> str | NoUpdate:
    """Cooperatively cancel the in-flight run; the poll loop finalizes the rest."""
    if not n_clicks:
        return no_update
    cancel_job((chat_history or {}).get("thread_id"))
    return "Stopping…"


# 3. -------------------------- RENDER CHAT ---------------------------------------


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Input("chat-store", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def enrich_chat_store(chat_history: dict[str, Any], user_store: dict[str, Any]) -> Any:
    """One-time enrichments of a committed transcript: Boardroom docs + nice title.

    Both must WRITE chat-store, and chat-store is a write hub — a second
    chat-store→chat-store callback would be scheduled alongside this one in the same
    dispatch and trip Dash's "Duplicate callback outputs". So they share this single
    callback. It runs after `poll_job` has already rendered the answer, so the
    (blocking) title LLM call never delays the visible answer. Self-terminating:
    once docs + title are present, subsequent fires no-op (no render loop).

    1. **Boardroom docs** — the editable doc is normally built at commit time, but
       messages from before that change (or any path that only stored a digest) need
       one too, else render_chat rebuilds a throwaway doc with fresh widget ids on
       every paint and the edit buttons' ids never match the edit callbacks.
    2. **Sidebar title** — a short LLM-generated label from the opening question,
       generated once when an answer exists; cached on `chat_history["title"]`.
    """
    if not chat_history:
        return no_update
    changed = False

    # 1) Boardroom editable docs.
    for msg in chat_history.get("messages") or []:
        if msg.get("type") == "Boardroom" and not msg.get("doc"):
            specs = msg.get("charts") or []
            msg["doc"] = build_boardroom_document(msg.get("digest") or {}, len(specs))
            changed = True

    # 2) Nice sidebar title, once a turn has actually produced an answer.
    if not (chat_history.get("title") or "").strip():
        msgs = chat_history.get("messages") or []
        has_answer = any(
            m.get("type") in ("AIMessage", "Boardroom", "DataOverflow") for m in msgs
        )
        first_q = next(
            (
                m.get("content")
                for m in msgs
                if m.get("type") == "HumanMessage" and (m.get("content") or "").strip()
            ),
            None,
        )
        if has_answer and first_q:
            title = _generate_conversation_title(first_q)
            if title:
                chat_history["title"] = title
                # Persist now so refresh_sidebar (reads the DB) shows the new title.
                user_id, _ = _current_user(user_store)
                thread_id = chat_history.get("thread_id")
                if user_id is not None and thread_id:
                    save_conversation(user_id, thread_id, chat_history)
                changed = True

    return chat_history if changed else no_update


@callback(
    Output("chat-box", "children"),
    Input("chat-store", "data"),
    Input("is-thinking", "data"),
    Input("boardroom-edit-mode", "data"),
    State("boardroom-active-page", "data"),
    prevent_initial_call=True,
)
def render_chat(
    chat_history: dict[str, Any],
    is_thinking: bool,
    edit_mode: bool,
    active_pages: dict[str, Any],
) -> list[Any] | NoUpdate:

    chat_items: list[Any] = []
    chart_idx = 0  # unique, stable per-chart id for the Chart/Data toggle

    # Guard on messages presence: chat-store can hold side state (e.g. custom_peers)
    # before any turn exists. Returning [] then would wipe the welcome hero, so only
    # re-render once there is an actual transcript.
    if chat_history and chat_history.get("messages"):
        for msg_idx, msg in enumerate(chat_history["messages"]):
            if msg["type"] == "Boardroom":
                # The editable document is built + stored at commit time; rebuild it
                # for legacy messages that predate the builder.
                specs = msg.get("charts") or []
                doc = msg.get("doc") or build_boardroom_document(
                    msg.get("digest") or {}, len(specs)
                )
                # Figures kept index-aligned with specs (None where unbuildable) so a
                # chart widget's spec_index always maps to the right figure. Shared
                # with the PPT export so both views draw identical charts.
                figures = boardroom_figures_for_specs(specs, doc, compact=True)
                active_page = int((active_pages or {}).get(str(msg_idx), 0) or 0)
                chat_items.append(
                    render_boardroom_document(
                        doc, figures, edit_mode=bool(edit_mode),
                        card_idx=msg_idx, active_page=active_page,
                    )
                )

            elif msg["type"] == "SQLOutputForCharts":
                # Skip entirely when there is no chart spec or no rows (e.g. an
                # analyst turn whose route had no per-flow chart attached).
                if not msg.get("chart_data") or not msg.get("updated_query"):
                    logger.info(
                        "render_chat: skipping chart msg (chart_data=%s updated_query=%s)",
                        bool(msg.get("chart_data")),
                        bool(msg.get("updated_query")),
                    )
                    continue
                try:
                    df = pd.DataFrame(msg["updated_query"])
                    fig, chart_message = generate_chart(
                        df=df,
                        chart_outputs=msg["chart_data"],
                    )
                    logger.info(
                        "render_chat: chart_type=%r df_shape=%s -> fig=%s msg=%r",
                        msg["chart_data"].get("chart_type") if isinstance(msg["chart_data"], dict) else type(msg["chart_data"]).__name__,
                        df.shape,
                        fig is not None,
                        chart_message,
                    )

                    if fig is not None:
                        chat_items.append(
                            chart_block(
                                fig,
                                list(df.columns),
                                df.to_dict("records"),
                                chart_idx,
                            )
                        )
                        chart_idx += 1
                    elif chart_message:
                        # Only surface a flag for a genuine reason (e.g. scalar);
                        # an empty message means "nothing to draw" — stay silent.
                        chat_items.append(
                            html.Div(chart_message, className="message gpt-chart-flag")
                        )
                except Exception:
                    logger.exception("Exception in Output")

            elif msg["type"] == "HumanMessage":
                chat_items.append(
                    html.Div(msg["content"], className="message user-message")
                )

            elif msg["type"] == "AIMessage":
                content = msg.get("content") or ""

                # Detect the consulting-grade format and wrap it as an insight card.
                # The deterministic rails always lead with "Executive Summary";
                # the analyst agent uses dynamic, query-shaped H3 headings, so we
                # also treat any answer with multiple "### " sections as an insight.
                is_insight = (
                    "Executive Summary" in content
                    or content.lstrip().startswith("### ")
                    or content.count("### ") >= 2
                )

                chat_items.append(ai_message(content, is_insight, idx=msg_idx))

            elif msg["type"] == "ClarifyCard":
                chat_items.append(clarify_card(msg.get("payload") or {}))

            elif msg["type"] == "DataOverflow":
                try:
                    parts = [dcc.Markdown(msg["content"])]
                    chat_items.append(
                        html.Div(parts, className="message overflow-message")
                    )

                    chat_items.append(
                        html.Div([html.Button("Excel Data", id="download-btn")])
                    )

                except Exception:
                    logger.exception("Error rendering the data-overflow message")

        # The live "Running X agent… · Ns" status renders in the dedicated
        # thinking-bar above the input (updated by poll_job), not inline here.
        if not is_thinking:
            followups = (chat_history or {}).get("followups") or []
            block = followup_suggestions(followups)
            if block is not None:
                chat_items.append(block)

        return chat_items

    return no_update


# 4. -------------------------- UPDATE CHAT-STORE ---------------------------------------


@callback(
    Output("chat-store", "data"),
    Output("trigger-gpt", "data"),
    Output("is-thinking", "data"),
    Output("user-input", "value"),
    Input("send-btn", "n_clicks"),
    State("user-input", "value"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def update_chat(
    n_clicks: int, user_input: str, chat_history: dict[str, Any]
) -> tuple[dict[str, Any], Optional[bool], Optional[bool], Optional[str]]:

    chat_history = chat_history or {}
    chat_history.setdefault("thread_id", uuid.uuid4().hex[:12])

    if not (user_input or "").strip():
        return chat_history, no_update, no_update, no_update

    chat_history.setdefault("messages", []).append(
        {
            "type": "HumanMessage",
            "content": user_input.strip(),
            "rephrased_content": None,
        }
    )
    chat_history["followups"] = []  # drop previous-turn suggestions

    return chat_history, True, True, ""


# 4b. -------------------------- SUGGESTION / FOLLOW-UP CHIP CLICK ---------------------------------------


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("trigger-gpt", "data", allow_duplicate=True),
    Output("is-thinking", "data", allow_duplicate=True),
    Input({"type": "suggestion-chip", "idx": ALL, "q": ALL}, "n_clicks"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def ask_suggested_question(
    n_clicks_list: list[int | None], chat_history: dict[str, Any]
) -> tuple[dict[str, Any] | NoUpdate, Optional[bool], Optional[bool]]:
    """Send a starter or follow-up chip's question as if the user typed it."""

    triggered = ctx.triggered_id
    triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None

    # Guard against the spurious fire when new chips mount with n_clicks=0/None.
    if not isinstance(triggered, dict) or not triggered_value:
        return no_update, no_update, no_update

    question = (triggered.get("q") or "").strip()
    if not question:
        return no_update, no_update, no_update

    chat_history = chat_history or {}
    chat_history.setdefault("thread_id", uuid.uuid4().hex[:12])
    chat_history.setdefault("messages", []).append(
        {
            "type": "HumanMessage",
            "content": question,
            "rephrased_content": None,
        }
    )
    chat_history["followups"] = []  # drop previous-turn suggestions

    return chat_history, True, True


# 4c. -------------------------- HITL CLARIFICATION SUBMIT + RESUME ---------------------------------------


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("trigger-resume", "data", allow_duplicate=True),
    Output("is-thinking", "data", allow_duplicate=True),
    Output("custom-peers-open", "data", allow_duplicate=True),
    Input({"type": "clarify-option", "qid": ALL, "value": ALL}, "n_clicks"),
    Input({"type": "clarify-free-submit", "qid": ALL}, "n_clicks"),
    State({"type": "clarify-free-text", "qid": ALL}, "value"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def submit_clarification(
    option_clicks: list[int | None],
    free_clicks: list[int | None],
    free_texts: list[str | None],
    chat_history: dict[str, Any],
) -> tuple[Any, Any, Any, Any]:
    """Record one question's answer; resume once EVERY question is answered.

    The clarify card may carry several questions (unresolved-entity "did you
    mean" MCQs + the LLM ambiguity question). Each click answers ONE question
    (keyed by qid); partial answers re-render the card with the selection
    locked, and the resume worker fires only when the last open question is
    answered — with `{question_id: answer}` for the multi-question gate, or the
    bare string the single-question custom-peer gate expects. Kept deliberately
    fast (no LLM call) so the thinking indicator paints immediately.
    """

    triggered = ctx.triggered_id
    triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None

    # Guard the spurious fire when the card (re)mounts (n_clicks 0/None).
    if not triggered_value or not isinstance(triggered, dict):
        return no_update, no_update, no_update, no_update

    qid = str(triggered.get("qid") or "q0")
    if triggered.get("type") == "clarify-option":
        answer = (triggered.get("value") or "").strip()
    elif triggered.get("type") == "clarify-free-submit":
        # Map this question's typed value out of the aligned pattern states.
        answer = ""
        states = ctx.states_list[0] if ctx.states_list else []
        for entry in states:
            entry_id = entry.get("id") or {}
            if str(entry_id.get("qid")) == qid:
                answer = (entry.get("value") or "").strip()
                break
    else:
        return no_update, no_update, no_update, no_update

    if not answer:
        return no_update, no_update, no_update, no_update

    chat_history = chat_history or {}
    if not chat_history.get("awaiting_clarification"):
        return no_update, no_update, no_update, no_update

    pending_card = next(
        (
            m
            for m in reversed(chat_history.get("messages", []))
            if m.get("type") == "ClarifyCard"
        ),
        None,
    )
    if pending_card is None:
        return no_update, no_update, no_update, no_update
    payload = dict(pending_card.get("payload") or {})

    # "Pick new peers" on the carrier-mismatch card opens the Custom Peers dialog
    # instead of resuming; the thread stays paused until apply_custom_peers resumes
    # it with the freshly chosen set. Leave the card + awaiting flag intact.
    if payload.get("kind") == "custom_peer_mismatch" and answer == "Pick new peers":
        return no_update, no_update, no_update, True

    questions = clarify_questions_of(payload)
    answers = dict(payload.get("answers") or {})
    answers[qid] = answer
    open_qids = [
        q_id
        for q in questions
        if (q_id := str(q.get("id") or "q0")) not in answers
    ]

    if open_qids:
        # Partial: lock this question's selection and keep the card up.
        payload["answers"] = answers
        pending_card["payload"] = payload
        return chat_history, no_update, no_update, no_update

    # Complete: drop the card; record the answers as one readable user turn.
    summary = "; ".join(
        answers[q_id]
        for q in questions
        if (q_id := str(q.get("id") or "q0")) in answers
    )
    chat_history["messages"] = [
        m for m in chat_history.get("messages", []) if m.get("type") != "ClarifyCard"
    ]
    chat_history["messages"].append(
        {"type": "HumanMessage", "content": summary, "rephrased_content": None}
    )
    # Resume value: the clarify gate takes {qid: answer}; the single-question
    # custom-peer gate (flat legacy payload, no "questions" key) takes a string.
    if "questions" in payload:
        resume_value: Any = answers
    else:
        resume_value = answer
    # Hand the answers to the resume worker; keep awaiting_clarification True
    # until the resume actually completes so a stray click can't double-resume.
    chat_history["pending_clarification_answer"] = resume_value
    chat_history["followups"] = []

    return chat_history, True, True, no_update


# 5. -------------------------- DOWNLOAD BTN FOR ADDITIONAL DATA ---------------------------------------


@callback(
    Output("download-excel", "data"),
    Input("download-btn", "n_clicks", allow_optional=True),
    Input("chat-store", "data"),
    State("chat-box", "children"),
    prevent_initial_call=True,
)
def download_data(n_clicks, chat_history, chat_messages):
    if chat_history:
        try:
            for msg in chat_history["messages"]:
                if msg["type"] == "DataOverflow":

                    triggered = ctx.triggered_id

                    if (triggered == "download-btn") and (n_clicks):
                        data = msg["query_result"]

                        df = pd.DataFrame(data)
                        return dcc.send_data_frame(
                            df.to_excel, "query_data.xlsx", index=False
                        )

                else:
                    continue

        except Exception:
            logger.exception("Error while downloading data")
            return None

    return no_update


# 6. -------------------------- THUMBS UP/DOWN FEEDBACK ---------------------------------------


# Instant visual confirmation: mark the clicked thumb active (clientside, no
# round-trip). The server callback below records it to episodic memory.
clientside_callback(
    """
    function(up, down) {
        const ctx = window.dash_clientside.callback_context;
        const trig = ctx.triggered.length ? ctx.triggered[0].prop_id : '';
        const isUp = trig.indexOf('"rating":"up"') !== -1;
        return [
            isUp ? 'msg-feedback-btn active' : 'msg-feedback-btn',
            !isUp ? 'msg-feedback-btn active' : 'msg-feedback-btn',
        ];
    }
    """,
    Output({"type": "msg-feedback", "idx": MATCH, "rating": "up"}, "className"),
    Output({"type": "msg-feedback", "idx": MATCH, "rating": "down"}, "className"),
    Input({"type": "msg-feedback", "idx": MATCH, "rating": "up"}, "n_clicks"),
    Input({"type": "msg-feedback", "idx": MATCH, "rating": "down"}, "n_clicks"),
    prevent_initial_call=True,
)


@callback(
    Output("feedback-sink", "data"),
    Input({"type": "msg-feedback", "idx": ALL, "rating": ALL}, "n_clicks"),
    State("chat-store", "data"),
    State("user-store", "data"),
    State("active-conversation", "data"),
    prevent_initial_call=True,
)
def record_message_feedback(
    n_clicks_list: list[int | None],
    chat_history: dict[str, Any],
    user_store: dict[str, Any],
    active_id: str | None,
) -> Any:
    """Persist a thumbs up/down for an answer into episodic memory."""
    triggered = ctx.triggered_id
    triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None
    if not isinstance(triggered, dict) or not triggered_value:
        return no_update

    user_id, _ = _current_user(user_store)
    if user_id is None:
        return no_update

    rating = triggered.get("rating")
    idx = triggered.get("idx")
    chat_history = chat_history or {}
    conv_id = (chat_history.get("thread_id")) or active_id
    messages = chat_history.get("messages", [])
    note = None
    if isinstance(idx, int) and 0 <= idx < len(messages):
        note = (messages[idx].get("content") or "")[:300]

    episodic_store.record_feedback(user_id, conv_id, rating, note)
    return {"idx": idx, "rating": rating}
