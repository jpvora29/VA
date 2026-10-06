"""The solver prompt is shaped for the prompt cache and carries no dead weight.

Three changes, each pinned here:

* the turn-shared part comes FIRST, so every solver in a turn sends an identical
  opening the provider can serve from cache — the sub-question used to be the
  third block, which made each solver's prompt unique from there on;
* a skill that declares both scopes is printed once, not once per scope, and
  with the calculation library on the triggered rule bodies are offered by name
  (`consult_skill`) instead of being resent on every model call;
* a dependent step sees at most a few rows of each earlier record, plus the
  record's real row count.

Run:  pytest tests/test_solver_prompt_budget.py -q
"""
from __future__ import annotations

import json
import re

import pytest

from core.agents.analyst import common
from core.schemas.analyst_subgraph import SchemaSlice

QUESTION = "Why did Allianz premium decline in Singapore and how does it compare to peers?"


@pytest.fixture(autouse=True)
def _offline_schema(monkeypatch):
    schema = {"GPR": [{"Column Name": "Premium"}], "Peers": [{"Column Name": "Carrier_Group"}]}
    monkeypatch.setattr(common, "get_schema", lambda flow: schema)
    monkeypatch.delenv("SOLVER_RULES", raising=False)
    monkeypatch.delenv("ANALYTICS_TOOLS", raising=False)


def _prompt(*, role="ROLE A", lens="temporal_trend", sub_question=QUESTION, prior=""):
    return common._solver_prompt(
        role=role, question=QUESTION, sub_question=sub_question, lens=lens,
        flow="gpr", route="premium", schema_slice=SchemaSlice(), prior_digest=prior,
    )


def _head():
    return common.solver_prompt_head(flow="gpr", route="premium", schema_slice=SchemaSlice())


# ── 1. cacheable shape ───────────────────────────────────────────────────────


def test_every_solver_in_a_turn_opens_with_the_same_head():
    head = _head()
    one = _prompt(role="Generic solver", lens="temporal_trend", sub_question="How did it move?")
    two = _prompt(role="Peer solver", lens="peer_benchmark", sub_question="Versus peers?")
    assert one.startswith(head) and two.startswith(head)


def test_the_head_holds_nothing_that_varies_by_step():
    head = _head()
    for step_specific in ("[SUB-QUESTION", "[LENS TO APPLY", "[YOUR ROLE",
                          "[RESULTS FROM EARLIER STEPS", "[DOMAIN RULES"):
        assert step_specific not in head


def test_the_sub_question_is_the_last_block():
    prompt = _prompt(sub_question="How did Marine move?")
    assert prompt.rstrip().endswith("[SUB-QUESTION — answer only this]\nHow did Marine move?")


def test_the_head_still_carries_the_compute_first_rules_and_confidentiality():
    head = _head()
    assert "CALCULATIONS AVAILABLE BY NAME" in head
    assert "Reach for compute_metric FIRST" in head
    assert "CONFIDENTIALITY" in head


# ── 2. rules: once each, and on demand ───────────────────────────────────────


def _skill_headings(text: str) -> list:
    """Skill names as rendered (`## gpr-timeframe`); a body's own `## Definition`
    subheadings are not skill names."""
    return re.findall(r"^## ([a-z0-9]+(?:-[a-z0-9]+)+)$", text, flags=re.MULTILINE)


def test_a_skill_declared_for_both_scopes_is_printed_once():
    names = _skill_headings(common.domain_rules("premium", "gpr", QUESTION))
    assert names and len(names) == len(set(names))


def test_a_both_route_prints_a_shared_skill_once_across_flows():
    names = _skill_headings(common.domain_rules("both", "gpr", QUESTION))
    assert names.count("cross-sql-readonly-safety") == 1


def test_on_demand_rules_keep_always_on_skills_inline_and_offer_the_rest_by_name():
    rules = common.solver_rules("premium", "gpr", QUESTION)
    inline = _skill_headings(rules)
    assert "gpr-default-timeframe" in inline
    assert "gpr-peer-average" not in inline  # triggered: offered, not inlined
    assert "- gpr-peer-average:" in rules
    assert "consult_skill(name)" in rules


def test_worked_planner_examples_are_never_inlined_into_a_solver():
    assert not any(name.endswith("-example")
                   for name in _skill_headings(common.solver_rules("premium", "gpr", QUESTION)))


def test_full_mode_restores_every_matched_body(monkeypatch):
    monkeypatch.setenv("SOLVER_RULES", "full")
    assert "gpr-peer-average" in _skill_headings(common.solver_rules("premium", "gpr", QUESTION))


def test_with_the_library_off_the_solver_gets_the_full_sql_rules(monkeypatch):
    """No named calculation to reach for -> SQL is the only path, so it needs them."""
    monkeypatch.setenv("ANALYTICS_TOOLS", "off")
    assert "gpr-peer-average" in _skill_headings(common.solver_rules("premium", "gpr", QUESTION))


def test_on_demand_is_materially_smaller_than_full(monkeypatch):
    on_demand = len(common.solver_rules("both", "gpr", QUESTION))
    monkeypatch.setenv("SOLVER_RULES", "full")
    assert on_demand < len(common.solver_rules("both", "gpr", QUESTION)) / 2


# ── 3. earlier results ───────────────────────────────────────────────────────


def test_a_dependent_step_sees_a_capped_digest_with_the_real_row_count():
    record = {"evidence_id": "e1", "step_id": "s0", "lens": "temporal_trend", "flow": "gpr",
              "status": "validated", "sql": "SELECT 1", "rows": [{"n": i} for i in range(80)]}
    (digested,) = json.loads(common.digest_evidence([record]))
    assert digested["row_count"] == 80
    assert len(digested["rows"]) == common._PRIOR_DIGEST_ROWS < 80
