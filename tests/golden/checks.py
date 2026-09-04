"""What makes an answer GOOD — the quality bar, as pure functions over a trace.

``diff.py`` compares two runs to each other and answers "did anything change?".
That is the right question during a refactor and the wrong one for "is the
chatbot any good?" — two runs can agree perfectly and both be wrong. These checks
ask the second question, of one run, against the things that were actually
reported broken: peer names appearing in answers, the premium missing from the
reply, charts arriving for some questions and not others.

**A check must not share a source with the code it audits.** The peer-name check
reads the carrier vocabulary from the WAREHOUSE, not from
``core.agents.common.peer_privacy`` — auditing the redactor with the redactor's
own output would pass by construction and catch nothing. The same principle
decides the rest: judge the output the user saw, using facts from the data.

Every check is a pure function of ``(trace, case)`` returning a
:class:`CheckResult`, and they are registered in one table. Add a rule by adding
a row, not by editing a runner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, List, Mapping, Sequence, Tuple

from tests.golden.harness import GoldenTrace

# Marsh is the market proxy, not a peer; the subject is whoever the question is
# about. Everything else that appears in a carrier column is a peer.
NAMEABLE = frozenset({"marsh"})

# Categories, so the scorecard can say WHICH kind of quality regressed.
CONFIDENTIALITY = "confidentiality"
GROUNDING = "grounding"
ROUTING = "routing"
PRESENTATION = "presentation"
COST = "cost"

# Budgets. Deliberately generous — these catch a runaway loop, not a slow day.
TOKEN_BUDGET = 120_000
LATENCY_BUDGET_MS = 180_000


@dataclass(frozen=True)
class CheckResult:
    """One rule's verdict on one trace."""

    name: str
    category: str
    passed: bool
    detail: str = ""
    #: A check that does not apply to this case (no expectation declared, no
    #: chart asked for). Skips are reported separately so a scorecard never
    #: flatters itself by counting them as passes.
    skipped: bool = False


@dataclass(frozen=True)
class Check:
    """One rule: what it guards, and how it judges a trace."""

    name: str
    category: str
    run: Callable[[GoldenTrace, Mapping[str, Any]], CheckResult]


def _ok(name: str, category: str, detail: str = "") -> CheckResult:
    return CheckResult(name=name, category=category, passed=True, detail=detail)


def _fail(name: str, category: str, detail: str) -> CheckResult:
    return CheckResult(name=name, category=category, passed=False, detail=detail)


def _skip(name: str, category: str, detail: str = "not applicable") -> CheckResult:
    return CheckResult(name=name, category=category, passed=True, detail=detail, skipped=True)


# ── the carrier vocabulary, read from the data ───────────────────────────────

@lru_cache(maxsize=1)
def carrier_vocabulary() -> Tuple[str, ...]:
    """Every carrier name in the warehouse — the words a leak would use.

    Read from the database rather than from the redactor's own bookkeeping, so
    this catches a name the redactor never noticed. An unreadable warehouse
    returns ``()`` and the confidentiality checks SKIP rather than pass: a check
    that cannot look must not report success.
    """
    names: set = set()
    try:
        from sqlalchemy import text

        from studio.data import get_engine

        with get_engine().connect() as conn:
            for table, column in (("GPR", "Carrier_Group"), ("Carriers", "Carrier")):
                try:
                    rows = conn.execute(
                        text(f'SELECT DISTINCT "{column}" FROM "{table}" '
                             f'WHERE "{column}" IS NOT NULL')
                    ).fetchall()
                except Exception:  # noqa: BLE001 - a flow this DB lacks
                    continue
                names.update(str(r[0]).strip() for r in rows if str(r[0] or "").strip())
    except Exception:  # noqa: BLE001 - no warehouse here
        return ()
    return tuple(sorted(names))


def _subjects(trace: GoldenTrace, case: Mapping[str, Any]) -> set:
    """Carriers this answer is allowed to name: the question's own, plus Marsh."""
    named = {str(v).strip().lower()
             for v in (trace.resolved_entities or {}).values() if str(v or "").strip()}
    text = f"{case.get('query', '')} {' '.join(case.get('history') or [])}".lower()
    for carrier in carrier_vocabulary():
        if re.search(rf"(?<!\w){re.escape(carrier.lower())}(?!\w)", text):
            named.add(carrier.lower())
    return named | set(NAMEABLE)


def peers_mentioned(text: str, allowed: set) -> List[str]:
    """Carrier names in `text` that this answer had no licence to use."""
    if not text:
        return []
    found: List[str] = []
    for carrier in carrier_vocabulary():
        if carrier.lower() in allowed:
            continue
        if re.search(rf"(?<!\w){re.escape(carrier)}(?!\w)", text, re.IGNORECASE):
            found.append(carrier)
    return found


def _rows_text(rows: Sequence[Mapping[str, Any]]) -> str:
    return " | ".join(
        " ".join(str(v) for v in row.values()) for row in rows if isinstance(row, dict)
    )


def _chart_text(specs: Sequence[Mapping[str, Any]]) -> str:
    parts: List[str] = []
    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        parts.append(str(spec.get("x") or ""))
        parts.extend(str(v) for v in (spec.get("y") or []))
        parts.extend(str(v) for v in (spec.get("series") or []))
    return " ".join(parts)


# ── confidentiality ──────────────────────────────────────────────────────────

def _no_peer_in(surface: str, getter: Callable[[GoldenTrace], str]):
    """Build the check that no unlicensed carrier is named on one surface."""
    name = f"no_named_peer_in_{surface}"

    def check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
        if not carrier_vocabulary():
            return _skip(name, CONFIDENTIALITY, "no warehouse to read carrier names from")
        text = getter(trace)
        if not text:
            return _skip(name, CONFIDENTIALITY, f"no {surface} in this turn")
        leaked = peers_mentioned(text, _subjects(trace, case))
        if leaked:
            return _fail(name, CONFIDENTIALITY, f"named {', '.join(sorted(set(leaked)))}")
        return _ok(name, CONFIDENTIALITY)

    return Check(name=name, category=CONFIDENTIALITY, run=check)


# ── grounding ────────────────────────────────────────────────────────────────

_NUMBER = re.compile(r"\d[\d,]*\.?\d*")
# Figures a sentence may carry without the data having produced them.
_FREE_NUMBERS = frozenset({"0", "1", "2", "3", "4", "5", "10", "100"})
_SCALES = {"k": 1_000, "m": 1_000_000, "bn": 1_000_000_000, "b": 1_000_000_000}


def _forms(token: str) -> set:
    """The ways one figure can legitimately be written."""
    bare = token.replace(",", "")
    out = {bare}
    try:
        value = float(bare)
    except ValueError:
        return out
    out.add(f"{value:.0f}")
    out.add(f"{value:.1f}")
    out.add(f"{value:.2f}")
    if value.is_integer():
        out.add(str(int(value)))
    return out


def _evidence_numbers(rows: Sequence[Mapping[str, Any]]) -> set:
    """Every figure the data produced, in every form it might be quoted as."""
    found: set = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for value in row.values():
            for token in _NUMBER.findall(str(value)):
                found |= _forms(token)
                try:  # a quoted $12.4M against a stored 12400000
                    number = float(token.replace(",", ""))
                except ValueError:
                    continue
                for suffix, scale in _SCALES.items():  # noqa: B007 - suffix unused
                    if number >= scale:
                        found.add(f"{number / scale:.1f}")
                        found.add(f"{number / scale:.0f}")
    return found


#: How many evidence figures to pair up when looking for a derived percentage.
#: Bounded because the pairing is quadratic and the answer's percentages come from
#: the headline figures, which are the first ones a row carries.
_RATIO_SAMPLE = 40


def _raw_numbers(rows: Sequence[Mapping[str, Any]]) -> List[float]:
    values: List[float] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for value in row.values():
            for token in _NUMBER.findall(str(value)):
                try:
                    values.append(float(token.replace(",", "")))
                except ValueError:
                    continue
    return values


def _derived_percentages(rows: Sequence[Mapping[str, Any]]) -> set:
    """Percentages any two evidence figures could honestly produce.

    An analyst's sentence says "8% below the peer average" — a figure that is in
    the data twice over (as the carrier's total and the peer's) and nowhere as
    itself. Without this the check flags every comparison in every good answer,
    and a check that cries wolf is one nobody reads.
    """
    values = [v for v in _raw_numbers(rows) if v][:_RATIO_SAMPLE]
    out: set = set()
    for a in values:
        for b in values:
            if not b or a == b:
                continue
            for pct in (100.0 * a / b, 100.0 * (a - b) / b):
                out.add(f"{abs(pct):.0f}")
                out.add(f"{abs(pct):.1f}")
    return out


def numbers_not_in_evidence(answer: str, rows: Sequence[Mapping[str, Any]]) -> List[str]:
    """Figures the prose states that the retrieved rows cannot account for.

    A figure is accounted for when it appears in a row, or when two rows produce
    it as a percentage (a gap, a share, a growth rate — the arithmetic an analyst
    is supposed to do). Years and small counting numbers pass: they are structure,
    not claims. What is left is a number the model supplied itself.
    """
    if not answer or not rows:
        return []
    allowed = _evidence_numbers(rows) | _derived_percentages(rows)
    loose: List[str] = []
    for token in _NUMBER.findall(answer):
        bare = token.replace(",", "")
        if bare in _FREE_NUMBERS or re.fullmatch(r"(19|20)\d{2}", bare):
            continue
        if not (_forms(token) & allowed):
            loose.append(token)
    return loose


# ── the table ────────────────────────────────────────────────────────────────

CHECKS: Tuple[Check, ...] = ()


def _route_check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
    expected = str(case.get("expected_route") or "")
    if not expected:
        return _skip("route_as_expected", ROUTING, "no expected_route declared")
    actual = _normalised_route(trace.route)
    if actual != _normalised_route(expected):
        return _fail("route_as_expected", ROUTING, f"expected {expected!r}, got {trace.route!r}")
    return _ok("route_as_expected", ROUTING)


def _normalised_route(route: str) -> str:
    """`gpr` and `premium` name the same family on either side of the router."""
    value = str(route or "").strip().lower()
    return "gpr" if value == "premium" else value


def _depth_check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
    expected = str(case.get("expected_depth") or "")
    if not expected:
        return _skip("depth_as_expected", ROUTING, "no expected_depth declared")
    if str(trace.depth or "").lower() != expected.lower():
        return _fail("depth_as_expected", ROUTING, f"expected {expected!r}, got {trace.depth!r}")
    return _ok("depth_as_expected", ROUTING)


def _skills_check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
    expected = set(case.get("expected_skills") or [])
    if not expected:
        return _skip("expected_skills_fired", ROUTING, "no expected_skills declared")
    missing = sorted(expected - set(trace.selected_skills or []))
    if missing:
        return _fail("expected_skills_fired", ROUTING, f"never fired: {', '.join(missing)}")
    return _ok("expected_skills_fired", ROUTING)


def _answered_check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
    """The turn produced prose at all — the failure that reads as a broken bot."""
    if str(case.get("expected_route") or "").lower() == "fallback":
        return _ok("answered", PRESENTATION, "fallback still answers")
    if trace.error:
        return _fail("answered", PRESENTATION, f"errored: {trace.error}")
    if not (trace.answer or "").strip():
        return _fail("answered", PRESENTATION, "no answer text")
    return _ok("answered", PRESENTATION)


def _measure_check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
    """A question about a measure is answered WITH that measure.

    "It's not showing premium" is this check. A premium question whose reply
    carries no figure has not been answered, however well it reads.
    """
    if str(case.get("expected_route") or "").lower() == "fallback":
        return _skip("answer_states_a_figure", GROUNDING, "fallback carries no measure")
    answer = trace.answer or ""
    if not answer:
        return _fail("answer_states_a_figure", GROUNDING, "no answer to inspect")
    if not _NUMBER.search(answer):
        return _fail("answer_states_a_figure", GROUNDING, "the answer states no figure at all")
    return _ok("answer_states_a_figure", GROUNDING)


def _faithful_check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
    if not trace.evidence_rows:
        return _skip("numbers_trace_to_evidence", GROUNDING, "no evidence captured")
    loose = numbers_not_in_evidence(trace.answer, trace.evidence_rows)
    if loose:
        return _fail("numbers_trace_to_evidence", GROUNDING,
                     f"not in the data: {', '.join(sorted(set(loose))[:5])}")
    return _ok("numbers_trace_to_evidence", GROUNDING)


def _chart_check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
    """A question that asked for a chart got one.

    Only asserted for the cases that ASK — "charts come for some questions and
    not others" is a complaint about explicit requests going unanswered, not
    about every answer needing a picture.
    """
    if str(case.get("category") or "").lower() != "chart":
        return _skip("chart_rendered_when_asked", PRESENTATION, "no chart requested")
    if not trace.chart_specs:
        return _fail("chart_rendered_when_asked", PRESENTATION,
                     "the query asked for a chart and none was produced")
    return _ok("chart_rendered_when_asked", PRESENTATION)


def _token_check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
    if not trace.token_total:
        return _skip("within_token_budget", COST, "no token count captured")
    if trace.token_total > TOKEN_BUDGET:
        return _fail("within_token_budget", COST,
                     f"{trace.token_total:,} tokens over the {TOKEN_BUDGET:,} budget")
    return _ok("within_token_budget", COST, f"{trace.token_total:,} tokens")


def _latency_check(trace: GoldenTrace, case: Mapping[str, Any]) -> CheckResult:
    if not trace.duration_ms:
        return _skip("within_latency_budget", COST, "not timed")
    if trace.duration_ms > LATENCY_BUDGET_MS:
        return _fail("within_latency_budget", COST,
                     f"{trace.duration_ms / 1000:.0f}s over the "
                     f"{LATENCY_BUDGET_MS / 1000:.0f}s budget")
    return _ok("within_latency_budget", COST, f"{trace.duration_ms / 1000:.1f}s")


CHECKS = (
    Check("route_as_expected", ROUTING, _route_check),
    Check("depth_as_expected", ROUTING, _depth_check),
    Check("expected_skills_fired", ROUTING, _skills_check),
    Check("answered", PRESENTATION, _answered_check),
    Check("answer_states_a_figure", GROUNDING, _measure_check),
    Check("numbers_trace_to_evidence", GROUNDING, _faithful_check),
    _no_peer_in("prose", lambda t: t.answer or ""),
    _no_peer_in("table", lambda t: _rows_text(t.table_rows)),
    _no_peer_in("chart_labels", lambda t: _chart_text(t.chart_specs)),
    Check("chart_rendered_when_asked", PRESENTATION, _chart_check),
    Check("within_token_budget", COST, _token_check),
    Check("within_latency_budget", COST, _latency_check),
)


def run_checks(trace: GoldenTrace, case: Mapping[str, Any]) -> List[CheckResult]:
    """Every check's verdict on one trace, in table order."""
    return [check.run(trace, case) for check in CHECKS]


def failures(results: Sequence[CheckResult]) -> List[CheckResult]:
    return [r for r in results if not r.passed]
