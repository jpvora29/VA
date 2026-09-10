"""Run from the repo root: python tools/evaluate_icg_commentary.py [--live].

Offline checks verify synthetic reference text, numbers and readability only.
--live uses the existing local model configuration; no credentials are requested,
printed or written. It tests both authorship and rejection of misleading commentary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.template_fill import commentary as C, commentary_verify as V
from studio.template_fill.commentary_examples import cases


def evaluate(live=False, repeats=1):
    from core.definitions import get_glossary
    from studio.template_fill.commentary_writer import ColumnRequest, compose_with_agent
    if live:
        from studio.ai.client import llm_available
        if not llm_available():
            raise RuntimeError("Live evaluation needs the application's existing AI configuration and STUDIO_AI enabled.")
    results = []
    for case in cases():
        pack = case.pack
        source = V.Judged(case.reference, case.fact_ids, topic=case.topic)
        verified = V.check_numbers([source], pack)
        readable = C.judge_column(verified.kept, wanted=2, node="reference", subject=pack.subject)
        row = {"case": case.name, "section": case.topic, "reference": case.reference,
               "fact_ids": list(case.fact_ids), "evidence": pack.as_brief(),
               "reference_pass": bool(readable.text), "reject_example": case.reject,
               "rejection_reason": case.reason, "live_runs": []}
        if live:
            glossary = get_glossary().brief(pack.terms())
            for repeat in range(repeats):
                lines = compose_with_agent(ColumnRequest(topic=case.topic, pack=pack,
                    subject=pack.subject, bullets=2, voice=C.deck_voice("balanced", pack.subject),
                    brief=C.column_rules(case.topic, 2)))
                accepted = C.judge_column(lines, wanted=2, node="live-evaluation", subject=pack.subject)
                # Semantic adversarial check deliberately sees all relevant evidence.
                bad = V.Judged(case.reject, tuple(e.fact_id for e in pack.items), topic=case.topic)
                verdict = V.check_claims([bad], pack, glossary_brief=glossary)
                reviewed_rejection = bool(verdict.dropped) and "verification unavailable" not in verdict.dropped[0].reason
                row["live_runs"].append({"repeat": repeat+1, "authored": accepted.text,
                    "authored_pass": bool(accepted.text), "misleading_example_rejected": reviewed_rejection,
                    "review_reason": verdict.dropped[0].reason if verdict.dropped else "Incorrectly approved"})
        results.append(row)
    return {"mode": "live" if live else "offline-reference-check", "synthetic_data": True,
            "human_stakeholder_review_required": True, "cases": results,
            "passed": all(r["reference_pass"] and all(v["authored_pass"] and v["misleading_example_rejected"]
                           for v in r["live_runs"]) for r in results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("outputs/icg-commentary-review"))
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("--repeats must be between 1 and 10")
    try:
        report = evaluate(args.live, args.repeats)
    except RuntimeError as error:
        parser.exit(2, str(error) + "\n")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# ICG commentary review", "", f"Mode: {report['mode']}. All figures are synthetic.", "",
             "References were checked for numerical support and readability. Offline results do not evaluate AI authorship or semantic judgment.", ""]
    for row in report["cases"]:
        lines += [f"## {row['case']} — {row['section']}", "", row["reference"], "",
                  f"Reject: {row['reject_example']}", "", f"Why: {row['rejection_reason']}", ""]
        for run in row["live_runs"]:
            lines += [f"AI run {run['repeat']}: {run['authored'] or 'No accepted commentary'}", "",
                      f"Adversarial review: {run['review_reason']}", ""]
    (args.output / "review.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(report['cases'])} cases; {report['mode']}; passed={report['passed']}; {args.output / 'review.md'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
