"""The structured LLM stages — payload bounds, claim checks, retry and fallback.

Synthetic book, fake models: the model's behaviour is scripted so each path (verified
first time, repaired on the retry, refused twice, unavailable, over budget) is exercised
deterministically. No DB, no endpoint.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace

import pandas as pd
import pytest

from studio.exec_summary import payloads as P
from studio.exec_summary.analysis import analyse
from studio.exec_summary.config import load_config
from studio.exec_summary.context import AnalysisContext
from studio.exec_summary.llm import NoModel
from studio.exec_summary.peers import PeerSet
from studio.exec_summary.schemas import (
    SOURCE_FALLBACK,
    SOURCE_MODEL,
    ModelFinding,
    StageOutput,
)
from studio.exec_summary.stages import StageCall, StageEnv, run_stage, write_commentary
from studio.exec_summary.verify import names_universe, other_carriers, verify_stage

M = 1_000_000.0
CFG = load_config()


@pytest.fixture(autouse=True)
def _no_stage_cache(monkeypatch):
    monkeypatch.setenv("STUDIO_COMMENTARY_CACHE", "off")


def _book() -> pd.DataFrame:
    rows = []
    def add(country, product, industry, carrier, prior, cur, segment="Corporate"):
        for year, value in ((2024, prior), (2025, cur)):
            rows.append({"country": country, "product": product, "industry": industry,
                         "segment": segment, "carrier": carrier, "year": year,
                         "premium": value})
    for country, scale in (("Singapore", 1.0), ("Hong Kong", 0.8)):
        add(country, "Property", "Manufacturing", "Focal", 36 * M * scale, 40 * M * scale)
        add(country, "Property", "Chemicals", "Focal", 0.0, 0.0)
        add(country, "Property", "Chemicals", "Rival", 25 * M, 30 * M)
        add(country, "Property", "Manufacturing", "Rival", 100 * M, 120 * M)
        add(country, "Casualty", "Wholesale", "Focal", 15 * M * scale, 12 * M * scale)
        add(country, "Casualty", "Wholesale", "Rival", 135 * M, 168 * M)
        add(country, "Casualty", "Wholesale", "Other", 20 * M, 21 * M, segment="Commercial")
    return pd.DataFrame(rows)


@pytest.fixture
def analysis():
    ctx = AnalysisContext(carrier="Focal", countries=("Singapore", "Hong Kong"),
                          current_year=2025, prior_year=2024, current_label="FY2025",
                          prior_label="FY2024", currency="USD", symbol="$")
    peers = {"Singapore": PeerSet("Singapore", ("Rival",), "setup_pin"),
             "Hong Kong": PeerSet("Hong Kong", ("Rival", "Other"), "setup_pin")}
    return analyse(ctx, _book(), peers, None, CFG)


def _env(analysis, model) -> StageEnv:
    cube = _book()
    return StageEnv(model=model, store=analysis.evidence, run_id="t", rule_version="r",
                    budgets=CFG.budgets, concurrency=1,
                    forbidden_names=frozenset(other_carriers(cube, "Focal")),
                    universe=frozenset(names_universe(cube)))


def _facts(payload) -> dict:
    """``{metric: (id, display)}`` for the payload's top-level product/country facts."""
    found = {}
    for block in ("product", "country", "overall"):
        for metric, text in (payload.data.get(block) or {}).items():
            eid, display = text.split(" | ", 1)
            found[metric] = (eid, display)
    return found


def _good(payload, *, rule=None) -> StageOutput:
    f = _facts(payload)
    eid, display = f["carrier_premium"]
    return StageOutput(scope_id=payload.scope_id, findings=[ModelFinding(
        rule_id=rule or payload.allowed_rules[0], severity="context",
        statement=f"Carrier premium stands at {display}.", interpretation="", recommendation="",
        evidence_ids=[eid], qualifications=[])] * max(1, payload.min_findings),
        priority_refs=[], missing_references=[])


class ScriptedModel:
    """Returns the scripted answers in order, then ``None``."""

    label = "scripted"

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def complete(self, stage, system, user):
        self.calls.append((stage, user))
        return self.answers.pop(0) if self.answers else None


# ── payload bounds (design Section 19) ───────────────────────────────────────


def test_product_payload_is_bounded_and_every_fact_carries_its_id(analysis):
    ca = analysis.countries[0]
    payload = P.product_payload(analysis, ca, ca.products[0])
    rows = payload.data["industries"]["rows"]
    assert len(rows) <= 6 and len({r["name"] for r in rows}) == len(rows)
    assert len(payload.data["industries"]["top3"]) <= 3
    counts = payload.data["industries"]["counts"]
    assert counts["selected"] + counts["omitted"] == counts["total"]
    ids = set(re.findall(r'"(e\d+) \|', payload.to_json()))
    assert ids and ids <= payload.allowed_ids
    assert all(analysis.evidence.get(i) is not None for i in ids)


def test_a_product_with_no_qualified_candidate_makes_no_opportunity_call(analysis):
    ca = analysis.countries[0]
    casualty = next(p for p in ca.products if p.product == "Casualty")
    assert not casualty.shortlist
    assert P.opportunity_payload(analysis, ca, casualty) is None


def test_country_payload_never_carries_another_countrys_facts(analysis):
    sg, hk = analysis.countries
    env = _env(analysis, NoModel())
    commentary = write_commentary(analysis, env)
    payload = P.country_payload(analysis, sg, commentary.children)
    hk_ids = set(hk.evidence.values())
    assert not (payload.allowed_ids & hk_ids)


# ── claim checks (design Sections 13, 21) ────────────────────────────────────


@pytest.mark.parametrize("statement, cite_extra, reason", [
    ("Carrier premium stands at $41.0M.", False, "unsupported number"),
    ("Carrier premium stands at {d}, ahead of Rival.", False, "names another carrier"),
    ("Carrier premium stands at {d} because of Chemicals.", False, "causal wording"),
    ("Carrier premium stands at {d}, a strong market share.", False, "Marsh book"),
    ("Carrier premium stands at {d}, led by Aerospace.", False, None),
])
def test_verifier_drops_what_it_cannot_trace(analysis, statement, cite_extra, reason):
    ca = analysis.countries[0]
    payload = P.product_payload(analysis, ca, ca.products[0])
    eid, display = _facts(payload)["carrier_premium"]
    out = StageOutput(scope_id=payload.scope_id, findings=[ModelFinding(
        rule_id="PRODUCT_POSITION", severity="context", statement=statement.format(d=display),
        interpretation="", recommendation="", evidence_ids=[eid], qualifications=[])],
        priority_refs=[], missing_references=[])
    verified = verify_stage(out, payload, analysis.evidence, forbidden_names={"Rival", "Other"},
                            universe=names_universe(_book()) | {"Aerospace"})
    if reason is None:                    # an industry not in the payload is invented
        assert not verified.findings and "not in the input" in verified.errors[0]
    else:
        assert not verified.findings and reason in verified.errors[0]


def test_verifier_rejects_a_reversed_direction_and_a_foreign_id(analysis):
    ca = analysis.countries[0]
    casualty = next(p for p in ca.products if p.product == "Casualty")
    payload = P.product_payload(analysis, ca, casualty)
    eid, display = _facts(payload)["carrier_yoy"]           # -20.0%
    assert display.startswith("-")
    reversed_ = ModelFinding(rule_id="PRODUCT_WEAKNESS", severity="attention",
                             statement=f"Casualty premium grew {display}.", interpretation="",
                             recommendation="", evidence_ids=[eid], qualifications=[])
    foreign_id = analysis.countries[1].evidence["carrier_premium"]
    foreign = replace_finding(reversed_, statement="Casualty is reviewed.",
                              evidence_ids=[foreign_id])
    out = StageOutput(scope_id=payload.scope_id, findings=[reversed_, foreign],
                      priority_refs=[], missing_references=[])
    verified = verify_stage(out, payload, analysis.evidence)
    assert not verified.findings
    assert "rose beside a negative" in verified.errors[0]
    assert "not in this input" in verified.errors[1]


def replace_finding(f: ModelFinding, **kw) -> ModelFinding:
    return f.model_copy(update=kw)


def test_a_wrong_scope_rejects_the_whole_answer(analysis):
    ca = analysis.countries[0]
    payload = P.product_payload(analysis, ca, ca.products[0])
    out = _good(payload).model_copy(update={"scope_id": "Hong Kong/Property/*/*"})
    verified = verify_stage(out, payload, analysis.evidence)
    assert not verified.scope_ok and not verified.findings


# ── the stage runner: verified, repaired, refused, unavailable, over budget ──


def _product_call(analysis):
    ca = analysis.countries[0]
    pa = ca.products[0]
    from studio.exec_summary import fallback as FB
    from functools import partial
    return StageCall(P.product_payload(analysis, ca, pa),
                     partial(FB.product_fallback, analysis, ca, pa))


def test_a_verified_answer_is_used_as_is(analysis):
    call = _product_call(analysis)
    model = ScriptedModel(_good(call.payload))
    result = run_stage(call, _env(analysis, model))
    assert result.source == SOURCE_MODEL and result.status == "complete"
    assert len(model.calls) == 1
    assert all(f.validation_status == "verified" for f in result.findings)


def test_a_rejected_answer_gets_one_targeted_retry(analysis):
    call = _product_call(analysis)
    bad = _good(call.payload).model_copy(deep=True)
    bad.findings[0].statement = "Carrier premium stands at $99.9M."
    model = ScriptedModel(bad, _good(call.payload))
    result = run_stage(call, _env(analysis, model))
    assert result.source == SOURCE_MODEL
    assert len(model.calls) == 2
    assert "rejected for these reasons" in model.calls[1][1]
    assert "unsupported number" in model.calls[1][1]


def test_two_rejections_fall_back_to_deterministic_wording(analysis):
    call = _product_call(analysis)
    bad = _good(call.payload).model_copy(deep=True)
    bad.findings[0].statement = "Carrier premium stands at $99.9M."
    result = run_stage(call, _env(analysis, ScriptedModel(bad, bad)))
    assert result.source == SOURCE_FALLBACK and result.findings
    assert any("unsupported number" in e for e in result.errors)


def test_no_model_falls_back_and_the_fallback_passes_every_check(analysis):
    commentary = write_commentary(analysis, _env(analysis, NoModel()))
    for r in commentary.all_results():
        assert r.source == SOURCE_FALLBACK
        assert r.findings, r.scope_id
        assert all(e.startswith("model unavailable") for e in r.errors), (r.scope_id, r.errors)
    assert 2 <= len(commentary.overall.findings) <= CFG.findings.overall_max


def test_an_oversized_payload_is_never_sent(analysis):
    call = _product_call(analysis)
    tiny = replace(CFG.budgets, input_tokens={"product": 50})
    env = replace(_env(analysis, ScriptedModel(_good(call.payload))), budgets=tiny)
    result = run_stage(call, env)
    assert result.source == SOURCE_FALLBACK
    assert "payload over the input token budget" in result.errors
    assert env.model.calls == []


def test_concurrent_child_stages_keep_a_deterministic_order(analysis):
    env = replace(_env(analysis, NoModel()), concurrency=6)
    first = list(write_commentary(analysis, env).children)
    second = list(write_commentary(analysis, env).children)
    assert first == second
