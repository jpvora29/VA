"""The chart layer: Chartwright designs the chart, the critic repairs one.

Two halves of the same quality goal, in the order they run:

* `agent` — **Chartwright**, the chart specialist. One tool per chart type, each
  offering only the columns the result set actually has and only the ones whose
  ROLE fits that argument, so a bad spec is unrepresentable rather than repaired.
* `critic` — `ChartSpecCritic`, the pre-render gate that still repairs a spec
  arriving from anywhere else (the older two-phase path, a stored Boardroom
  widget, a hand-edited override).

Both read column roles through `critic.classify_columns`, so prevention and
repair cannot disagree about what a column is.
"""
from core.charts.agent import AGENT_NAME, Chartwright, design_chart  # noqa: F401
from core.charts.critic import ChartSpecCritic, classify_columns  # noqa: F401
from core.charts.profile import ColumnProfile, build_profile  # noqa: F401

__all__ = [
    "AGENT_NAME",
    "Chartwright",
    "ChartSpecCritic",
    "ColumnProfile",
    "build_profile",
    "classify_columns",
    "design_chart",
]
