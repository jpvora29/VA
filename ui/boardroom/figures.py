"""Build the plotly figures for a Boardroom message's chart specs.

One shared path for the on-screen board (`ui.callbacks.render_chat`) and the
PowerPoint export, so a chart always looks the same in both. Figures stay
index-aligned with the specs (None where unbuildable) because chart widgets
reference them by ``spec_index``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from logger import get_logger
from ui.chart_functions import generate_chart

logger = get_logger(__name__)


def chart_type_overrides(doc: Optional[Dict[str, Any]]) -> Dict[int, str]:
    """Per-chart-widget chart_type overrides (from edits) -> {spec_index: type}."""
    overrides: Dict[int, str] = {}
    for page in (doc or {}).get("pages", []):
        for w in page.get("widgets", []):
            if w.get("kind") == "charts":
                si = (w.get("data") or {}).get("spec_index")
                ct = (w.get("meta") or {}).get("chart_type")
                if isinstance(si, int) and ct:
                    overrides[si] = ct
    return overrides


def figures_for_specs(
    specs: List[Dict[str, Any]],
    doc: Optional[Dict[str, Any]] = None,
    *,
    compact: bool = False,
) -> List[Any]:
    """Rebuild one figure per chart spec ({'chart_data', 'rows'}).

    ``compact=True`` applies the small-card layout the inline board uses.
    """
    overrides = chart_type_overrides(doc)
    figures: List[Any] = []
    for i, spec in enumerate(specs or []):
        chart_data = spec.get("chart_data")
        rows = spec.get("rows")
        if not chart_data or not rows:
            figures.append(None)
            continue
        try:
            if i in overrides and isinstance(chart_data, dict):
                chart_data = {**chart_data, "chart_type": overrides[i]}
            fig, _ = generate_chart(df=pd.DataFrame(rows), chart_outputs=chart_data)
            if fig is not None and compact:
                # Shrink fonts and side margins for the card, but KEEP the
                # theme's computed top/bottom margins — they reserve the space
                # that stops the title and legend overlapping.
                fig.update_layout(
                    height=300,
                    margin=dict(l=48, r=16),
                    font=dict(size=11),
                    title=dict(font=dict(size=13)),
                    legend=dict(font=dict(size=10)),
                )
            figures.append(fig)
        except Exception:  # noqa: BLE001 - a bad spec must not break the board
            logger.exception("Boardroom: failed to build a chart figure")
            figures.append(None)
    return figures
