"""Skill-catalog inspection CLI (migration_plan.md Phase 4).

Shows exactly which skills the loader would inject for a given flow / scope /
query, why each one fired (own trigger vs pulled in via `requires`), and what was
suppressed — the observability hook that makes the progressive loader debuggable
without standing up the whole graph.

    python -m core.skills.inspect --flow gpr --scope sql --query "Zurich SoW by product"
    python -m core.skills.inspect --flow survey --scope planner --list   # full menu
    python -m core.skills.inspect --validate                             # CI health

`--body NAME` prints one skill's fully ref-resolved body.
"""
from __future__ import annotations

import argparse
import sys

from core.skills.loader import get_skill_loader


def _cmd_validate() -> int:
    issues = get_skill_loader().validate()
    if not issues:
        print("catalog OK - no validation issues")
        return 0
    print(f"{len(issues)} validation issue(s):")
    for issue in issues:
        print(f"  - {issue}")
    return 1


def _cmd_body(name: str) -> int:
    body = get_skill_loader().body(name)
    if body is None:
        print(f"unknown skill: {name!r}", file=sys.stderr)
        return 1
    print(body)
    return 0


def _cmd_list(flow: str, scope: str) -> int:
    loader = get_skill_loader()
    skills = loader.applicable(flow, scope)
    print(f"{len(skills)} skill(s) available for {flow}/{scope}:")
    for s in skills:
        gate = "always" if s.always else f"triggers={list(s.triggers)}"
        print(f"  [{s.priority:>3}] {s.name}  ({gate})")
    return 0


def _cmd_match(flow: str, scope: str, query: str) -> int:
    loader = get_skill_loader()
    matched = loader.matching(flow, scope, query)
    fired = {s.name for s in matched if s.positive_hit(query)}
    print(f"query: {query!r}\nflow={flow} scope={scope}")
    print(f"{len(matched)} skill(s) injected:")
    for s in matched:
        why = "trigger" if s.name in fired else "requires"
        print(f"  [{s.priority:>3}] {s.name}  (via {why})")
    conflicts = loader._conflicts(matched)
    if conflicts:
        print("conflicts (kept, warned):")
        for pair in conflicts:
            print(f"  - {pair[0]} <-> {pair[1]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m core.skills.inspect")
    p.add_argument("--flow", help="survey | gpr | gimmi | cross")
    p.add_argument("--scope", help="planner | sql | response | chart | pitch")
    p.add_argument("--query", help="user query to match triggers against")
    p.add_argument("--list", action="store_true", help="list the full flow/scope menu")
    p.add_argument("--body", metavar="NAME", help="print one skill's resolved body")
    p.add_argument("--validate", action="store_true", help="run catalog validation")
    args = p.parse_args(argv)

    if args.validate:
        return _cmd_validate()
    if args.body:
        return _cmd_body(args.body)
    if not args.flow or not args.scope:
        p.error("--flow and --scope are required unless --validate/--body is used")
    if args.list or not args.query:
        return _cmd_list(args.flow, args.scope)
    return _cmd_match(args.flow, args.scope, args.query)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
