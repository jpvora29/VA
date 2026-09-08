"""The vocabulary of reasons a slot is still the template's placeholder.

One entry per reason, each written to answer the two questions an author actually asks
when they see a blank on a page they are about to send:

    why is this empty?      →  ``why``, the mechanism — what the fill engine tried
    can I do anything?      →  ``fix``, the change that would resolve it, or nothing

Kept as data in one dict so a new reason is a new entry, not an edit to the renderer.
Nothing here formats: the page decides how a cause looks.
"""
from __future__ import annotations

from typing import Dict

from studio.review.model import Cause

# ── data the run does not have ───────────────────────────────────────────────

NO_REPORTING_YEAR = "no_reporting_year"
NO_PRIOR_YEAR = "no_prior_year"
NO_PEER_BENCHMARK = "no_peer_benchmark"
NO_MARKET_RANK = "no_market_rank"
NO_SHARE_OF_WALLET = "no_share_of_wallet"
NO_SURVEY_BOOK = "no_survey_book"
NO_SPOTLIGHT = "no_spotlight"
NO_COUNTRY_BREAKDOWN = "no_country_breakdown"
NO_CHART_SERIES = "no_chart_series"
NO_DATA = "no_data"

# ── the template says nothing about what belongs in the box ──────────────────

UNMAPPED_FIGURE = "unmapped_figure"
UNMAPPED_TEXT = "unmapped_text"
UNMAPPED_CHART = "unmapped_chart"

# ── things the author did, or a bug ──────────────────────────────────────────

BLANKED = "blanked"
STALE = "stale"
COMMENTARY_EMPTY = "commentary_empty"


CAUSES: Dict[str, Cause] = {
    NO_REPORTING_YEAR: Cause(
        NO_REPORTING_YEAR,
        "No reporting year could be resolved",
        "Every figure on the deck is a period comparison, so the deck first has to know "
        "which year is 'current'. The selection pins no year and the data in scope "
        "carries none either, so nothing downstream could be computed.",
        "Pin a year in Setup, or check that the dataset's year column is mapped on the "
        "Data page.",
        severity="error",
    ),
    NO_PRIOR_YEAR: Cause(
        NO_PRIOR_YEAR,
        "No prior year in scope, so nothing year-on-year filled",
        "A year-on-year figure needs the reporting year AND the one before it inside the "
        "same filters. The current year resolved; the prior year returned no rows, so "
        "every growth, movement and change box was left as the template authored it "
        "rather than filled with a number that is not there.",
        "Widen the period in Setup, or load a dataset that carries the earlier year. "
        "Everything that is not a comparison filled normally.",
    ),
    NO_PEER_BENCHMARK: Cause(
        NO_PEER_BENCHMARK,
        "Too few carriers in scope for the peer benchmark",
        "The peer figures are the AVERAGE of the top five carriers in scope — never a "
        "named competitor, which is what makes them safe to show a carrier. With fewer "
        "carriers than that in the filters, an average would identify them, so it is not "
        "published.",
        "Relax the filters that narrow the carrier list (product, country or segment), "
        "so at least five carriers remain in scope.",
    ),
    NO_MARKET_RANK: Cause(
        NO_MARKET_RANK,
        "Market rank could not be computed",
        "A rank places the subject against every other carrier in the same scope, so it "
        "needs the whole market for those filters — not just the subject's own rows.",
        "Check that the scope is not pinned to the subject carrier, and that the market "
        "rows for this period are present in the dataset.",
    ),
    NO_SHARE_OF_WALLET: Cause(
        NO_SHARE_OF_WALLET,
        "Share of wallet could not be computed",
        "Share of wallet is the subject's premium as a proportion of the whole Marsh "
        "book in the same scope, so it needs both — the carrier's rows AND the market's "
        "rows for these filters. One of the two came back empty.",
        "Check that the filters leave more than the subject carrier in scope, and that "
        "the period has market rows as well as the carrier's.",
    ),
    NO_SURVEY_BOOK: Cause(
        NO_SURVEY_BOOK,
        "This deck was built on premium data only",
        "The overall survey score comes from the Carrier Survey book, which is a "
        "different source from the premium data. This run's data basis does not include "
        "it, so the survey tiles keep the template's own figure rather than borrowing a "
        "premium number that would be wrong.",
        "Switch the data basis in Setup to the option that includes the Carrier Survey.",
    ),
    NO_SPOTLIGHT: Cause(
        NO_SPOTLIGHT,
        "No single country or product stood out to feature",
        "The 'xyz' callouts feature ONE significant entity — the largest country in "
        "scope, or the largest product when only one country is selected. With nothing "
        "in scope to rank, there is no entity to name.",
        "Widen the country or product filters so there is more than one to compare.",
    ),
    NO_COUNTRY_BREAKDOWN: Cause(
        NO_COUNTRY_BREAKDOWN,
        "No country breakdown for the 'Country (n)' labels",
        "These labels are filled positionally from the subject's premium by country, "
        "biggest first. The breakdown came back empty, so the numbered labels stay as "
        "authored.",
        "Check the country filter, and that the dataset's country column is mapped.",
    ),
    NO_CHART_SERIES: Cause(
        NO_CHART_SERIES,
        "A chart kept the template's own data",
        "The growth quadrant is filled from a computed series rather than from cell "
        "values. No series resolved for this scope, so the chart still shows the numbers "
        "the template was authored with.",
        "Re-check the scope — a chart with no points is usually the same gap as the "
        "figures around it.",
    ),
    NO_DATA: Cause(
        NO_DATA,
        "Mapped, but the data returned nothing",
        "The slot knows which figure belongs in it, and the computation for that figure "
        "returned no value for this scope.",
        "Narrow or widen the selection in Setup and regenerate.",
    ),
    UNMAPPED_FIGURE: Cause(
        UNMAPPED_FIGURE,
        "Nothing near the placeholder says which figure it wants",
        "Slots are mapped by reading the text around them — the row label, the column "
        "header, the slide title. These carry no word the mapper recognises "
        "('premium'/'GWP', 'share of wallet', 'rank', 'peer', 'survey'), so it made no "
        "guess rather than filling them with the wrong number.",
        "Either label the row or column in the template, or map the slot by hand on the "
        "Canvas — select it and pick a role in the inspector.",
    ),
    UNMAPPED_TEXT: Cause(
        UNMAPPED_TEXT,
        "A text placeholder that names no known entity",
        "Text slots fill only when they name something the deck knows — the subject "
        "carrier, or a numbered country label. These do not, so the template's own words "
        "were kept.",
        "Map the slot by hand on the Canvas if it should carry data; otherwise it is "
        "template copy and can be left alone.",
    ),
    UNMAPPED_CHART: Cause(
        UNMAPPED_CHART,
        "A chart the fill engine does not drive",
        "Only the growth quadrant is filled from computed data. Any other chart keeps "
        "the numbers the template was authored with — including externally linked "
        "(think-cell) charts, which are filled in PowerPoint by design.",
        "",
    ),
    BLANKED: Cause(
        BLANKED,
        "A filled value was cleared by an edit",
        "The slot resolved to a real figure and an edit on the Canvas emptied it. The "
        "export would ship a blank box.",
        "Auto-fix restores the computed value; or type the value you meant.",
        severity="error",
    ),
    STALE: Cause(
        STALE,
        "Marked filled, but still reads as a placeholder",
        "The slot is recorded as filled and its text is still a placeholder token "
        "(something like 'xx.x'). This should not happen and would ship a visible "
        "placeholder to a client.",
        "Auto-fix rewrites these from the resolved data.",
        severity="error",
    ),
    COMMENTARY_EMPTY: Cause(
        COMMENTARY_EMPTY,
        "A commentary box was not written",
        "Prose boxes are replaced wholesale, so a box that gets no text keeps whatever "
        "the template was authored with — which on these templates is example "
        "commentary about another carrier.",
        "Regenerate; if it persists, exclude the page in \"What's in your QBR\" rather "
        "than shipping the example text.",
        severity="error",
    ),
}


def cause(cause_id: str) -> Cause:
    """The cause for ``cause_id``, or a generic one — never a KeyError on a live page."""
    return CAUSES.get(cause_id) or Cause(
        cause_id or NO_DATA, "Unfilled", "No value resolved for this slot.", ""
    )


__all__ = [
    "CAUSES", "cause",
    "NO_REPORTING_YEAR", "NO_PRIOR_YEAR", "NO_PEER_BENCHMARK", "NO_MARKET_RANK",
    "NO_SHARE_OF_WALLET",
    "NO_SURVEY_BOOK", "NO_SPOTLIGHT", "NO_COUNTRY_BREAKDOWN", "NO_CHART_SERIES", "NO_DATA",
    "UNMAPPED_FIGURE", "UNMAPPED_TEXT", "UNMAPPED_CHART",
    "BLANKED", "STALE", "COMMENTARY_EMPTY",
]
