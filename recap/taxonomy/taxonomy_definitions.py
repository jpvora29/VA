"""
taxonomy/taxonomy_definitions.py

Authoritative definitions for all four umbrella categories and their
sub-categories.

Source of truth: Key Takeaways.xlsx (assets provided by the business).

Labels, sub-category names, and definitions are taken verbatim from that
file and must not be changed without updating the Excel as well.

These definitions are injected verbatim into LLM classifier prompts so
the model uses the company's formal meaning rather than its own inference.
"""

from __future__ import annotations

from typing import Dict, List

# ---------------------------------------------------------------------------
# Umbrella + sub-category definitions
# ---------------------------------------------------------------------------

UMBRELLA_DEFINITIONS: Dict[str, Dict] = {

    # ── 1. Performance & Position ────────────────────────────────────────────
    "performance_and_position": {
        "label": "Performance & Position",
        "definition": (
            "Insights that describe how the carrier or the overall relationship "
            "is performing commercially. This umbrella covers aggregate premium "
            "volume, retention, new business, line-of-business results, and "
            "country or regional trading outcomes measured against targets, prior "
            "periods, or peer benchmarks."
        ),
        "sub_categories": {
            "overall_trading_performance": {
                "label": "Overall Trading Performance",
                "definition": (
                    "Aggregate premium volume (YoY growth), retention rates by "
                    "product line, attachment rates, and contribution to Marsh's "
                    "overall portfolio and revenue targets; performance against "
                    "agreed growth KPIs from the ICG Agreement."
                ),
            },
            "new_business_performance": {
                "label": "New Business Performance",
                "definition": (
                    "New wins and cross-sell conversion rates, particularly in "
                    "priority segments and geographies; capture rate against target "
                    "OpCos; evidence of successful product adoption or sector "
                    "penetration; alignment with carrier's new business appetite."
                ),
            },
            "line_of_business_performance": {
                "label": "Line of Business Performance",
                "definition": (
                    "Detailed breakdown of retention, growth, profitability, and "
                    "competitive standing by product line (e.g., property, casualty, "
                    "financial lines, specialty); underperformers and standout "
                    "performers; gap analysis vs. peers and carrier's strategic aims."
                ),
            },
            "country_regional_performance": {
                "label": "Country / Regional Performance",
                "definition": (
                    "Comparative performance across Marsh's key geographies and "
                    "operating companies; markets where the carrier is over- or "
                    "under-represented; emerging opportunities in growth regions; "
                    "competitive dynamics and market share trends by country or region."
                ),
            },
        },
    },

    # ── 2. Opportunity & Growth ───────────────────────────────────────────────
    "opportunity_and_growth": {
        "label": "Opportunity & Growth",
        "definition": (
            "Insights that identify forward-looking commercial potential or "
            "strategic expansion. This umbrella covers Marsh-led or co-led "
            "facilities and portfolio solutions the carrier could participate in, "
            "and segment priorities where growth is being targeted for the period."
        ),
        "sub_categories": {
            "facilities_and_portfolio_solutions": {
                "label": "Facilities & Portfolio Solutions",
                "definition": (
                    "Carrier appetite and performance in Marsh-led or co-led "
                    "facilities, panels, and portfolio solutions (including group "
                    "captives, programme facilities, and integrated risk solutions); "
                    "opportunities to deepen Marsh placement through bespoke "
                    "structures; and strategic fit between carrier capacity and "
                    "Marsh's corporate or specialty client base."
                ),
            },
            "segment_focus": {
                "label": "Segment Focus",
                "definition": (
                    "Primary underwriting priority for the period (e.g., mid-market, "
                    "large corporate, multinational, specialty sectors) and degree of "
                    "alignment with Marsh's strategic segment goals; implications for "
                    "resource planning and placement focus across Marsh OpCos and "
                    "broking leadership engagement."
                ),
            },
        },
    },

    # ── 3. Market & External Context ─────────────────────────────────────────
    "market_and_external_context": {
        "label": "Market & External Context",
        "definition": (
            "Insights driven by factors external to the Marsh-carrier relationship: "
            "hard and soft market dynamics, competitive repositioning, and material "
            "strategic or operational changes within the carrier. Use this umbrella "
            "when the insight explains the external or internal carrier backdrop "
            "against which the trading performance should be read."
        ),
        "sub_categories": {
            "market_conditions": {
                "label": "Market Conditions",
                "definition": (
                    "Hard and soft market dynamics affecting carrier underwriting "
                    "appetite, premium adequacy, and capacity allocation; pricing "
                    "trends in key lines; competitive repositioning by other carriers; "
                    "and how these shifts influence Marsh's placement strategy and "
                    "negotiating posture with this carrier."
                ),
            },
            "carrier_strategic_developments": {
                "label": "Carrier Strategic Developments",
                "definition": (
                    "Material strategic or operational changes within the carrier "
                    "(e.g., M&A, leadership changes, appetite reset, new product "
                    "launches, geographic expansion, or operational restructuring) "
                    "that signal evolving priorities and may create consulting or "
                    "collaboration opportunities; alignment with Marsh's sector or "
                    "market focus."
                ),
            },
        },
    },

    # ── 4. Relationship & Collaboration ──────────────────────────────────────
    "relationship_and_collaboration": {
        "label": "Relationship & Collaboration",
        "definition": (
            "Insights about the quality, health, and strategic alignment of the "
            "Marsh-carrier relationship. This umbrella covers overall partnership "
            "sentiment, strategic initiative alignment, and the quality of market "
            "engagement — appetite clarity, quote responsiveness, and "
            "competitiveness."
        ),
        "sub_categories": {
            "relationship_health": {
                "label": "Relationship Health",
                "definition": (
                    "Quantitative and qualitative health assessment: senior management "
                    "sentiment, responsiveness to queries and exceptions, speed of "
                    "quote turnaround, quality of underwriting guidance, and "
                    "collaborative tone; early warning indicators of tension or "
                    "disengagement; readiness for strategic or governance conversations."
                ),
            },
            "strategic_initiatives": {
                "label": "Strategic Initiatives",
                "definition": (
                    "Degree of alignment between carrier's stated strategic priorities "
                    "(e.g., underwriting discipline, new sector entry, client service "
                    "enhancements) and Marsh's placement strategy and consulting "
                    "recommendations; opportunities to co-design solutions or influence "
                    "carrier direction through senior engagement."
                ),
            },
            "market_engagement_quality": {
                "label": "Market Engagement Quality",
                "definition": (
                    "Carrier's visibility, leadership presence, and competitive "
                    "positioning in the market; quality and frequency of engagement "
                    "with Marsh's client base; appetite signalling through rate moves "
                    "and terms; evidence of market-leading innovation or pricing "
                    "discipline."
                ),
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Canonical key lists (used by classifiers and the pipeline)
# ---------------------------------------------------------------------------

UMBRELLA_KEYS: List[str] = list(UMBRELLA_DEFINITIONS.keys())


# ---------------------------------------------------------------------------
# Helpers used by classifier prompts
# ---------------------------------------------------------------------------

def get_umbrella_definition(umbrella_key: str) -> str:
    """Return the definition string for a given umbrella key."""
    return UMBRELLA_DEFINITIONS[umbrella_key]["definition"]


def get_sub_category_block(umbrella_key: str) -> str:
    """
    Return a formatted sub-category block for injection into LLM prompts.
    """
    sub_cats = UMBRELLA_DEFINITIONS[umbrella_key]["sub_categories"]
    lines: List[str] = []
    for key, meta in sub_cats.items():
        lines.append(f"  {key}: {meta['definition']}")
    return "\n".join(lines)


def get_full_taxonomy_block() -> str:
    """
    Return a human-readable summary of the entire taxonomy for
    injection into recap or multi-label prompt contexts.
    """
    blocks: List[str] = []
    for key, meta in UMBRELLA_DEFINITIONS.items():
        blocks.append(
            f"=== {meta['label']} ===\n"
            f"{meta['definition']}\n\n"
            f"Sub-categories:\n{get_sub_category_block(key)}"
        )
    return "\n\n".join(blocks)


def get_all_sub_category_keys(umbrella_key: str) -> List[str]:
    """Return the list of valid sub-category keys for an umbrella."""
    return list(UMBRELLA_DEFINITIONS[umbrella_key]["sub_categories"].keys())
