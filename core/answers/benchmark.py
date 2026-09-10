"""Pairing a figure with the benchmark it should be read against.

"$390" is a number. "$390, below the peer average of $512 by $122" is the
finding, and on a question about how a carrier is doing it is usually THE
finding. The pairing that produces it used to key on
``(dimensions, lens, source_id)`` — the benchmark had to arrive in the same
result row as its subject.

That is the one shape the analytical path never produces. The peer solver makes
two tool calls, `compute_breakdown` for the carrier and
`compute_peer_average_total` for the field, and each call records its own
evidence set with its own provenance string — so two source ids, and dimensions
that differ by exactly the carrier, because a peer average is not filtered to one
carrier. Under the old key they could never meet, and the reader got two
unrelated observations sitting next to each other with the subtraction left to
them.

So the pairing is done here, on what actually makes two figures comparable:

    same measure      Premium against Peer_Avg_Premium, never against a score
    same unit         a currency benchmark for a currency figure
    same cut          the benchmark's dimensions, carrier aside, are the
                      subject's — so a Canada/2025 benchmark reads against the
                      Canada/2025 figure, and a per-product benchmark against
                      that product's figure
    one candidate     the CLOSEST subject wins; a tie is ambiguous and is
                      dropped rather than guessed

Pure: facts in, claims out. No model, no database.
"""
from __future__ import annotations

import re
from typing import Sequence

from core.answers.claims import AnswerClaim, context, relevance
from core.answers.facts import CARRIER_COLUMNS, AnswerFact, format_value, label, stable_id

# How a benchmark measure is spelled. `Peer_Avg_Premium` is what the tool digest
# labels `peer_average` / `peer_average_total` with
# (`core.analytics.tools.rows`); the looser spellings cover hand-written SQL.
BENCHMARK_PREFIX = re.compile(r"(?i)^peer[_ ]?(?:avg|average)[_ ]?")

# A question that asks to be benchmarked. The gap is then the direct answer and
# has to outrank the breadth and mix claims, rather than trailing them.
BENCHMARK_WORDS = re.compile(
    r"(?i)\bpeers?\b|\bbenchmark|\bversus\b|\bvs\.?\b|\bcompared?\b|\bcompetitors?\b"
    r"|\bthe\s+market\b|\brelative\s+to\b|\bagainst\b|\bposition(?:ed|ing)?\b"
)

#: Where a benchmark gap ranks. Asked for, it sits just under the portfolio
#: headline (50) so the answer leads with the book and then the comparison.
#:
#: Unasked it still outranks the premium decomposition's TAIL (35-40), and that
#: is deliberate. A broad "how is X performing?" draws on three books at once and
#: the answer is capped at ten claims, so at a lower rank the peer comparison was
#: pushed out by a seventh growth sentence — one more cut of the same book,
#: instead of the one number that says whether any of it is good.
ASKED = 46
UNASKED = 43


def benchmark_measure(metric: str) -> str:
    """The measure a benchmark metric benchmarks, lowercased, or "".

    `Peer_Avg_Premium` -> `premium`; `Premium` -> "" (it is a subject, not a
    benchmark).
    """
    text = str(metric or "")
    return BENCHMARK_PREFIX.sub("", text).strip().lower() if BENCHMARK_PREFIX.match(text) else ""


def comparable_cut(fact: AnswerFact) -> frozenset[tuple[str, str]]:
    """The dimensions two figures must agree on: everything but who it is about."""
    return frozenset((k, v) for k, v in fact.dimensions if k.lower() not in CARRIER_COLUMNS)


def _distance(subject: AnswerFact, cut: frozenset) -> int:
    """How much finer the subject's cut is than the benchmark's.

    A benchmark for (country, year) can sit under a total AND under every product
    line. The total is the one it belongs beside, and it is the one with nothing
    extra — so the closest subject wins and a tie is left alone.
    """
    return len([1 for pair in comparable_cut(subject) if pair not in cut])


def subject_for(benchmark: AnswerFact, facts: Sequence[AnswerFact]) -> AnswerFact | None:
    """The one figure this benchmark belongs beside, or None when unclear."""
    measure = benchmark_measure(benchmark.metric)
    if not measure:
        return None
    cut = comparable_cut(benchmark)
    candidates = [f for f in facts
                  if f.metric.lower() == measure and f.unit == benchmark.unit
                  and not benchmark_measure(f.metric) and cut <= comparable_cut(f)]
    if not candidates:
        return None
    closest = min(_distance(f, cut) for f in candidates)
    nearest = [f for f in candidates if _distance(f, cut) == closest]
    return nearest[0] if len(nearest) == 1 else None


def gap_claim(subject: AnswerFact, benchmark: AnswerFact, question: str) -> AnswerClaim:
    """"X was $390, below the peer average of $512 by $122." """
    delta = subject.value - benchmark.value
    direction = "above" if delta > 0 else "below" if delta < 0 else "equal to"
    text = (f"{label(subject.metric)} was {subject.rendered}, {direction} "
            f"the peer average of {benchmark.rendered}")
    if delta:
        unit = "percentage_points" if subject.unit == "percent" else subject.unit
        text += f" by {format_value(abs(delta), unit)}"
    scope = context(subject)
    text += f" ({scope})." if scope else "."
    asked = bool(question and BENCHMARK_WORDS.search(question))
    return AnswerClaim(stable_id("c_", [subject.id, benchmark.id, "peer_gap"]), text,
                       (subject.id, benchmark.id), "peer_gap",
                       f"{subject.value:g} - {benchmark.value:g} = {delta:g}",
                       (ASKED if asked else UNASKED) + relevance(question, subject))


def benchmark_claims(facts: Sequence[AnswerFact], question: str) -> list[AnswerClaim]:
    """One gap claim per benchmark the evidence can pair with a subject."""
    claims = []
    for fact in facts:
        subject = subject_for(fact, facts)
        if subject is not None:
            claims.append(gap_claim(subject, fact, question))
    return claims
