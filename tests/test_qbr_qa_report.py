"""QAReport (plan Phase 6): grouping, blocking policy, template + content checks."""
from __future__ import annotations

import os

os.environ["STUDIO_AI"] = "off"

from studio.commentary.agent import SlideCommentary  # noqa: E402
from studio.commentary.verify import CommentarySentence, VerificationIssue  # noqa: E402
from studio.content.evidence_pack import EvidenceItem, EvidencePack  # noqa: E402
from studio.qa import (  # noqa: E402
    CRITICAL,
    INFO,
    WARNING,
    QAIssue,
    QAReport,
    check_charts,
    check_required_slots,
    run_qbr_qa,
)
from studio.template_intelligence.binding import BindingMapV2, SlotBindingV2  # noqa: E402


def _field(slide_idx=0, role="carrier_gwp", filled=True, text="USD 42.1M",
           value_kind="money", where=("para", 0)):
    return {
        "slide_idx": slide_idx, "shape_id": 7, "where": list(where),
        "value_kind": value_kind, "token": "$xx,xxxm", "role": role,
        "placeholder": False, "text": text, "filled": filled,
    }


def _pack_with(fact_id="f_1", rendered="USD 42.1M"):
    item = EvidenceItem(fact_id=fact_id, measure="premium_total", value=42_100_000.0,
                        rendered=rendered)
    return EvidencePack(subject="Zurich", country=None, period="FY2026",
                        comparison_period="FY2025", items={fact_id: item})


# ── report shape ──────────────────────────────────────────────────────────────


def test_report_groups_and_blocks_only_on_critical():
    report = QAReport(issues=(
        QAIssue("a", WARNING, "w"), QAIssue("b", INFO, "n"),
    ))
    assert not report.blocking
    assert report.counts() == {"critical": 0, "warning": 1, "info": 1, "total": 2}

    blocked = QAReport(issues=report.issues + (QAIssue("c", CRITICAL, "boom"),))
    assert blocked.blocking
    assert set(blocked.grouped()) == {CRITICAL, WARNING, INFO}


# ── template checks ───────────────────────────────────────────────────────────


def test_unfilled_mapped_slot_is_a_warning_not_a_block():
    fields = {"k1": _field(filled=False, text="$xx,xxxm")}
    issues = check_required_slots(fields)
    assert [i.severity for i in issues] == [WARNING]
    assert issues[0].code == "slot_unfilled"


def test_stale_placeholder_text_is_critical():
    fields = {"k1": _field(filled=True, text="xx.x%")}
    issues = check_required_slots(fields)
    assert [i.code for i in issues] == ["slot_stale_placeholder"]
    assert issues[0].severity == CRITICAL


def test_hidden_slides_are_skipped():
    fields = {"k1": _field(slide_idx=3, filled=False)}
    assert check_required_slots(fields, hidden_slides=[3]) == []


def test_chart_checks_empty_vs_populated_series():
    fields = {"c1": _field(role="growth_bubble", value_kind="series", where=("chart",))}
    ok = check_charts(fields, {"growth_bubble": {"points": [{"lob": "Marine"}]}})
    assert [i.code for i in ok] == ["chart_data_ok"]

    empty = check_charts(fields, {"growth_bubble": {"points": []}})
    assert [i.code for i in empty] == ["chart_empty_series"]
    assert empty[0].severity == CRITICAL

    missing = check_charts(fields, {})
    assert [i.code for i in missing] == ["chart_no_data"]
    assert missing[0].severity == WARNING


# ── content checks through run_qbr_qa ─────────────────────────────────────────


def test_commentary_with_unknown_fact_blocks_export():
    pack = _pack_with()
    commentary = [SlideCommentary(
        slide_idx=1, purpose="trading_summary",
        sentences=(CommentarySentence("Premium reached USD 42.1M.", ("f_missing",)),),
    )]
    report = run_qbr_qa(fields={}, values={}, commentary=commentary, pack=pack)
    assert report.blocking
    assert any(i.code == "commentary_unknown_fact" for i in report.criticals())


def test_faithful_commentary_and_recorded_blanks_do_not_block():
    pack = _pack_with()
    commentary = [SlideCommentary(
        slide_idx=1, purpose="trading_summary",
        sentences=(CommentarySentence("Premium reached USD 42.1M.", ("f_1",)),),
        issues=(VerificationIssue("trimmed", "1 sentence over cap", 1),),
    )]
    bmap = BindingMapV2(
        name="t", template_path="x.pptx",
        bindings=(
            SlotBindingV2(0, 7, ("para", 0), "money", "$xx", role="carrier_gwp"),
            SlotBindingV2(0, 9, ("shape",), "text", "", role=None, treatment="decorative"),
        ),
    )
    report = run_qbr_qa(
        fields={"k1": _field()}, values={}, commentary=commentary, pack=pack,
        binding_map=bmap,
    )
    assert not report.blocking
    codes = {i.code for i in report.issues}
    assert "intentionally_blank" in codes            # silence is recorded, allowed
    assert "binding_unapproved" in codes             # draft map flagged as warning


def test_peer_leak_in_final_output_is_critical():
    pack = _pack_with()
    commentary = [SlideCommentary(
        slide_idx=1, purpose="swot",
        sentences=(CommentarySentence("Premium reached USD 42.1M vs AXA.", ("f_1",)),),
    )]
    report = run_qbr_qa(fields={}, values={}, commentary=commentary, pack=pack,
                        banned_names=("AXA",))
    assert report.blocking
    assert any(i.code == "peer_name_leak" for i in report.criticals())
