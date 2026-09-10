"""Carrier-facing regressions at the evidence/writer seam used by Studio export.

These are synthetic facts, including the user's illustrative failure patterns.
They assert meaning and delivery controls rather than preferred adjectives.
"""
from types import SimpleNamespace

import pytest

from studio.template_fill import commentary as C
from studio.template_fill import commentary_evidence as E
from studio.template_fill import commentary_verify as V
from studio.template_fill import facts_trend as T


def facts(**overrides):
    value = {
        "subject": "Example Carrier",
        "scope": {"Product_Line": "Environmental", "Country": "Singapore"},
        "carrier": {"current_year": 2025, "current": 10_000_000, "prior": 12_000_000,
                    "pct": -16.6667, "delta": -2_000_000},
        "marsh": {"current": 100_000_000, "prior": 80_000_000, "pct": 25},
        "sow": {"current": 10, "delta": -5}, "rank": {},
        "peer": {"sow": 18.5, "n_carriers": 3, "benchmark_count": 3},
    }
    value.update(overrides)
    return value


def test_opposite_movements_cannot_have_identical_evidence():
    def pack(sign):
        return E.build_pack(facts(carrier={"current": 100, "pct": sign * 20,
                                          "delta": sign * 20},
                                  marsh={"current": 1000, "pct": sign * 10}))
    assert pack(1).as_brief() != pack(-1).as_brief()
    assert "decreased" in pack(-1).get("carrier.yoy").as_line().lower()


def test_prior_premium_and_explicit_scope_reach_author():
    pack = E.build_pack(facts())
    assert pack.get("carrier.prior") is not None
    assert "Environmental" in pack.as_brief() and "Singapore" in pack.as_brief()


def test_equal_numbers_in_different_scopes_do_not_group_together():
    from studio.template_fill.commentary_batch import _evidence_key
    first = facts()
    second = facts(scope={"Product_Line": "Marine", "Country": "Singapore"})
    assert _evidence_key(first, {}) != _evidence_key(second, {})


def test_immaterial_mover_does_not_reach_author():
    pack = E.build_pack(facts(movers=[{"name": "Manufacturing", "delta": -2000}]))
    assert pack.get("mover.Manufacturing") is None


def test_benchmark_names_actual_count_and_selection_basis():
    line = E.build_pack(facts()).get("peer.sow").as_line().lower()
    assert "top-5" not in line and "3" in line and "largest" in line


def test_above_benchmark_is_not_a_premium_growth_target():
    pack = E.build_pack(facts(sow={"current": 20}, peer={"sow": 18.5}))
    assert pack.get("peer.gap_value") is None


def test_clear_metric_opening_is_accepted():
    line = "Share of Marsh Services premium held by Example Carrier fell by 8.9 percentage points to 16.8%."
    kept, dropped = C._keep_lines([line], "Example Carrier")
    assert kept == [line] and not dropped


@pytest.mark.parametrize("line", [
    "The book also lost 1.5 percentage points in the client segment that averaged 3.7% share across a $17M pool that grew 149.5%, so the pressure sat in the fastest-growing placement base.",
    "Services also lost 8.9 percentage points to 16.8% of a $5M pool that grew 38.6%, which made that line the clearest place where Marsh demand outpaced the book.",
    "Manufacturing gave back $2K, and the same book still grew by $6K, so the loss sat inside a rising Marsh flow rather than a shrinking one.",
])
def test_ambiguous_placement_sentences_need_repair(line):
    kept, dropped = C._keep_lines([line], "Example Carrier")
    assert not kept and dropped


def test_missing_verifier_is_not_approval(monkeypatch):
    monkeypatch.setattr("studio.ai.client.structured", lambda *a, **k: None)
    result = V.check_claims([V.Judged("The carrier lost share.", ("sow.delta",))], E.build_pack(facts()))
    assert not result.kept and "unavailable" in result.dropped[0].reason


def test_unknown_citation_is_rejected_even_without_numbers():
    result = V.check_numbers([V.Judged("The carrier lost share.", ("invented.fact",))], E.build_pack(facts()))
    assert not result.kept


def test_clear_single_finding_does_not_need_padding():
    line = "Example Carrier's share of Marsh Services premium fell to 16.8%."
    assert C.judge_column([line], wanted=3, node="quality").text == line


def test_seasonality_does_not_become_acceleration(monkeypatch):
    labels = [f"{year}-{month:02d}" for year in (2024, 2025) for month in range(1, 13)]
    values = [100 if month < 10 else 200 for year in (2024, 2025) for month in range(1, 13)]
    monkeypatch.setattr(T.C, "period_series", lambda *a, **k: {"labels": labels, "values": values})
    result = T.load(SimpleNamespace(flow="gpr", engine=None), {"Year": 2025}, annual_pct=0)
    assert not result.get("pace")
    assert result["quarter_yoy"] == 0
    assert result["quarter_prior_label"] == "2024-Q4"


def test_incomplete_quarter_is_not_called_closed(monkeypatch):
    labels = [f"{year}-{month:02d}" for year in (2024, 2025) for month in range(1, 12)]
    monkeypatch.setattr(T.C, "period_series", lambda *a, **k: {"labels": labels, "values": [100] * len(labels)})
    result = T.load(SimpleNamespace(flow="gpr", engine=None), {"Year": 2025})
    assert result["quarter_label"] == "2025-Q3"


def test_segment_marsh_growth_direction_is_preserved():
    row = SimpleNamespace(sow_delta=-8.9, sow=16.8, market=5_000_000,
                          market_yoy=-38.6, peer_sow=None)
    assert "decreased" in E._losing_value(row).lower()


def test_simple_reversed_movement_is_rejected_without_a_model():
    pack = E.build_pack(facts())
    result = V.check_numbers([V.Judged("Carrier premium increased 16.7%.", ("carrier.yoy",))], pack)
    assert not result.kept and "direction" in result.dropped[0].reason


def test_review_keeps_identical_text_attached_to_its_own_section(monkeypatch):
    from studio.ai.models import CommentaryVerdict, CommentaryVerdicts
    monkeypatch.setattr("studio.ai.client.structured", lambda *a, **k: CommentaryVerdicts(
        verdicts=[CommentaryVerdict(keep=True), CommentaryVerdict(keep=False, reason="wrong section")]))
    items = [V.Judged("The carrier lost share.", ("sow.delta",), topic=topic)
             for topic in ("challenges", "working")]
    result = V.verify(items, E.build_pack(facts()))
    assert result.judged[0].kept and not result.judged[1].kept
    assert result.judged[0].topic == "challenges"


def test_positive_results_do_not_generate_a_challenge():
    from studio.template_fill import commentary_findings as F
    pack = E.build_pack(facts(carrier={"current": 20e6, "prior": 10e6, "pct": 100, "delta": 10e6},
                              sow={"current": 20, "delta": 10}, peer={}))
    assert not F.for_topic(pack, "challenges")
    assert pack.get("assessment.challenges")
    assert "Do not turn a positive result" in F.brief(pack, "challenges")


def test_small_quarter_base_suppresses_extreme_percentage(monkeypatch):
    labels = [f"{year}-{month:02d}" for year in (2024, 2025) for month in (10, 11, 12)]
    values = [100, 100, 100, 4751, 4751, 4751]
    monkeypatch.setattr(T.C, "period_series", lambda *a, **k: {"labels": labels, "values": values})
    result = T.load(SimpleNamespace(flow="gpr", engine=None), {"Year": 2025})
    assert result["quarter_yoy"] is None and result["quarter_prior"] == 300
    assert result["comparison_note"]


def test_html_entities_do_not_reach_export_text():
    line = "The carrier's share of Marsh premium fell.&#x20;"
    result = C.judge_column([line], wanted=2, node="html")
    assert result.text == "The carrier's share of Marsh premium fell."


def test_all_synthetic_references_are_citable_and_readable():
    from studio.template_fill.commentary_examples import cases
    for case in cases():
        result = V.check_numbers([V.Judged(case.reference, case.fact_ids, topic=case.topic)], case.pack)
        assert result.kept, (case.name, result.dropped)
        assert C.judge_column(result.kept, wanted=2, node=case.name).text == case.reference


def test_negative_quarter_base_keeps_its_sign_in_evidence_and_preview():
    f = facts(trend={"quarter_current": 40000, "quarter_prior": -10000,
                     "quarter_label": "2025-Q4", "quarter_prior_label": "2024-Q4",
                     "quarter_yoy": None})
    assert "-$10K" in E.build_pack(f).get("trend.quarter").rendered
    assert "-$10K" in T.lines_for("performance", f)[0]


def test_default_mode_requires_verified_ai(monkeypatch):
    from studio import commentary_mode
    monkeypatch.delenv("COMMENTARY_MODE", raising=False)
    monkeypatch.delenv("STUDIO_AI", raising=False)
    assert commentary_mode.mode() == commentary_mode.AI_REQUIRED


def test_repairs_cannot_reintroduce_an_accepted_benchmark_finding():
    from studio.template_fill.commentary_batch import _exclude_established
    accepted = {"challenge": "The carrier is below the peer average by 2.0 percentage points."}
    fresh = {"priority": ["Reaching peer parity is the priority this year."]}
    dropped = {}
    assert _exclude_established(fresh, accepted, dropped) == {"priority": []}
    assert "already accepted" in dropped["priority"][0]


def test_numeric_units_do_not_consume_the_start_of_normal_words():
    from studio.ai.verifier import allowed_numbers, verify_bullets
    assert allowed_numbers("12 by premium, 3 months, 4 key segments") == {"12", "3", "4"}
    assert allowed_numbers("$12B, $3M, $4K") == {"12b", "3m", "4k"}
    assert verify_bullets(["Ranked 3 of 12 by Marsh-placed premium."], {"3", "12"})[0]
