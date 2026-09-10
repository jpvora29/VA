"""Recover named comparison inputs already returned by deterministic tools.

This does not run another query or guess a prior period/measure. SQL and uploaded
data tools carry those names with the operands, including the partial-year cutoff.
"""
from __future__ import annotations

from dataclasses import replace
import math

from core.answers.facts import FactPack, build_fact_pack, facts_for_set, number, stable_id


def comparison_facts(item: dict) -> tuple[list, list[str]]:
    expanded, conflicts = [], []
    for raw in item.get("facts") or []:
        if raw.get("name") not in {"yoy", "yoy_to_date"}:
            continue
        support = raw.get("support") or []
        if len(support) != 1:
            continue
        row = support[0]
        metric = row.get("measure_name")
        prior_year, year = number(row.get("prior_year")), number(row.get("yr"))
        prior, current = number(row.get("prev")), number(row.get("measure"))
        if not metric or None in (prior_year, year, prior, current) or prior == 0:
            continue
        expected = round((current - prior) / prior * 100, 1)
        value = number(raw.get("value"))
        if value is None or not math.isclose(value, expected, abs_tol=1e-8):
            conflicts.append("Comparison operands disagree with the reported growth")
            continue
        for period, operand in ((prior_year, prior), (year, current)):
            dims = dict(raw.get("dims") or {})
            dims["year"] = str(int(period)) if period.is_integer() else str(period)
            expanded.append({"name": "period_series", "column": metric, "unit": metric,
                "dims": dims, "value": operand, "support": support,
                "formula": f"Recorded {metric} input to {raw['name']} for {dims['year']}"})
    return facts_for_set(dict(item, facts=expanded, rows=[])) if expanded else [], conflicts


def build_answer_fact_pack(evidence) -> FactPack:
    pack = build_fact_pack(evidence)
    candidates, conflicts = list(pack.facts), list(pack.conflicts)
    for item in evidence:
        inputs, errors = comparison_facts(item)
        candidates.extend(inputs)
        conflicts.extend(errors)
    unique, values = {}, {}
    for fact in candidates:
        # A tool's `year` overrides a inherited scope's `Year`. They are one
        # dimension, not two periods to print or two different time series.
        dims = tuple(sorted({k.lower(): v for k, v in fact.dimensions}.items()))
        identity = (fact.source_id, dims, fact.metric, fact.value, fact.unit)
        normalized = replace(fact, id=stable_id("f_", identity), dimensions=dims)
        unique[normalized.id] = normalized
        values.setdefault((fact.metric, fact.unit, dims), set()).add(fact.value)
    conflicts.extend("Conflicting normalized evidence" for observed in values.values() if len(observed) > 1)
    return FactPack(tuple(sorted(unique.values(), key=lambda f: (f.dimensions, f.metric, f.source_id))),
                    pack.row_count, tuple(conflicts))
