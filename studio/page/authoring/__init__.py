"""QBR Studio authoring shell — the story-led, evidence-governed workspace.

This renders the product direction from ``QBR_STUDIO_VISUAL_DESIGN_BLUEPRINT.md``:
a **Boardroom Canvas** (page composition + widget inspector) and a **Client-ready
Review**, all wrapped around the *same real* ``DeckSpec`` that ``studio.deck.build_deck``
computes from the DB and that ``studio.export.ppt`` writes to PowerPoint. Browser and
PPT are two renderers of one document (blueprint §5).

Pure layout + deterministic derivations. The live Dash callbacks in the
``studio.authoring`` package feed it a deck and the current view/overrides.

The builders live one concern per module — this package re-exports the full,
historical ``authoring`` namespace so ``from studio.page import authoring as A``
and every ``A.<name>`` keep working unchanged:

    constants   modes, theme colors, zoom bounds
    derive      slide status, page counts, provenance flags
    chrome      mode rail + top bar
    data        Data mode (upload, mapping, saved datasets, grid)
    setup       Setup mode form + scope preview
    inspector   the widget inspector (tabs, color picker, appearance)
    canvas      Canvas mode frame, zoom, pages panel, library modal
    review      client-ready checklist + export card
    shell       body_for + authoring_shell assembly
"""
from __future__ import annotations

from studio.page.authoring.canvas import (
    _COMPONENTS,
    _component_library,
    _divider_label,
    _library_modal,
    _page_sections,
    _page_toolbar,
    _pages_panel,
    _thumb_preview,
    _zoom_controls,
    adjusted_zoom,
    canvas_body,
    normalized_zoom,
    zoom_scale,
)
from studio.page.authoring.chrome import _placeholder_topbar, mode_rail, top_bar
from studio.page.authoring.constants import (
    MODES,
    STANDARD_COLORS,
    THEME_COLORS,
    ZOOM_FIT,
    ZOOM_MAX,
    ZOOM_MIN,
    ZOOM_STEP,
    _STATUS_LABEL,
)
from studio.page.authoring.derive import (
    _edited,
    _hidden_ids,
    _is_hidden,
    _prov_badge,
    deck_counts,
    slide_status,
)
from studio.page.authoring.data import data_body
from studio.page.authoring.inspector import (
    _chart_control,
    _color_picker,
    _inspector_panel,
    _inspector_section,
    _inspector_tabs,
    _kv,
    _legacy_widget_inspector,
    _panel_toggle,
    _select_hint,
    _slide_appearance,
    _text_role_editor,
    _widget_appearance,
    _widget_data_body,
    _widget_inspector,
    _widget_rules_body,
    _widget_setup_body,
    _widget_tabs,
)
from studio.page.authoring.review import (
    _checks,
    _overflow_slides,
    _stat_card,
    _unsupported_blocks,
    review_body,
)
from studio.page.authoring.setup import (
    _SECTION_META,
    _audience_length,
    _radio_field,
    _peers_panel,
    _scope_preview,
    _setup_section,
    _template_control,
    BUSY_FLAG_CLASS,
    BUSY_FLAG_ON,
    BUSY_FORM,
    BUSY_PREVIEW,
    BUSY_SECTIONS,
    DATA_BASIS_DEFAULT,
    DATA_BASIS_OPTIONS,
    MIN_CUSTOM_PEERS,
    MIN_PEERS_MESSAGE,
    busy_overlay,
    custom_peer_picker,
    info_tip,
    peer_min_note,
    peer_set_body,
    scope_axes,
    survey_note,
    survey_peer_picker,
    scope_preview_card,
    scope_preview_empty,
    setup_body,
    template_sections_panel,
)
from studio.page.authoring.shell import authoring_shell, body_for, empty_canvas

__all__ = [
    # constants
    "MODES", "THEME_COLORS", "STANDARD_COLORS",
    "ZOOM_MIN", "ZOOM_MAX", "ZOOM_STEP", "ZOOM_FIT",
    # derivations
    "slide_status", "deck_counts",
    # chrome
    "mode_rail", "top_bar",
    # setup
    "scope_preview_empty", "scope_preview_card", "template_sections_panel", "setup_body",
    "peer_set_body", "survey_note", "scope_axes", "busy_overlay", "info_tip",
    "custom_peer_picker", "survey_peer_picker", "peer_min_note",
    "DATA_BASIS_DEFAULT", "DATA_BASIS_OPTIONS", "MIN_CUSTOM_PEERS", "MIN_PEERS_MESSAGE",
    "BUSY_FLAG_CLASS", "BUSY_FLAG_ON", "BUSY_FORM", "BUSY_PREVIEW", "BUSY_SECTIONS",
    # canvas
    "normalized_zoom", "adjusted_zoom", "zoom_scale", "canvas_body",
    # data / review (review hosts the export card)
    "data_body", "review_body",
    # shell
    "empty_canvas", "body_for", "authoring_shell",
]
