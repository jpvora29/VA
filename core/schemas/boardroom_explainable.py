"""Evidence-first Boardroom widgets — the explainable replacements.

Roadmap phase 1 ("Explainable Boardroom") replaces the widgets whose headline
value was an unexplained model score:

    Risks & watch items  ->  Risk & Watchlist        (premium exposed + trigger)
    Opportunity radar    ->  Product Line Headroom   (carrier vs Marsh premium)
    Market opportunity   ->  Industry Whitespace     (ranked, product-filtered)
    Insight timeline     ->  Quarterly Performance   (adjacent, complete quarters)
    Positioning matrix   ->  Product Portfolio Map   (wallet vs portfolio share,
                                                      sized by premium)
                         +   Top Carriers            (who leads the line)

Two share measures run through these models and must never be merged: share of
WALLET is outward (carrier premium / Marsh premium in scope) and share of
PORTFOLIO is inward (a line / the carrier's own premium). Both are governed
terms — see `core/definitions/terms.yaml`. Any widget that shows a product line
shows both.

Every model here follows the same two rules:

1. **Actual measures only.** Each quantity is carried twice — a `*_display`
   string exactly as it should read on screen and in PowerPoint, and a `*_value`
   float the deterministic layer can sort, threshold and total. No 0-100 scores.
2. **The model never classifies.** Priority comes from
   :mod:`core.boardroom.priority`; the extractor reports the facts those rules
   need (movement, persistence, comparability) and nothing else.

The legacy models in :mod:`core.schemas.boardroom` stay as they are: saved
conversations still render through them.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from core.llm import InputField, OutputField, Signature
from pydantic import BaseModel, Field

Tone = Literal["good", "warn", "danger", "neutral"]

PresenceStatus = Literal["no_premium", "low_presence", "established", "unknown"]

# Shared prompt text for the raw rows every widget extractor reads.
_SQL_OUTPUT_DESC = (
    "Underlying result rows keyed by lens. Each value is a compact "
    "pipe-delimited table: an optional 'constants:' line (columns identical on "
    "every row), a header row of column names, then one 'val | val | ...' line "
    "per row. Scan EVERY entry."
)


# ───────────────────────── 1. Risk & Watchlist ─────────────────────────


class WatchItem(BaseModel):
    """One evidence-backed watchlist row. Priority is computed, never written."""

    risk: str = Field(description="Short business name for the issue, e.g. 'Property premium contraction'.")
    scope: str = Field(
        default="",
        description="The business scope the issue sits in, e.g. 'Canada / Property / Chubb'.",
    )
    premium_exposed: str = Field(
        default="",
        description="Premium at stake, formatted for display, e.g. '£12.4m'. Empty when the rows do not show it.",
    )
    premium_exposed_value: Optional[float] = Field(
        default=None,
        description="The same premium as a plain number (12400000), for ranking and thresholds.",
    )
    share_of_wallet_pct: Optional[float] = Field(
        default=None, description="Carrier share of wallet in this scope, as a percentage (19.5)."
    )
    share_of_portfolio_pct: Optional[float] = Field(
        default=None,
        description=(
            "Share of PORTFOLIO: this line as a percentage of the carrier's own "
            "premium in scope (line premium / carrier total). A different "
            "denominator from share of wallet - report both, never merge them."
        ),
    )
    movement: str = Field(
        default="",
        description="The movement as it should read, e.g. '-14.2% QoQ' or '-£3.2m'.",
    )
    movement_pct: Optional[float] = Field(
        default=None,
        description="Signed percentage movement (-14.2). Null when the rows show no comparable movement.",
    )
    adverse: bool = Field(
        default=True,
        description="True when the movement is bad for the carrier (premium down, rank up, score down).",
    )
    comparison: str = Field(
        default="",
        description="The comparison basis, named explicitly, e.g. 'Q2 2026 vs Q1 2026' or 'YTD vs prior YTD'.",
    )
    trigger: str = Field(
        default="",
        description="What the data shows, in one line, e.g. 'Premium fell 14.2% between Q1 and Q2 2026'. State the fact, not a severity.",
    )
    consecutive_periods: int = Field(
        default=1,
        description="How many consecutive periods the movement has run adversely (1 = a single period).",
    )
    breached_kpi: str = Field(
        default="",
        description="A governed KPI target that has been crossed, e.g. 'Rank fell from #10 to #14'. Empty when none.",
    )
    periods_comparable: bool = Field(
        default=True,
        description="False when the periods compared are incomplete or not like-for-like — then no priority is assigned.",
    )
    owner_action: str = Field(
        default="",
        description="The expected next step, e.g. 'Review top-lost industries with the Placement team'.",
    )
    tone: Tone = Field(default="warn", description="Sentiment from the carrier's perspective.")

    # ── computed downstream by `core.boardroom.priority` — LEAVE EMPTY ──
    priority: str = Field(default="", description="LEAVE EMPTY. Assigned by the approved threshold rules.")
    priority_reason: str = Field(default="", description="LEAVE EMPTY. The rule sentence behind the label.")
    priority_tests: List[Dict[str, Any]] = Field(
        default_factory=list, description="LEAVE EMPTY. Every rule test and whether this item passed it."
    )
    priority_approved: bool = Field(
        default=False, description="LEAVE EMPTY. Whether the thresholds used are business-approved."
    )
    priority_thresholds: str = Field(
        default="", description="LEAVE EMPTY. The thresholds in force when the label was assigned."
    )


class Watchlist(BaseModel):
    """The Risk & Watchlist widget: rows of facts, plus its comparison basis."""

    items: List[WatchItem] = Field(default_factory=list, description="0-6 watch items, most material first.")
    basis: str = Field(
        default="",
        description="The comparison every item shares, e.g. 'Q2 2026 vs Q1 2026'. Empty when items name their own.",
    )
    note: str = Field(
        default="",
        description="When `items` is empty, one honest line saying why (e.g. 'No comparable prior period in the data').",
    )
    thresholds: str = Field(
        default="", description="LEAVE EMPTY. The approved thresholds, filled downstream for the 'why' drawer."
    )
    thresholds_approved: bool = Field(
        default=False, description="LEAVE EMPTY. Whether the business has signed those thresholds off."
    )


# ───────────────────── 2. Product Line Headroom ─────────────────────


class HeadroomRow(BaseModel):
    """One product line: what the carrier writes against what Marsh places."""

    product_line: str = Field(description="Product line / line of business, e.g. 'Property'.")
    carrier_premium: str = Field(default="", description="Carrier premium as displayed, e.g. '£8.2m'.")
    carrier_premium_value: Optional[float] = Field(default=None, description="Carrier premium as a number.")
    marsh_premium: str = Field(default="", description="Marsh-book premium as displayed, e.g. '£42.0m'.")
    marsh_premium_value: Optional[float] = Field(default=None, description="Marsh premium as a number.")
    share_of_wallet_pct: Optional[float] = Field(
        default=None, description="Carrier premium as a percentage of Marsh premium (19.5)."
    )
    share_of_portfolio_pct: Optional[float] = Field(
        default=None,
        description=(
            "Share of PORTFOLIO: this line as a percentage of the carrier's own "
            "premium in scope (line premium / carrier total). A different "
            "denominator from share of wallet - report both, never merge them."
        ),
    )
    whitespace_premium: str = Field(
        default="", description="Marsh premium not written by the carrier, as displayed, e.g. '£33.8m'."
    )
    whitespace_premium_value: Optional[float] = Field(default=None, description="Whitespace premium as a number.")
    market_change: str = Field(
        default="",
        description="Market movement WITH its basis, e.g. '+6.4% QoQ'. Empty when no comparable period exists.",
    )
    status: PresenceStatus = Field(
        default="unknown",
        description="'no_premium' when the carrier writes nothing here, 'low_presence' when it is small, 'established' otherwise.",
    )
    focus: str = Field(default="", description="One-line suggested focus, e.g. 'Expand in Manufacturing'.")


class ProductLineHeadroom(BaseModel):
    """The Product Line Headroom widget — ranked by whitespace premium."""

    rows: List[HeadroomRow] = Field(default_factory=list, description="One row per product line, biggest whitespace first.")
    definition: str = Field(
        default="Whitespace premium = Marsh premium - carrier premium (floored at zero).",
        description="The approved whitespace definition actually used, shown to the user.",
    )
    basis: str = Field(default="", description="The period the figures cover, e.g. 'Q2 2026'.")
    note: str = Field(default="", description="Honest explanation when the widget cannot be filled.")


# ───────────────────── 3. Industry Whitespace ─────────────────────


class WhitespaceRow(BaseModel):
    """One industry where Marsh places premium the carrier does not write."""

    industry: str = Field(description="Industry / sector name, e.g. 'Manufacturing'.")
    product_line: str = Field(
        default="",
        description="The product line this row belongs to — the widget is always filtered by one.",
    )
    marsh_premium: str = Field(default="", description="Marsh premium in the industry, displayed.")
    marsh_premium_value: Optional[float] = Field(default=None, description="Marsh premium as a number.")
    carrier_premium: str = Field(default="", description="Carrier premium in the industry, displayed.")
    carrier_premium_value: Optional[float] = Field(default=None, description="Carrier premium as a number.")
    share_of_wallet_pct: Optional[float] = Field(default=None, description="Carrier share of wallet (0.0 when none).")
    share_of_portfolio_pct: Optional[float] = Field(
        default=None,
        description=(
            "Share of PORTFOLIO: this line as a percentage of the carrier's own "
            "premium in scope (line premium / carrier total). A different "
            "denominator from share of wallet - report both, never merge them."
        ),
    )
    peer_share_of_wallet_pct: Optional[float] = Field(
        default=None,
        description=(
            "What the PEER SET holds of the wallet in this industry, as a percentage. "
            "Shows whether the whitespace is unwritten or simply written by someone else."
        ),
    )
    focus_reason: str = Field(
        default="",
        description=(
            "Why this industry is (or is not) where to focus, in one line grounded in the "
            "figures, e.g. 'Largest unwritten premium and the fastest-growing industry'."
        ),
    )
    whitespace_premium: str = Field(default="", description="Marsh premium the carrier does not hold, displayed.")
    whitespace_premium_value: Optional[float] = Field(default=None, description="Whitespace premium as a number.")
    marsh_change: str = Field(default="", description="Marsh movement with its basis, e.g. '+8.2% QoQ'.")
    status: PresenceStatus = Field(default="unknown", description="'no_premium' / 'low_presence' / 'established'.")


class IndustryWhitespace(BaseModel):
    """The Industry Whitespace widget — ranked bars, filtered by product line."""

    rows: List[WhitespaceRow] = Field(default_factory=list, description="Industries, biggest whitespace first.")
    product_line: str = Field(
        default="",
        description="The product line in focus — required, because the widget ranks industries WITHIN a product.",
    )
    product_lines: List[str] = Field(
        default_factory=list,
        description="Every product line present in the rows, so the user can switch the filter.",
    )
    definition: str = Field(
        default="An industry qualifies when Marsh premium is material and carrier premium is zero or low.",
        description="The approved whitespace definition actually used, shown behind 'How whitespace is calculated'.",
    )
    basis: str = Field(default="", description="The period the figures cover.")
    note: str = Field(default="", description="Honest explanation when the widget cannot be filled.")


# ───────────────────── 4. Quarterly Performance ─────────────────────


class QuarterRow(BaseModel):
    """One quarter, compared with the quarter immediately before it."""

    quarter: str = Field(description="Quarter label, e.g. 'Q2 2026'.")
    premium: str = Field(default="", description="Actual premium in the quarter, displayed, e.g. '£19.2m'.")
    premium_value: Optional[float] = Field(default=None, description="Premium as a number.")
    change_currency: str = Field(default="", description="Change against the prior quarter in money, e.g. '-£3.2m'.")
    change_pct: Optional[float] = Field(default=None, description="Signed percentage change against the prior quarter.")
    share_of_wallet_pct: Optional[float] = Field(default=None, description="Share of wallet in the quarter.")
    rank_change: str = Field(default="", description="Rank movement when the rows carry rank, e.g. '#12 -> #14'.")
    driver: str = Field(default="", description="The main product or industry behind the movement.")
    complete: bool = Field(
        default=True, description="False when the quarter is partial — it is then shown but never compared."
    )


class QuarterlyPerformance(BaseModel):
    """The Quarterly Performance widget — adjacent, comparable quarters only."""

    rows: List[QuarterRow] = Field(
        default_factory=list, description="Up to 8 quarters in chronological order, oldest first."
    )
    basis: str = Field(default="QoQ", description="The comparison basis: 'QoQ', 'YTD vs prior YTD' or 'Annual'.")
    note: str = Field(default="", description="Honest explanation when quarters are unavailable or not comparable.")


# ───────────────── 5. Product portfolio map (bubbles) ─────────────────


class PortfolioBubble(BaseModel):
    """One product line, plotted on the two share measures with premium as size.

    The two axes answer different questions and have different denominators:
    share of WALLET is outward ("how much of Marsh's placement in this line does
    the carrier win"), share of PORTFOLIO is inward ("how much of the carrier's
    own book sits in this line"). They are never merged into one "share".
    """

    product_line: str = Field(description="Product line / line of business, e.g. 'Property'.")
    share_of_wallet_pct: Optional[float] = Field(
        default=None, description="X axis: carrier premium / Marsh premium in this line, as a percentage."
    )
    share_of_portfolio_pct: Optional[float] = Field(
        default=None, description="Y axis: this line / the carrier's total premium in scope, as a percentage."
    )
    premium: str = Field(default="", description="Carrier premium in this line, displayed — the bubble's size.")
    premium_value: Optional[float] = Field(default=None, description="The same premium as a number.")
    marsh_premium: str = Field(default="", description="Marsh premium in this line, displayed.")
    marsh_premium_value: Optional[float] = Field(default=None, description="Marsh premium as a number.")
    growth: str = Field(
        default="",
        description="Growth WITH its basis, e.g. '+12.4% YoY'. Empty when no comparable period exists.",
    )
    growth_pct: Optional[float] = Field(default=None, description="Signed growth percentage.")
    peer_share_of_wallet_pct: Optional[float] = Field(
        default=None, description="What the peer set holds of the wallet in this line, as a percentage."
    )
    tone: Tone = Field(default="neutral")


class ProductPortfolioMap(BaseModel):
    """Share of wallet against share of portfolio, one bubble per product line."""

    bubbles: List[PortfolioBubble] = Field(default_factory=list, description="One per product line, 2-12.")
    wallet_benchmark_pct: Optional[float] = Field(
        default=None,
        description="Vertical line: the carrier's overall share of wallet in scope, or the peer average.",
    )
    portfolio_benchmark_pct: Optional[float] = Field(
        default=None,
        description=(
            "Horizontal line: how the MARSH BOOK is split across the same lines, so a bubble "
            "above it is a line the carrier is over-weight in versus the market."
        ),
    )
    benchmark_label: str = Field(
        default="Carrier average / market mix",
        description="What the two benchmark lines represent, in one short phrase.",
    )
    basis: str = Field(default="", description="The period the figures cover, e.g. 'Q2 2026'.")
    note: str = Field(default="", description="One-line read of the map, or why it cannot be built.")


# ───────────────── 6. Top carriers in the line ─────────────────


class CarrierStanding(BaseModel):
    """One carrier's standing in the Marsh book for this scope.

    Peer identities arrive already anonymised ('Peer 1', 'Peer 2') from the
    evidence boundary. Report the label exactly as the rows give it — never try
    to work out or restore who a peer is.
    """

    carrier: str = Field(description="The carrier as the rows name it — the subject, or 'Peer 1'.")
    is_subject: bool = Field(default=False, description="True for the carrier the question is about.")
    rank: Optional[int] = Field(default=None, description="Position by premium within the Marsh book.")
    premium: str = Field(default="", description="Premium as displayed.")
    premium_value: Optional[float] = Field(default=None, description="Premium as a number.")
    share_of_wallet_pct: Optional[float] = Field(default=None, description="Share of wallet, as a percentage.")
    movement: str = Field(default="", description="Movement WITH its basis, e.g. '+8.1% YoY'.")
    movement_pct: Optional[float] = Field(default=None, description="Signed movement percentage.")


class TopCarriers(BaseModel):
    """Who leads this line in the Marsh book, and how they are moving."""

    carriers: List[CarrierStanding] = Field(
        default_factory=list, description="Ranked by premium, highest first. Up to 8."
    )
    field_size: Optional[int] = Field(
        default=None,
        description="How many carriers Marsh placed with in this scope — a rank is meaningless without it.",
    )
    scope: str = Field(default="", description="The line and market this ranking covers, e.g. 'Canada / Property'.")
    basis: str = Field(default="", description="The period, and the movement basis when one is shown.")
    note: str = Field(default="", description="Honest explanation when the ranking cannot be built.")


# ───────────────── 7. Actual-measure positioning (retired) ─────────────────


class PositionPoint(BaseModel):
    """One carrier plotted on real axes — no normalisation."""

    label: str = Field(description="Carrier name, or 'Peer average' for the aggregated peer set.")
    x_value: Optional[float] = Field(default=None, description="Actual x measure (share of wallet % or premium).")
    x_display: str = Field(default="", description="The x measure as it should read, e.g. '19.5%' or '£8.2m'.")
    y_value: Optional[float] = Field(default=None, description="Actual y measure (broker survey score).")
    y_display: str = Field(default="", description="The y measure as it should read, e.g. '7.4'.")
    is_subject: bool = Field(default=False, description="True for the carrier in focus.")
    tone: Tone = Field(default="neutral")


class ActualPositioning(BaseModel):
    """Positioning on actual measures, with named benchmark lines."""

    points: List[PositionPoint] = Field(default_factory=list, description="2-8 plotted carriers.")
    x_label: str = Field(default="Share of wallet", description="What the x axis actually measures.")
    x_unit: str = Field(default="%", description="Unit for the x axis: '%', '£m', 'score' …")
    y_label: str = Field(default="Broker score", description="What the y axis actually measures.")
    y_unit: str = Field(default="", description="Unit for the y axis.")
    x_benchmark: Optional[float] = Field(default=None, description="Peer-average or target x, drawn as a vertical line.")
    y_benchmark: Optional[float] = Field(default=None, description="Peer-average or target y, drawn as a horizontal line.")
    benchmark_label: str = Field(default="Peer average", description="What the benchmark lines represent.")
    note: str = Field(default="", description="One-line read of the positioning.")


# ───────────────────────────── signatures ─────────────────────────────


class BoardroomWatchlistSignature(Signature):
    """
    Build the Risk & Watchlist for a boardroom dashboard.

    One row per issue the analysis genuinely surfaces. Each row must answer:
    what the issue is, the business scope it sits in, how much premium is
    exposed, how far the measure moved, WHICH periods were compared, and what
    the data shows (the trigger).

    NEVER write a severity, priority, or 'High/Med/Low' anywhere. Priority is
    computed downstream from approved business thresholds using the facts you
    report — so instead report them faithfully: `premium_exposed_value`,
    `movement_pct` with its sign, `consecutive_periods`, any `breached_kpi`, and
    `periods_comparable` (set it FALSE when the periods compared are partial or
    not like-for-like).

    Name the comparison explicitly ('Q2 2026 vs Q1 2026', 'YTD vs prior YTD').
    Never write an unspecified change. Peers stay aggregated.
    Use ONLY figures present in the commentary or rows. Leave a field empty (or
    the whole list empty) rather than estimating, normalising or inventing a
    number. An honest empty widget is correct when the data cannot support it.
    """

    user_query: str = InputField(desc="The user's original question.")
    commentary: str = InputField(desc="The finished written analysis.")
    sql_output: Any = InputField(desc=_SQL_OUTPUT_DESC)
    watchlist: Watchlist = OutputField(
        desc="Evidence-backed watch items; empty with a `note` when nothing comparable exists."
    )


class BoardroomHeadroomSignature(Signature):
    """
    Build Product Line Headroom for a boardroom dashboard.

    One row per product line showing the carrier's premium, the Marsh-book
    premium, share of wallet, and the whitespace between them in CURRENCY —
    never an opportunity score. Rank by whitespace premium, descending.

    Whitespace premium = max(Marsh premium - carrier premium, 0), unless the
    rows state a different approved definition — in which case use theirs and
    say so in `definition`.

    Mark a product line the carrier does not write as `status='no_premium'`,
    never as a high score. Always give `market_change` its basis ('+6.4% QoQ');
    leave it empty when no comparable period exists.

    Every product row must ALSO carry `share_of_portfolio_pct` - that line as a
    percentage of the carrier's OWN premium in scope. Share of wallet says how
    much of Marsh's placement the carrier wins; share of portfolio says how much
    of the carrier's book sits there. A product line without its portfolio share
    is missing half the picture.
    Use ONLY figures present in the commentary or rows. Leave a field empty (or
    the whole list empty) rather than estimating, normalising or inventing a
    number. An honest empty widget is correct when the data cannot support it.
    """

    user_query: str = InputField(desc="The user's original question.")
    commentary: str = InputField(desc="The finished written analysis.")
    sql_output: Any = InputField(desc=_SQL_OUTPUT_DESC)
    headroom: ProductLineHeadroom = OutputField(
        desc="Ranked product-line headroom; empty rows with a `note` when premium is not split by product."
    )


class BoardroomWhitespaceSignature(Signature):
    """
    Build Industry Whitespace for a boardroom dashboard.

    Rank the industries where Marsh places material premium but the selected
    carrier writes zero or very little, WITHIN one product line. Set
    `product_line` to the product the question is about (or the product with the
    most premium in the rows) and list every product line you saw in
    `product_lines`.

    Report Marsh premium, carrier premium, share of wallet, share of portfolio
    and whitespace premium for every row, and set `status` to 'no_premium' when
    the carrier writes nothing and 'low_presence' when it writes very little.
    Never output an intensity or a 0-100 score.

    Where the rows show it, also set `peer_share_of_wallet_pct`: whether the
    premium the carrier does not write is unplaced or simply written by the peer
    set changes what to do about it. Use `focus_reason` to say, in one grounded
    line, why this industry is or is not the place to focus - size of the
    unwritten premium, its growth, and how contested it is.
    Use ONLY figures present in the commentary or rows. Leave a field empty (or
    the whole list empty) rather than estimating, normalising or inventing a
    number. An honest empty widget is correct when the data cannot support it.
    """

    user_query: str = InputField(desc="The user's original question.")
    commentary: str = InputField(desc="The finished written analysis.")
    sql_output: Any = InputField(desc=_SQL_OUTPUT_DESC)
    whitespace: IndustryWhitespace = OutputField(
        desc="Ranked industry whitespace for one product line; empty rows with a `note` when industries are absent."
    )


class BoardroomQuarterlySignature(Signature):
    """
    Build Quarterly Performance for a boardroom dashboard.

    One row per quarter, in chronological order, with the actual premium, the
    change against the IMMEDIATELY PRECEDING quarter in both currency and
    percentage, share of wallet where present, any rank movement, and the main
    product or industry driver.

    Hard rules:
    - Compare adjacent quarters only, and only complete ones. Mark a partial
      quarter `complete=false` and leave its change fields empty.
    - Use at most the latest 8 quarters.
    - Never mix an annual survey score into a quarterly premium row.
    - If the rows carry no comparable quarters, return no rows and explain why
      in `note`; set `basis` to 'YTD vs prior YTD' or 'Annual' only if THAT
      comparison is genuinely available in the rows.
    Use ONLY figures present in the commentary or rows. Leave a field empty (or
    the whole list empty) rather than estimating, normalising or inventing a
    number. An honest empty widget is correct when the data cannot support it.
    """

    user_query: str = InputField(desc="The user's original question.")
    commentary: str = InputField(desc="The finished written analysis.")
    sql_output: Any = InputField(desc=_SQL_OUTPUT_DESC)
    quarterly: QuarterlyPerformance = OutputField(
        desc="Comparable quarters; empty rows with a `note` when quarterly history is unavailable."
    )


class BoardroomPortfolioMapSignature(Signature):
    """
    Build the Product Portfolio Map for a boardroom dashboard: one bubble per
    product line, plotted on two DIFFERENT share measures.

    - x = share of WALLET: carrier premium / Marsh premium in that line, percent.
      It says how much of Marsh's placement in the line the carrier wins.
    - y = share of PORTFOLIO: that line / the carrier's OWN total premium in
      scope, percent. It says how the carrier's book is distributed.
    - bubble size = the carrier's premium in the line, in currency.

    The two are never merged into one "share": they have different denominators,
    and a reader cannot tell them apart from the number alone. Report both, and
    the premium, for every line.

    Set `wallet_benchmark_pct` to the carrier's overall share of wallet in scope
    (or the peer average when the rows carry it), and `portfolio_benchmark_pct`
    to how the MARSH BOOK is split across the same lines, so a line above it is
    one the carrier is over-weight in. Add growth WITH its basis where the rows
    support it.

    Use ONLY figures present in the commentary or rows. Leave a field empty (or
    the whole list empty) rather than estimating, normalising or inventing a
    number. An honest empty widget is correct when the data cannot support it.
    """

    user_query: str = InputField(desc="The user's original question.")
    commentary: str = InputField(desc="The finished written analysis.")
    sql_output: Any = InputField(desc=_SQL_OUTPUT_DESC)
    portfolio_map: ProductPortfolioMap = OutputField(
        desc="One bubble per product line; empty with a `note` when premium is not split by product."
    )


class BoardroomTopCarriersSignature(Signature):
    """
    Build the Top Carriers standing for a boardroom dashboard: who leads this
    scope in the Marsh book, their premium, share of wallet, and how each is
    moving (with the basis named).

    Rank by premium, highest first, and always set `field_size` — "#5" alone is
    meaningless, "#5 of 12" is a finding. Mark the carrier the question is about
    with `is_subject`.

    Peer identities in the rows are ALREADY anonymised ('Peer 1', 'Peer 2').
    Copy those labels exactly. Never guess, infer, or restore a peer's real name,
    and never describe a peer in a way that would identify it.

    Use ONLY figures present in the commentary or rows. Leave a field empty (or
    the whole list empty) rather than estimating, normalising or inventing a
    number. An honest empty widget is correct when the data cannot support it.
    """

    user_query: str = InputField(desc="The user's original question.")
    commentary: str = InputField(desc="The finished written analysis.")
    sql_output: Any = InputField(desc=_SQL_OUTPUT_DESC)
    top_carriers: TopCarriers = OutputField(
        desc="The ranked standing; empty with a `note` when the rows carry no carrier comparison."
    )


class BoardroomPositioningActualsSignature(Signature):
    """
    RETIRED - kept so saved boards still open. Share of wallet against a broker
    survey score compared two unrelated things on one plot; the Product
    Portfolio Map (share of wallet against share of portfolio, sized by premium)
    replaced it. New digests never request this widget.

    Build actual-measure positioning for a boardroom dashboard.

    Plot each carrier on REAL measures: x is actual share of wallet (percent) or
    actual premium, y is the actual broker survey score. Do NOT rescale anything
    to 0-100 — the chart adapts its axes to the real units, and `x_label`,
    `x_unit`, `y_label`, `y_unit` tell it what they are.

    Set `x_benchmark` / `y_benchmark` to the peer average (or the agreed target)
    when the rows carry it, and say what they represent in `benchmark_label`.
    Individual peers stay aggregated: plot 'Peer average' as ONE point.
    Use ONLY figures present in the commentary or rows. Leave a field empty (or
    the whole list empty) rather than estimating, normalising or inventing a
    number. An honest empty widget is correct when the data cannot support it.
    """

    user_query: str = InputField(desc="The user's original question.")
    commentary: str = InputField(desc="The finished written analysis.")
    sql_output: Any = InputField(desc=_SQL_OUTPUT_DESC)
    positioning_actual: ActualPositioning = OutputField(
        desc="Positioning on actual measures; empty points when a real measure is missing."
    )
