"""The scorecard: how good is the chatbot right now, and where is it weak.

    python -m tests.golden.report                 # score the recorded traces
    python -m tests.golden.report --live          # run the golden set, then score
    python -m tests.golden.report --record        # run it and SAVE as the record

A single pass/fail over the whole suite says nothing actionable — "the chatbot got
worse" is not a bug report. This prints the rate per QUERY CATEGORY (peer, chart,
lookup, hybrid) and per CHECK CATEGORY (confidentiality, grounding, routing,
presentation, cost), because those are the two cuts that name what broke.

Recorded traces are what let this run without credentials: `--record` captures a
live run to ``baseline/traces.json``, and every later run scores that file. The
checks themselves then regress under CI on every commit, which is the point —
a quality bar nobody can run is not a bar.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from tests.golden import checks as C
from tests.golden.harness import BASELINE_DIR, GoldenTrace, live_available, load_cases

TRACES_PATH = BASELINE_DIR / "traces.json"


@dataclass
class Tally:
    """Passes and failures for one bucket of the scorecard."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def scored(self) -> bool:
        """False when nothing in this bucket was actually judged.

        A bucket of pure skips is not a perfect score, and printing it as 100%
        is how a quality tool talks itself into believing the confidentiality
        rules hold on a run where no answer was produced to check.
        """
        return self.total > 0

    @property
    def rate(self) -> float:
        return 100.0 * self.passed / self.total if self.total else 0.0

    def add(self, result: C.CheckResult) -> None:
        if result.skipped:
            self.skipped += 1
        elif result.passed:
            self.passed += 1
        else:
            self.failed += 1


@dataclass
class Scorecard:
    """Every check's verdict on every case, bucketed the two ways that matter."""

    by_query_category: Dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))
    by_check_category: Dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))
    by_check: Dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))
    failures: List[Tuple[str, C.CheckResult]] = field(default_factory=list)
    overall: Tally = field(default_factory=Tally)

    def add(self, case: Mapping[str, Any], result: C.CheckResult) -> None:
        category = str(case.get("category") or "uncategorised")
        self.by_query_category[category].add(result)
        self.by_check_category[result.category].add(result)
        self.by_check[result.name].add(result)
        self.overall.add(result)
        if not result.passed:
            self.failures.append((str(case.get("id") or "?"), result))


def score(traces: Sequence[GoldenTrace], cases: Sequence[Mapping[str, Any]]) -> Scorecard:
    """Run every check over every trace it has a case for."""
    by_id = {str(c.get("id")): c for c in cases}
    card = Scorecard()
    for trace in traces:
        case = by_id.get(trace.id)
        if case is None:
            continue
        for result in C.run_checks(trace, case):
            card.add(case, result)
    return card


# ── rendering ────────────────────────────────────────────────────────────────

def _bar(rate: float, width: int = 20) -> str:
    filled = int(round(width * rate / 100.0))
    return "#" * filled + "." * (width - filled)


def _section(title: str, tallies: Mapping[str, Tally]) -> List[str]:
    if not tallies:
        return []
    lines = [f"\n{title}", "-" * len(title)]
    # Unscored buckets sort last: they are not the best result, they are no result.
    for name, tally in sorted(tallies.items(), key=lambda kv: (kv[1].scored, kv[1].rate, kv[0])):
        skipped = f"  ({tally.skipped} n/a)" if tally.skipped else ""
        if not tally.scored:
            lines.append(f"  {name:26s} {'-' * 20}    n/a   nothing to judge{skipped}")
            continue
        lines.append(f"  {name:26s} {_bar(tally.rate)}  {tally.rate:5.1f}%  "
                     f"{tally.passed}/{tally.total}{skipped}")
    return lines


def render(card: Scorecard) -> str:
    lines = ["", "=" * 64, "  CHATBOT QUALITY SCORECARD", "=" * 64]
    lines.append(f"\noverall: {card.overall.passed}/{card.overall.total} checks passed "
                 f"({card.overall.rate:.1f}%), {card.overall.skipped} not applicable")
    lines += _section("by query category", card.by_query_category)
    lines += _section("by check category", card.by_check_category)
    lines += _section("by check", card.by_check)
    if card.failures:
        lines += ["", "failures", "--------"]
        for case_id, result in card.failures:
            lines.append(f"  {case_id:28s} {result.name:30s} {result.detail}")
    else:
        lines += ["", "no failures."]
    return "\n".join(lines) + "\n"


# ── trace i/o ────────────────────────────────────────────────────────────────

def load_traces(path: Path = TRACES_PATH) -> List[GoldenTrace]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [GoldenTrace.from_dict(item) for item in raw]


def save_traces(traces: Sequence[GoldenTrace], path: Path = TRACES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([t.to_dict() for t in traces], indent=2, default=str),
        encoding="utf-8",
    )


def _capture() -> List[GoldenTrace]:
    from tests.golden.harness import run_golden_set

    return run_golden_set()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Score the golden query set.")
    parser.add_argument("--live", action="store_true",
                        help="run the golden set now instead of scoring the record")
    parser.add_argument("--record", action="store_true",
                        help="run the golden set and save it as the record")
    parser.add_argument("--fail-under", type=float, default=0.0,
                        help="exit non-zero when the overall pass rate is below this")
    args = parser.parse_args(argv)

    if args.live or args.record:
        if not live_available():
            print("live run needs API_KEY / ENDPOINT / DEPLOYMENT.", file=sys.stderr)
            return 2
        traces = _capture()
        if args.record:
            save_traces(traces)
            print(f"recorded {len(traces)} trace(s) -> {TRACES_PATH}")
    else:
        traces = load_traces()
        if not traces:
            print(f"no recorded traces at {TRACES_PATH}. Run with --record "
                  f"(needs credentials) to create them.", file=sys.stderr)
            return 2

    card = score(traces, load_cases())
    print(render(card))
    if args.fail_under and card.overall.rate < args.fail_under:
        print(f"pass rate {card.overall.rate:.1f}% is below the required "
              f"{args.fail_under:.1f}%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
