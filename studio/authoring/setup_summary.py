"""The read-outs around the Setup form that say what the brief adds up to.

* the **action bar** — ready or not, the page count, the books and the audience, beside
  Generate (a server callback: the page count needs the template catalog);
* the **cover preview** — plain text of what is selected, painted in the browser
  (assets/studio_v6.js) so it follows every pick at once instead of waiting on a round trip.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from dash import ALL, ClientsideFunction, Input, Output, State, html

from studio.page.authoring import setup as S
from studio.template_fill.deck_slides import DeckSlides

_AUDIENCE = {"carrier_leadership": "Carrier team", "marsh_regional": "Regional"}
_BASIS = {S.DATA_BASIS_WITH_SURVEY: "GPR + Survey"}


def page_count(basis: Optional[str], slides: DeckSlides) -> int:
    """Distinct pages the deck carries — the same count the page list shows."""
    return S.base_page_count(basis, slides)


def _carrier(ids: Sequence[Mapping[str, Any]], values: Sequence[Any]) -> Optional[str]:
    for ident, value in zip(ids or [], values or []):
        if (ident or {}).get("col") == "carrier" and value not in (None, "", []):
            return str(value)
    return None


def bar_state(carrier: Optional[str], pages: int, basis: Optional[str],
              audience: Optional[str], source: Optional[str]):
    """``(icon class, status text, summary text, ready)`` for the action bar."""
    books = "Custom data" if source == "custom" else _BASIS.get(str(basis), "GPR only")
    parts = [f"{pages} page" + ("s" if pages != 1 else ""), books,
             _AUDIENCE.get(str(audience), "Carrier team")]
    summary = " · ".join(parts)
    if not carrier:
        return "bi bi-circle", "Pick a carrier to begin", summary, False
    if pages == 0:
        return "bi bi-exclamation-circle-fill", "No pages ticked", summary, False
    return "bi bi-check-circle-fill", f"Scope selected — {carrier}", summary, True


def register_setup_summary(app) -> None:
    @app.callback(
        Output("qs6-status-icon", "children"),
        Output("qs6-status-text", "children"),
        Output("qs6-summary", "children"),
        Output("qs6-status-icon", "className"),
        Output("qs6-source-badge", "children"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        Input("qs-slides", "data"),
        Input("studio-data-basis", "value"),
        Input("studio-audience", "value"),
        Input("studio-data-source", "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
    )
    def paint_bar(values, slides, basis, audience, source, ids):
        """The one-line answer to "is this ready to generate, and what will it be?"."""
        icon, text, summary, ready = bar_state(
            _carrier(ids, values), page_count(basis, DeckSlides.from_store(slides)),
            basis, audience, source)
        badge = "Custom data" if source == "custom" else "Governed data"
        return (html.I(className=icon), text, summary,
                "qs6-status-icon" + (" is-ready" if ready else ""), badge)

    app.clientside_callback(
        ClientsideFunction(namespace="qs6", function_name="paintCover"),
        Output("qs6-cover-carrier", "children"),
        Output("qs6-cover-period", "children"),
        Output("qs6-cover-scope", "children"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        Input("studio-period-basis", "value"),
        Input("studio-period-dates", "data"),
        State({"type": "studio-filter", "col": ALL}, "id"),
    )
