"""Synthetic review cases: expected meaning, not phrases an author must reproduce.

None of these figures describe a real carrier. Keep the negative examples alongside
the references so a fluent but unsupported answer cannot count as an improvement.
"""
from dataclasses import dataclass

from studio.segments import Placement, SegmentFinding, SegmentFindings
from studio.template_fill.commentary_evidence import build_pack


@dataclass(frozen=True)
class ReviewCase:
    name: str
    topic: str
    facts: dict
    reference: str
    fact_ids: tuple[str, ...]
    reject: str
    reason: str

    @property
    def pack(self):
        return build_pack(self.facts)


def _facts(current=12e6, prior=10e6, marsh=100e6, marsh_prior=80e6, **extra):
    result = {
        "subject": "Example Carrier",
        "scope": {"Country": "Singapore", "Product_Line": "Environmental", "Year": 2025},
        "carrier": {"current_year": 2025, "current": current, "prior": prior,
                    "delta": current-prior, "pct": (current/prior-1)*100 if prior > 0 else None},
        "marsh": {"current": marsh, "prior": marsh_prior,
                  "pct": (marsh/marsh_prior-1)*100 if marsh_prior > 0 else None},
        "sow": {"current": current/marsh*100,
                "delta": (current/marsh-prior/marsh_prior)*100},
    }
    result.update(extra)
    return result


def _segment(**kwargs):
    row = SegmentFinding(dim="SIC_Major_Class", **kwargs)
    return {"industry": SegmentFindings(dim=row.dim, label="industry", rows=(row,))}


def cases() -> tuple[ReviewCase, ...]:
    services = _facts(segments=_segment(
        name="Services", carrier=840000, market=5e6, sow=16.8, prior_sow=25.7,
        sow_delta=-8.9, market_yoy=38.6, prior_market=5e6/1.386,
        prior_carrier=.257*5e6/1.386, placement=Placement.LOSING))
    env = _facts(current=12.9e6, prior=12e6,
                 peer={"sow": 18.5, "n_carriers": 10, "benchmark_count": 5})
    return (
        ReviewCase("services_share_loss", "challenges", services,
                   "Example Carrier's share of Marsh's Services premium fell from 25.7% to 16.8%, while Marsh's Services premium grew 38.6%.",
                   ("segment.industry.losing.services",),
                   "Services also lost 8.9 percentage points to 16.8% of a $5M pool that grew 38.6%, so Marsh demand outpaced the book.",
                   "Name whose share fell; premium growth does not establish demand growth."),
        ReviewCase("environmental_benchmark", "challenges", env,
                   "Example Carrier received 12.9% of Marsh's Environmental premium, compared with 18.5% on average across the five largest carriers in this scope.",
                   ("sow.current", "peer.sow", "scope.Product_Line"),
                   "Environmental accounted for 12.9% of the carrier's portfolio, against peers at 18.5%.",
                   "Share of Marsh placements is not the carrier's portfolio mix."),
        ReviewCase("premium_up_share_down", "performance", _facts(),
                   "Example Carrier's Marsh-placed premium grew 20.0% to $12M. Its share of Marsh placements fell from 12.5% to 12.0%.",
                   ("carrier.yoy", "carrier.premium", "sow.current", "sow.prior", "sow.delta"),
                   "Example Carrier's premium declined as its share of Marsh placements fell.",
                   "A share decline can coexist with absolute premium growth."),
        ReviewCase("premium_down_share_up", "performance", _facts(10e6, 12e6, 80e6, 120e6),
                   "Example Carrier's Marsh-placed premium fell from $12M to $10M. Its share of Marsh placements rose from 10.0% to 12.5%.",
                   ("carrier.premium", "carrier.prior", "carrier.delta", "sow.current", "sow.prior", "sow.delta"),
                   "The increase in share proves Example Carrier grew its premium.",
                   "Relative gains do not establish absolute growth."),
        ReviewCase("both_decline", "challenges", _facts(8e6, 12e6, 80e6, 100e6),
                   "Example Carrier's Marsh-placed premium fell 33.3%, while total Marsh-placed premium fell 20.0%.",
                   ("carrier.yoy", "marsh.yoy"),
                   "Example Carrier grew 33.3%, while total Marsh-placed premium grew 20.0%.",
                   "Preserve the direction of both movements."),
        ReviewCase("flat_carrier_growing_marsh", "challenges", _facts(10e6, 10e6, 100e6, 80e6),
                   "Example Carrier's Marsh-placed premium remained at $10M, while its share of Marsh placements fell from 12.5% to 10.0%.",
                   ("carrier.premium", "carrier.prior", "sow.current", "sow.prior"),
                   "Example Carrier lost premium because Marsh demand moved to competitors.",
                   "Neither an absolute loss nor its cause is supported."),
        ReviewCase("positive_results_no_forced_challenge", "challenges", _facts(20e6, 10e6, 100e6, 80e6),
                   "The supplied premium and share comparisons show no qualifying shortfall for this section.",
                   ("assessment.challenges",),
                   "Rapid growth creates a clear renewal risk for the next quarter.",
                   "Do not invent risk to fill a challenges column."),
        ReviewCase("no_future_risk_evidence", "threats", _facts(),
                   "The supplied placement comparisons are insufficient to assess emerging underwriting or renewal risks.",
                   ("assessment.threats",),
                   "There are no underwriting or renewal risks for this carrier.",
                   "Insufficient evidence is not proof that risk is absent."),
        ReviewCase("small_quarter_base", "performance", _facts(trend={
            "quarter_current": 475100, "quarter_prior": 10000, "quarter_label": "2025-Q4",
            "quarter_prior_label": "2024-Q4", "quarter_yoy": None,
            "comparison_note": "Very small prior-year quarter base; report absolute premiums."}),
                   "Example Carrier's Marsh-placed premium rose from $10K in 2024-Q4 to $475K in 2025-Q4, from a small comparison base.",
                   ("trend.quarter", "trend.comparison_note"),
                   "Quarterly growth of 4651% proves year-end pace accelerated beyond the annual run rate.",
                   "Avoid unsupported acceleration and a percentage-only small-base headline."),
        ReviewCase("seasonal_quarters", "performance", _facts(trend={
            "quarter_current": 600000, "quarter_prior": 600000, "quarter_label": "2025-Q4",
            "quarter_prior_label": "2024-Q4", "quarter_yoy": 0}),
                   "Example Carrier's Marsh-placed premium was unchanged at $600K in 2025-Q4 compared with 2024-Q4.",
                   ("trend.quarter",),
                   "The latest quarter accelerated well ahead of the annual run rate.",
                   "Compare the same quarter in consecutive years; do not infer a trajectory."),
        ReviewCase("absent_placements", "growth", _facts(segments=_segment(
            name="Manufacturing", market=5e6, carrier=0, sow=0, placement=Placement.ABSENT)),
                   "Marsh placed $5M of Manufacturing premium, with none placed with Example Carrier. Review appetite and placement access before treating this as an opportunity.",
                   ("segment.industry.absent.manufacturing",),
                   "Example Carrier can capture the full $5M of Manufacturing placements next year.",
                   "Observed absence does not establish access, appetite or achievable premium."),
        ReviewCase("below_own_placed_average", "growth", _facts(segments=_segment(
            name="Technology", market=5e6, carrier=.25e6, sow=5, placed_sow=10,
            placement=Placement.THIN)),
                   "Example Carrier received 5.0% of Marsh's Technology premium, below its 10.0% average across the segments it writes. Review whether the placement gap fits its appetite.",
                   ("segment.industry.thin.technology",),
                   "Technology trails competitors by 5.0 percentage points because the carrier's service is poor.",
                   "Its own placed average is not a competitor benchmark; service is unmeasured."),
        ReviewCase("measured_contribution", "working", _facts(movers=[
            {"name": "Property", "delta": 2e6, "current": 5e6, "prior": 3e6}]),
                   "Property contributed $2M to Example Carrier's $2M increase in Marsh-placed premium.",
                   ("mover.Property", "carrier.delta"),
                   "Property added $2M because renewal retention and pricing improved.",
                   "An arithmetic contribution does not establish operational causes."),
        ReviewCase("three_carrier_benchmark", "challenges", _facts(
            peer={"sow": 33.3333, "benchmark_count": 3, "n_carriers": 3}),
                   "Example Carrier received 12.0% of Marsh placements, compared with 33.3% on average across the three carriers in this scope.",
                   ("sow.current", "peer.sow"),
                   "Example Carrier trails the top-five peer average of 33.3%.",
                   "Use the actual comparison count and selection basis."),
        ReviewCase("benchmark_scenario", "growth", env,
                   "Example Carrier's share of Marsh's Environmental premium was 5.6 percentage points below the largest-carrier average. Review the placement gap against appetite and capacity before setting a growth target.",
                   ("peer.gap", "peer.sow", "scope.Product_Line"),
                   "Matching peers guarantees $5.6M of additional premium.",
                   "A constant-denominator scenario is not a forecast or a guaranteed result."),
        ReviewCase("above_benchmark", "working", _facts(
            peer={"sow": 10, "benchmark_count": 5, "n_carriers": 12}),
                   "Example Carrier's 12.0% share of Marsh placements exceeded the 10.0% average across the five largest carriers in this scope.",
                   ("sow.current", "peer.sow", "peer.gap"),
                   "The carrier should close its 2.0 percentage point shortfall to the benchmark.",
                   "The carrier is above the benchmark, so the gap is not a growth target."),
    )
