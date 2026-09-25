"""Does a tier's deployment actually honour a reasoning effort?

Fires the same prompt twice on one tier — once as the tier is configured, once with
a reasoning effort — and prints the token usage of each, so you can see whether the
deployment spent reasoning tokens:

    python -m recap.check_reasoning_effort
    python -m recap.check_reasoning_effort --effort high --tier reason

What to look for:

- reasoning tokens > 0 on the WITH-effort call: the effort was honoured, and
  RECAP_REASONING_EFFORT is safe to set for stages on this tier.
- reasoning tokens 0 on the WITH-effort call: the deployment ignores the effort.
- a 400 on the WITH-effort call: the deployment is a classic model and rejects
  ``reasoning_effort`` outright — leave RECAP_REASONING_EFFORT unset for it.

The calls go through the same :func:`recap.llm.llm_client._bind` a recap run uses, so
the result describes the request a run would really send.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional

from core.llm.clients import resolve_tier
from recap.llm.llm_client import STRUCTURED_TIER, _bind, reasoning_tokens

SYSTEM_PROMPT = (
    "You are a helpful assistant. Respond ONLY with a JSON object of the "
    'form {"answer": "<your answer>"}.'
)
USER_MESSAGE = (
    "Think through this step by step, then answer: if a train leaves at "
    "3pm travelling 60mph and another leaves at 4pm travelling 90mph on "
    "the same route, at what time does the second train catch the first?"
)
TOKEN_BUDGET = 1800


async def call_once(tier: str, effort: Optional[str]) -> None:
    """One call, and what it cost. A failure is printed, not raised: it is the answer."""
    label = f"tier={tier!r} reasoning_effort={effort!r}"
    print(f"\n=== {label} ===")
    try:
        response = await _bind(tier, TOKEN_BUDGET, effort).ainvoke(
            [("system", SYSTEM_PROMPT), ("human", USER_MESSAGE)]
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic script, show everything
        print(f"CALL FAILED: {type(exc).__name__}: {exc}")
        return

    usage = response.usage_metadata or {}
    print("Answer:", (response.content or "")[:300])
    print("Usage:", json.dumps(usage, indent=2, default=str))
    if effort is None:
        return
    spent = reasoning_tokens(usage)
    if spent:
        print(f"CONFIRMED: reasoning_effort={effort!r} was honoured ({spent} reasoning tokens).")
    else:
        print(f"NOT CONFIRMED: reasoning_effort={effort!r} was sent but no reasoning "
              "tokens were reported - the deployment likely ignores it.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--effort", default="medium",
                        choices=["minimal", "low", "medium", "high"],
                        help="reasoning_effort to test (default: medium)")
    parser.add_argument("--tier", default=STRUCTURED_TIER,
                        help=f"tier to test (default: {STRUCTURED_TIER})")
    args = parser.parse_args()

    config = resolve_tier(args.tier)
    print(f"Tier {args.tier!r} -> deployment {config.deployment or '(ENDPOINT default)'}, "
          f"configured effort {config.effort or '(none - classic)'}")
    await call_once(args.tier, None)
    await call_once(args.tier, args.effort)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
