"""Calculated product-line growth insights. No model or database dependencies.

Totals describe only the returned, comparable cuts. Missing periods are never
zero-filled; rates, scores, peer averages and overlapping lenses are not summed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
import re

from core.answers.claims import AnswerClaim, change_claim, compile_claims, context, period_key, period_order
from core.answers.facts import AnswerFact, FactPack, format_value, is_period_column, stable_id


PRODUCT_COLUMNS = {"product", "product_line", "productline", "line_of_business", "lob"}
PREMIUM_COLUMNS = {"premium", "marsh_premium", "marsh_placed_premium"}
TOTAL_LABELS = {"all", "total", "overall", "grand total", "all products", "all product lines"}

# Words that make a question explicitly about MOVEMENT. Once the trigger for the
# whole decomposition below; now it gates one claim only — see the note there.
MOVEMENT_WORDS = re.compile(r"growth|grow|change|declin|increas|trend|driver", re.I)


def asks_about_movement(question: str) -> bool:
    """Whether the question itself names a movement.

    This used to decide whether the reader got a decomposition at all, and that
    was the wrong question to ask. "How is Chubb performing?" and "Show Chubb's
    premium growth" are the same request over the same rows, and only the second
    one matched, so the first got four bare year-on-year lines and none of the
    drivers, offsets, breadth, mix or concentration underneath them. What a
    decomposition needs is two periods and a slice to cut by — a property of the
    EVIDENCE, which `growth_groups` already checks — not a verb in the prompt.

    An empty question is not a question that failed to mention movement: record
    verification replays the compiler with no question text, so gating there
    would withhold a claim the stored answer contains and fail every record.
    """
    return not question or bool(MOVEMENT_WORDS.search(question))


@dataclass(frozen=True)
class ProductChange:
    name: str
    prior: AnswerFact
    current: AnswerFact

    @property
    def delta(self) -> float:
        return self.current.value - self.prior.value


@dataclass(frozen=True)
class GrowthGroup:
    facts: tuple[AnswerFact, ...]
    changes: tuple[ProductChange, ...]
    missing: int = 0

    @property
    def prior_total(self) -> float:
        return sum(p.prior.value for p in self.changes)

    @property
    def current_total(self) -> float:
        return sum(p.current.value for p in self.changes)


def common_dimensions(facts: tuple[AnswerFact, ...]) -> tuple[tuple[str, str], ...]:
    if not facts:
        return ()
    common = set(facts[0].dimensions)
    for fact in facts[1:]:
        common.intersection_update(fact.dimensions)
    return tuple(sorted(common))


def growth_groups(pack: FactPack, *, combine_sources: bool = False) -> tuple[GrowthGroup, ...]:
    grouped = defaultdict(list)
    for fact in pack.facts:
        if fact.unit != "currency" or fact.metric.lower() not in PREMIUM_COLUMNS:
            continue
        product = next((v for k, v in fact.dimensions if k.lower() in PRODUCT_COLUMNS), None)
        if not product or not period_key(fact) or not all(period_order(fact)):
            continue
        base = tuple((k, v) for k, v in fact.dimensions
                     if not is_period_column(k) and k.lower() not in PRODUCT_COLUMNS)
        # The recorded metric, lens, non-period scope and cutoff identify a
        # comparison. A different SQL/tool call is not itself a different book.
        # Keep unscoped results isolated because their population is unknown.
        source = None if combine_sources and base else fact.source_id
        grouped[(fact.metric, fact.unit, fact.lens, source, base)].append((product, fact))
    groups = []
    for entries in grouped.values():
        periods = sorted({period_order(f) for _, f in entries})
        if len(periods) < 2:
            continue
        before, after = periods[-2:]
        pairs = defaultdict(dict)
        relevant = []
        ambiguous = False
        for product, fact in entries:
            period = period_order(fact)
            if period not in {before, after}:
                continue
            previous = pairs[product].get(period)
            if combine_sources and previous and previous.value == fact.value and previous.dimensions == fact.dimensions:
                continue
            if previous or product.strip().lower() in TOTAL_LABELS:
                ambiguous = True
            pairs[product][period] = fact
            relevant.append(fact)
        if ambiguous or len(pairs) < 2:
            continue
        changes = tuple(ProductChange(name, values[before], values[after])
                        for name, values in sorted(pairs.items()) if before in values and after in values)
        groups.append(GrowthGroup(tuple(relevant), changes, len(pairs) - len(changes)))
    return tuple(groups)


def insight(group: GrowthGroup, kind: str, text: str, formula: str, priority: float) -> AnswerClaim:
    ids = tuple(sorted(f.id for f in group.facts))
    scope = context(replace(group.facts[0], dimensions=common_dimensions(group.facts)), omit_period=True)
    text += f" ({scope})." if scope else "."
    return AnswerClaim(stable_id("c_", [ids, kind]), text, ids, kind, formula, priority)


def portfolio_change(group: GrowthGroup) -> AnswerClaim:
    first = group.changes[0]
    base = common_dimensions(group.facts)
    prior = replace(first.prior, dimensions=base + period_key(first.prior),
                    value=group.prior_total, rendered=format_value(group.prior_total, "currency"))
    current = replace(first.current, dimensions=base + period_key(first.current),
                      value=group.current_total, rendered=format_value(group.current_total, "currency"))
    sentence = change_claim(prior, current, "")
    suffix = f" ({context(current, omit_period=True)})."
    text = sentence.text.removesuffix(suffix).removesuffix(".")
    text += f" across the {len(group.changes)} comparable product lines returned"
    formula = ("Prior total = " + " + ".join(f"{p.prior.value:g}" for p in group.changes)
               + "; current total = " + " + ".join(f"{p.current.value:g}" for p in group.changes)
               + "; " + sentence.formula)
    return insight(group, "portfolio_change", text, formula, 50)


def growth_driver(group: GrowthGroup, *, explain: bool = False) -> AnswerClaim | None:
    positive = [p for p in group.changes if p.delta > 0]
    if not positive:
        return None
    leader = sorted(positive, key=lambda p: (-p.delta, p.name))[0]
    gains = sum(p.delta for p in positive)
    text = f"{leader.name} was the largest growth contributor, adding {format_value(leader.delta, 'currency')}"
    if leader.prior.value > 0:
        text += f" ({format_value(leader.delta / leader.prior.value * 100, 'percent')} growth)"
    text += f" and accounting for {format_value(leader.delta / gains * 100, 'percent')} of the gross increases"
    formula = (f"{leader.current.value:g} - {leader.prior.value:g} = {leader.delta:g}; "
               f"gross increases = {gains:g}; contribution = {leader.delta:g} / {gains:g} × 100")
    if leader.prior.value > 0:
        formula += f"; growth = {leader.delta:g} / {leader.prior.value:g} × 100"
    if explain and group.prior_total > 0:
        contribution = leader.delta / group.prior_total * 100
        text += (f". Its increase contributed {format_value(contribution, 'percentage_points')} "
                 "to the combined growth rate")
        formula += f"; contribution to growth = {leader.delta:g} / {group.prior_total:g} × 100"
    return replace(insight(group, "growth_driver", text, formula, 40),
                   focus_ids=(leader.prior.id, leader.current.id))


def growth_offset(group: GrowthGroup, *, explain: bool = False) -> AnswerClaim | None:
    negative = [p for p in group.changes if p.delta < 0]
    if not negative:
        return None
    laggard = sorted(negative, key=lambda p: (p.delta, p.name))[0]
    gains = sum(max(0, p.delta) for p in group.changes)
    losses = -sum(p.delta for p in negative)
    text = f"{laggard.name} had the largest decline, down {format_value(-laggard.delta, 'currency')}"
    if laggard.prior.value > 0:
        text += f" ({format_value(-laggard.delta / laggard.prior.value * 100, 'percent')})"
    if gains:
        text += (f"; declines totalled {format_value(losses, 'currency')}, offsetting "
                 f"{format_value(losses / gains * 100, 'percent')} of the gross increases")
    formula = (f"{laggard.current.value:g} - {laggard.prior.value:g} = {laggard.delta:g}; "
               f"gross declines = {losses:g}; gross increases = {gains:g}")
    if gains:
        formula += f"; offset = {losses:g} / {gains:g} × 100"
    if laggard.prior.value > 0:
        formula += f"; decline = {-laggard.delta:g} / {laggard.prior.value:g} × 100"
    if explain and group.prior_total > 0:
        drag = losses / group.prior_total * 100
        text += (f". Together, the declining lines reduced the combined growth rate by "
                 f"{format_value(drag, 'percentage_points')}")
        formula += f"; drag on growth = {losses:g} / {group.prior_total:g} × 100"
    return replace(insight(group, "growth_offset", text, formula, 39),
                   focus_ids=(laggard.prior.id, laggard.current.id))


def growth_breadth(group: GrowthGroup, *, explain: bool = False) -> AnswerClaim:
    up = sum(p.delta > 0 for p in group.changes)
    down = sum(p.delta < 0 for p in group.changes)
    flat = len(group.changes) - up - down
    text = f"{up} of the {len(group.changes)} comparable product lines grew, {down} declined and {flat} were unchanged"
    return insight(group, "growth_breadth", text,
                   f"Count current - prior > 0: {up}; < 0: {down}; = 0: {flat}", 38)


def premium_mix(group: GrowthGroup, *, explain: bool = False) -> AnswerClaim | None:
    if group.current_total <= 0 or group.prior_total <= 0:
        return None
    if any(min(p.current.value, p.prior.value) < 0 for p in group.changes):
        return None
    leader = sorted(group.changes, key=lambda p: (-p.current.value, p.name))[0]
    current_share = leader.current.value / group.current_total * 100
    prior_share = leader.prior.value / group.prior_total * 100
    text = (f"{leader.name} was the largest returned product line at {leader.current.rendered}, "
            f"representing {format_value(current_share, 'percent')} of current premium versus "
            f"{format_value(prior_share, 'percent')} previously")
    formula = (f"{leader.current.value:g} / {group.current_total:g} × 100 = {current_share:g}%; "
               f"{leader.prior.value:g} / {group.prior_total:g} × 100 = {prior_share:g}%")
    if explain and current_share != prior_share:
        shift = abs(current_share - prior_share)
        direction = "more" if current_share > prior_share else "less"
        text += (f". The premium mix became {direction} concentrated in this line, "
                 f"with its weight {'rising' if direction == 'more' else 'falling'} "
                 f"by {format_value(shift, 'percentage_points')}")
        formula += f"; mix shift = {current_share:g} - {prior_share:g}"
    return insight(group, "premium_mix", text, formula, 37)


def growth_resilience(group: GrowthGroup) -> AnswerClaim | None:
    positive = sorted((p for p in group.changes if p.delta > 0), key=lambda p: (-p.delta, p.name))
    if not positive or len(group.changes) < 3:
        return None
    leader = positive[0]
    prior = group.prior_total - leader.prior.value
    current = group.current_total - leader.current.value
    delta = current - prior
    direction = "grew" if delta > 0 else "declined" if delta < 0 else "were unchanged"
    text = (f"Excluding {leader.name}, the remaining product lines {direction} "
            f"from {format_value(prior, 'currency')} to {format_value(current, 'currency')}")
    formula = (f"Prior excluding leader = {group.prior_total:g} - {leader.prior.value:g} = {prior:g}; "
               f"current excluding leader = {group.current_total:g} - {leader.current.value:g} = {current:g}")
    if prior > 0 and delta:
        text += f" ({format_value(abs(delta / prior * 100), 'percent')})"
        formula += f"; growth excluding leader = ({current:g} - {prior:g}) / {prior:g} × 100"
    if group.current_total > group.prior_total:
        text += (". Growth therefore extended beyond the largest contributor" if delta > 0 else
                 ". The combined increase depended on the largest contributor overcoming weakness elsewhere" if delta < 0 else
                 ". The largest contributor accounted for the entire net increase")
    return insight(group, "growth_resilience", text, formula, 36)


def growth_concentration(group: GrowthGroup) -> AnswerClaim | None:
    positive = sorted((p for p in group.changes if p.delta > 0), key=lambda p: (-p.delta, p.name))
    if len(positive) < 3:
        return None
    first, second = positive[:2]
    combined = first.delta + second.delta
    gains = sum(p.delta for p in positive)
    text = (f"{first.name} and {second.name} together added {format_value(combined, 'currency')}, "
            f"accounting for {format_value(combined / gains * 100, 'percent')} of gross increases. "
            "This measures how concentrated the gains were before declines in other lines")
    formula = (f"Top two gains = {first.delta:g} + {second.delta:g} = {combined:g}; "
               f"gross increases = {gains:g}; contribution = {combined:g} / {gains:g} × 100")
    return insight(group, "growth_concentration", text, formula, 35)


def growth_details(group: GrowthGroup) -> tuple[AnswerClaim, ...]:
    return tuple(claim for build in (growth_resilience, growth_concentration)
                 if (claim := build(group)) is not None)


def compile_answer_claims(pack: FactPack, question: str, *, legacy: bool = False) -> tuple[AnswerClaim, ...]:
    # Exact duplicate evidence must not make the period pairing ambiguous.
    unique = {}
    for fact in pack.facts:
        unique.setdefault((fact.metric, fact.unit, fact.lens, fact.dimensions, fact.value), fact)
    comparison_pack = pack if legacy else FactPack(tuple(unique.values()), pack.row_count, pack.conflicts)
    claims = list(compile_claims(comparison_pack, question))
    # The period comparison already explains these tool rates. Listing the
    # same percentage again as a standalone observation adds no insight.
    expanded_rates = {f.id for f in pack.facts if f.metric.startswith("YoY_%")
                      and f.support and f.support[0].get("measure_name")
                      and f.support[0].get("prior_year") is not None}
    claims = [c for c in claims if not set(c.fact_ids) & expanded_rates]
    if not legacy:
        # Perception has its own decomposition — see `core.answers.survey`. Kept
        # out of the legacy path so version 2 records still reproduce.
        from core.answers.survey import compile_survey_claims
        claims.extend(compile_survey_claims(pack, question))
    movement = asks_about_movement(question)
    # Version 2 records reproduce the old wording gate exactly, or they stop
    # verifying. Everything written since is gated on the EVIDENCE instead.
    if legacy and not movement:
        return tuple(claims)
    # "I cannot compute growth" answers a QUESTION about growth. Telling someone
    # who did not ask about movement that a movement cannot be computed is noise,
    # so this one claim stays gated on the wording.
    if movement and not any(c.kind == "change" for c in claims) and pack.facts:
        ids = tuple(sorted(f.id for f in pack.facts))
        claims.append(AnswerClaim(stable_id("c_", [ids, "comparison_coverage"]),
            "The returned evidence does not identify both comparison periods, so I cannot calculate a full growth breakdown.",
            ids, "comparison_coverage", "A growth comparison requires the same metric and cut in two identified periods.", 45))
    for group in growth_groups(pack, combine_sources=not legacy):
        if group.missing:
            total = len(group.changes) + group.missing
            claims.append(insight(group, "growth_coverage",
                f"Only {len(group.changes)} of the {total} returned product lines have both periods; "
                "a complete growth breakdown cannot be calculated",
                f"{len(group.changes)} comparable + {group.missing} missing a period = {total}", 49))
            continue
        claims.append(portfolio_change(group))
        for build in (growth_driver, growth_offset, growth_breadth, premium_mix):
            claim = build(group, explain=not legacy)
            if claim is not None:
                claims.append(claim)
        if not legacy:
            claims.extend(growth_details(group))
    return tuple(sorted(claims, key=lambda c: (-c.priority, c.id)))
