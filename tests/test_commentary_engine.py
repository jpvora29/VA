"""Commentary contracts, planner and verifier (plan Phases 4–5).

Pure tests over a synthetic EvidencePack — no DB, no LLM. Covers the plan's
commentary tests: YoY commentary includes current and prior premium, commentary
is suppressed below materiality thresholds, large movements need the absolute
change, driver language fails without decomposition facts, unsupported numbers
are removed, and named peers are blocked.
"""
from __future__ import annotations

import asyncio
import os

os.environ["STUDIO_AI"] = "off"

from studio.commentary import (  # noqa: E402
    build_commentary_plan,
    contract_for,
    draft_deterministic,
    draft_and_verify_commentary,
    verify_sentences,
)
from studio.commentary.planner import SlideCommentaryPlan  # noqa: E402
from studio.commentary.verify import CommentarySentence  # noqa: E402
from studio.content.evidence_graph import build_evidence_graph, material_entities  # noqa: E402
from studio.content.evidence_pack import (  # noqa: E402
    EvidenceItem,
    EvidencePack,
    Provenance,
    make_fact_id,
)

_PROD = "Product_Line"
_IND = "SIC_Major_Class"


def _item(items, measure, value, rendered, *, dims=None, period=None, derived_from=()):
    dims = dict(dims or {})
    fid = make_fact_id(measure, dims, period)
    items[fid] = EvidenceItem(
        fact_id=fid, measure=measure, value=value, rendered=rendered, dims=dims,
        provenance=Provenance(flow="gpr", source="GPR", period=period),
        derived_from=tuple(derived_from),
    )
    return fid


def _pack():
    """Synthetic Zurich pack: totals, movements, a decomposition, rank/sow,
    whitespace, an immaterial product, and a sub-floor mini book."""
    items = {}
    ids = {}
    ids["cur"] = _item(items, "premium_total", 42_100_000, "USD 42.1M",
                       dims={"year": 2026}, period=2026)
    ids["pri"] = _item(items, "premium_total", 35_600_000, "USD 35.6M",
                       dims={"year": 2025}, period=2025)
    ids["delta"] = _item(items, "premium_movement", 6_500_000, "+USD 6.5M",
                         dims={"scope": "total", "year": 2026}, period=2026,
                         derived_from=(ids["cur"], ids["pri"]))
    ids["pct"] = _item(items, "premium_movement_pct", 18.4, "+18.4%",
                       dims={"scope": "total", "year": 2026}, period=2026,
                       derived_from=(ids["cur"], ids["pri"]))
    ids["big_pct"] = _item(items, "premium_movement_pct", 25.0, "+25.0%",
                           dims={"scope": "total", "basis": "plan", "year": 2026},
                           period=2026, derived_from=(ids["cur"], ids["pri"]))
    ids["prop"] = _item(items, "premium_movement", 5_000_000, "+USD 5.0M",
                        dims={_PROD: "Property", "year": 2026}, period=2026)
    ids["rank"] = _item(items, "rank", 4, "#4 of 12", dims={"entity": "Zurich"}, period=2026)
    ids["sow"] = _item(items, "sow", 8.9, "8.9%", dims={"entity": "Zurich"}, period=2026)
    ids["ws"] = _item(items, "whitespace_market", 12_000_000, "USD 12.0M",
                      dims={_IND: "Aviation"}, period=2026)
    # Immaterial: a USD 1.0M product book (below the 5M practice floor).
    ids["niche"] = _item(items, "premium_total", 1_000_000, "USD 1.0M",
                         dims={_PROD: "Niche", "year": 2026}, period=2026)
    # A sub-floor mini book for the YoY narration-floor test.
    ids["small_cur"] = _item(items, "premium_total", 500_000, "USD 0.5M",
                             dims={"segment": "Micro", "year": 2026}, period=2026)
    ids["small_pct"] = _item(items, "premium_movement_pct", 12.0, "+12.0%",
                             dims={"segment": "Micro", "scope": "total", "year": 2026},
                             period=2026, derived_from=(ids["small_cur"],))
    pack = EvidencePack(subject="Zurich", country=None, period="FY2026",
                        comparison_period="FY2025", items=items)
    return pack, ids


def _plan(pack, ids, purpose="executive_summary", allowed=None):
    return SlideCommentaryPlan(
        slide_idx=2, purpose=purpose, contract=contract_for(purpose),
        allowed_fact_ids=tuple(sorted(allowed if allowed is not None else ids.values())),
    )


# ── planner: materiality suppression ─────────────────────────────────────────


def test_planner_suppresses_immaterial_entities():
    pack, ids = _pack()
    graph = build_evidence_graph(pack)
    plan = build_commentary_plan(pack, graph, [(2, "executive_summary")])
    allowed = plan.slides[0].allowed_fact_ids
    assert ids["niche"] not in allowed          # USD 1.0M product < 5M floor
    assert ids["cur"] in allowed and ids["prop"] in allowed


def test_material_entities_respects_floor():
    pack, ids = _pack()
    graph = build_evidence_graph(pack)
    material = material_entities(pack, graph)
    assert "product:Property" in material       # 5.0M movement clears the floor
    assert "product:Niche" not in material
    assert "industry:Aviation" in material


def test_empty_selection_becomes_data_gap():
    pack = EvidencePack(subject="Zurich", country=None, period="FY2026",
                        comparison_period="FY2025", items={})
    plan = build_commentary_plan(pack, build_evidence_graph(pack), [(1, "trading_summary")])
    assert plan.slides[0].data_gap


# ── deterministic drafting ────────────────────────────────────────────────────


def test_yoy_commentary_includes_current_and_prior_premium():
    pack, ids = _pack()
    sentences = draft_deterministic(_plan(pack, ids), pack)
    what_changed = sentences[0]
    assert "USD 42.1M" in what_changed.text and "USD 35.6M" in what_changed.text
    assert ids["cur"] in what_changed.fact_ids and ids["pri"] in what_changed.fact_ids
    kept, issues = verify_sentences(sentences, _plan(pack, ids), pack)
    assert kept and not issues


def test_driver_sentence_requires_sufficient_contribution():
    pack, ids = _pack()
    sentences = draft_deterministic(_plan(pack, ids), pack)
    driver = next((s for s in sentences if "driven by" in s.text), None)
    assert driver is not None                    # 5.0M / 6.5M = 77% ≥ 40% floor
    assert ids["prop"] in driver.fact_ids and ids["delta"] in driver.fact_ids


# ── verifier rules ────────────────────────────────────────────────────────────


def test_yoy_without_both_years_is_dropped():
    pack, ids = _pack()
    sent = CommentarySentence("Premium grew +18.4% year on year.", (ids["pct"],))
    kept, issues = verify_sentences([sent], _plan(pack, ids), pack)
    assert not kept
    assert any(i.code == "yoy_missing_years" for i in issues)


def test_unsupported_numbers_are_removed():
    pack, ids = _pack()
    sent = CommentarySentence("Premium reached USD 99.9M.", (ids["cur"],))
    kept, issues = verify_sentences([sent], _plan(pack, ids), pack)
    assert not kept
    assert any(i.code == "unsupported_number" for i in issues)


def test_driver_language_fails_without_decomposition_fact():
    pack, ids = _pack()
    sent = CommentarySentence("Growth was driven by strong renewals.",
                              (ids["cur"], ids["pri"]))
    kept, issues = verify_sentences([sent], _plan(pack, ids), pack)
    assert not kept
    assert any(i.code == "unsupported_causation" for i in issues)


def test_driver_language_passes_with_decomposition_fact():
    pack, ids = _pack()
    sent = CommentarySentence(
        "The movement was driven by Property, contributing +USD 5.0M of the +USD 6.5M change.",
        (ids["prop"], ids["delta"]))
    kept, issues = verify_sentences([sent], _plan(pack, ids), pack)
    assert kept and not issues


def test_named_peers_are_blocked():
    pack, ids = _pack()
    sent = CommentarySentence("Zurich outperformed AXA this year.", (ids["cur"],))
    kept, issues = verify_sentences([sent], _plan(pack, ids), pack,
                                    forbidden_names=("AXA",))
    assert not kept
    assert any(i.code == "peer_name" for i in issues)


def test_large_movement_requires_absolute_change():
    pack, ids = _pack()
    no_abs = CommentarySentence(
        "Premium grew +25.0% year on year to USD 42.1M, from USD 35.6M.",
        (ids["big_pct"], ids["cur"], ids["pri"]))
    kept, issues = verify_sentences([no_abs], _plan(pack, ids), pack)
    assert not kept
    assert any(i.code == "missing_absolute_change" for i in issues)

    with_abs = CommentarySentence(
        "Premium grew +25.0% year on year to USD 42.1M, from USD 35.6M — +USD 6.5M absolute.",
        (ids["big_pct"], ids["cur"], ids["pri"], ids["delta"]))
    kept, issues = verify_sentences([with_abs], _plan(pack, ids), pack)
    assert kept and not issues


def test_yoy_suppressed_below_narration_floor():
    pack, ids = _pack()
    sent = CommentarySentence("The micro book grew +12.0% to USD 0.5M.",
                              (ids["small_pct"], ids["small_cur"], ids["pri"]))
    kept, issues = verify_sentences([sent], _plan(pack, ids), pack)
    assert not kept
    assert any(i.code == "yoy_suppressed" for i in issues)


def test_uncited_and_disallowed_sentences_are_dropped():
    pack, ids = _pack()
    plan = _plan(pack, ids, allowed=[ids["cur"], ids["pri"]])
    uncited = CommentarySentence("A strong year overall.", ())
    disallowed = CommentarySentence("Rank held.", (ids["rank"],))
    kept, issues = verify_sentences([uncited, disallowed], plan, pack)
    assert not kept
    codes = {i.code for i in issues}
    assert {"uncited_sentence", "fact_not_allowed"} <= codes


def test_contract_caps_sentence_count():
    pack, ids = _pack()
    plan = _plan(pack, ids)
    cap = plan.contract.max_bullets * plan.contract.max_sentences_per_bullet
    many = [CommentarySentence(f"Premium held at USD 42.1M (view {chr(65 + i)}).", (ids["cur"],))
            for i in range(cap + 3)]           # letter suffix — no uncited numbers
    kept, issues = verify_sentences(many, plan, pack)
    assert len(kept) == cap
    assert any(i.code == "trimmed" for i in issues)


# ── async drafting preserves slide order ──────────────────────────────────────


def test_parallel_drafting_preserves_slide_order():
    pack, ids = _pack()
    graph = build_evidence_graph(pack)
    plan = build_commentary_plan(
        pack, graph, [(7, "trading_summary"), (2, "executive_summary"), (5, "growth")])
    result = asyncio.run(draft_and_verify_commentary(plan, pack))
    assert [c.slide_idx for c in result] == [7, 2, 5]      # input order, not completion order
    assert all(s.fact_ids for c in result for s in c.sentences)
