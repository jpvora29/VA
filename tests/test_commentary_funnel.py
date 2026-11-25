"""The QBR insight funnel: overall headline -> product pages -> country page.

Each test pins one root cause behind the "one thin pointer" Overall box:

1. the overall pack carried no per-line share of wallet or rank, so the draft's richest
   lines were uncitable and the number check removed them;
2. segment findings were narrowed against a parent page the deck never shows, so a
   single-country run lost every industry / client-segment finding;
3. the headline box owned nothing in the editorial plan, so it lost every shared claim
   to a field on a later page;
4. the plan's ownership never reached the prompt, so the writer could not avoid the
   repeats the gate then deleted;
5. the prompt said "use fewer" while the acceptance gate wanted a full box, and the
   country page's cells were asked for only as many bullets as their thinned draft.
"""

from __future__ import annotations

import pytest

from studio.template_fill import commentary as CM
from studio.template_fill import commentary_batch as B
from studio.template_fill import commentary_findings as FI
from studio.template_fill import editorial as E
from studio.template_fill import feedback as F
from studio.template_fill.commentary_evidence import build_pack


def _lines() -> list[dict]:
    """Rows of the shape ``feedback._line_facts`` returns."""
    return [
        {
            "name": "Cyber",
            "current": 44_000_000.0,
            "prior": 22_000_000.0,
            "delta": 22_000_000.0,
            "pct": 97.3,
            "sow": 14.7,
            "sow_prior": 8.5,
            "pool": 300_000_000.0,
            "pool_pct": 13.5,
            "rank": 1,
            "of_n": 12,
            "prior_rank": 6,
        },
        {
            "name": "Financial Lines",
            "current": 44_300_000.0,
            "prior": 28_200_000.0,
            "delta": 16_100_000.0,
            "pct": 57.1,
            "sow": 10.7,
            "sow_prior": 7.7,
            "pool": 414_000_000.0,
            "pool_pct": 13.2,
            "rank": 3,
            "of_n": 12,
            "prior_rank": 6,
        },
        {
            "name": "Property",
            "current": 40_000_000.0,
            "prior": 35_600_000.0,
            "delta": 4_400_000.0,
            "pct": 12.1,
            "sow": 7.3,
            "sow_prior": 7.1,
            "pool": 545_000_000.0,
            "pool_pct": 8.5,
            "rank": 6,
            "of_n": 12,
            "prior_rank": 7,
        },
        {
            "name": "Casualty",
            "current": 37_000_000.0,
            "prior": 37_100_000.0,
            "delta": -100_000.0,
            "pct": -0.4,
            "sow": 7.6,
            "sow_prior": 8.4,
            "pool": 480_000_000.0,
            "pool_pct": 10.2,
            "rank": 6,
            "of_n": 12,
            "prior_rank": 6,
        },
    ]


def _facts(lines: list[dict] | None = None) -> dict:
    return {
        "subject": "Zurich",
        "carrier": {
            "current": 208_000_000.0,
            "prior": 162_000_000.0,
            "delta": 46_000_000.0,
            "pct": 28.6,
            "current_year": 2025,
            "prior_year": 2024,
        },
        "marsh": {"current": 2_300_000_000.0, "prior": 2_100_000_000.0, "pct": 9.9},
        "sow": {"current": 9.1, "prior": 7.8, "delta": 1.3},
        "rank": {"current": 5, "of_n": 12, "delta": 1},
        "peer": {"sow": 10.8, "current": 247_000_000.0, "benchmark_count": 5},
        "lines": _lines() if lines is None else lines,
    }


# ── 1. the overall pack can cite product share of wallet ─────────────────────


def test_every_line_is_a_citable_fact_with_its_share_and_rank():
    pack = build_pack(_facts())
    cyber = pack.get("line.cyber")
    assert cyber is not None
    for figure in ("$44M", "97.3%", "14.7%", "8.5%", "#1 of 12", "5 places", "#6"):
        assert figure in cyber.rendered, (figure, cyber.rendered)
    assert cyber.value == pytest.approx(14.7 - 8.5), "the value is the share MOVE"


def test_the_portfolio_claims_the_draft_makes_are_now_evidence():
    pack = build_pack(_facts())
    assert (
        "2 of 4 lines (Cyber, Financial Lines)" in pack.get("portfolio.top5").rendered
    )
    share_range = pack.get("portfolio.share_range").rendered
    assert "Cyber at 14.7%" in share_range and "Property at 7.3%" in share_range
    assert (
        "furthest in Cyber, up 5 places from #6 to #1"
        in pack.get("portfolio.rank_moves").rendered
    )


def test_a_one_line_scope_carries_no_line_family():
    pack = build_pack(_facts(lines=[]))
    assert not [e for e in pack.items if e.fact_id.startswith(("line.", "portfolio."))]


def test_a_product_page_scope_builds_no_line_rows():
    class _Result:
        subject = "Zurich"

    assert (
        F._line_facts(_Result(), {"Product_Line": "Cyber", "Country": "Singapore"})
        == []
    )


# ── the headline box is offered the headline, in the page's order ────────────


def test_the_headline_box_is_offered_its_tiles_then_the_lines():
    findings = FI.for_topic(build_pack(_facts()), "thesis")
    leads = [f.fact_ids[0] for f in findings]
    assert leads[:3] == ["carrier.yoy", "sow.delta", "rank.current"]
    assert any(fid.startswith("portfolio.") for fid in leads), leads
    assert leads.index("rank.current") < leads.index("peer.gap"), (
        "rank is a tile; it leads"
    )


def test_a_line_that_lost_share_is_offered_to_challenges_not_successes():
    pack = build_pack(_facts())
    challenge_ids = {
        fid for f in FI.for_topic(pack, "challenges", limit=10) for fid in f.fact_ids
    }
    working_ids = {
        fid for f in FI.for_topic(pack, "working", limit=10) for fid in f.fact_ids
    }
    assert "line.casualty" in challenge_ids
    assert "line.casualty" not in working_ids


# ── 2. narrowing compares with a page the reader actually sees ───────────────


def test_a_single_country_run_has_no_parent_above_its_country():
    assert F._parent_filters({"Country": "Singapore"}, ("Singapore",)) is None


def test_a_product_page_on_a_single_country_run_sits_under_the_overall_page():
    parent = F._parent_filters(
        {"Country": "Singapore", "Product_Line": "Cyber"}, ("Singapore",)
    )
    assert parent == {"Country": "Singapore"}


def test_a_country_on_a_multi_country_run_sits_under_the_runs_markets():
    parent = F._parent_filters({"Country": "Japan"}, ("Singapore", "Japan"))
    assert parent == {"Country": ["Singapore", "Japan"]}


def test_an_unknown_run_keeps_the_old_reading():
    assert F._parent_filters({"Country": "Japan", "Year": 2025}) == {"Year": 2025}


# ── 3. the headline box owns its findings ────────────────────────────────────


def _column(topic: str, page: int, value_set: int = 0) -> B.Column:
    return B.Column(
        field_id=f"{page}.{topic}",
        targets=(B.Target(value_set, f"note:{page}:1:0"),),
        topic=topic,
        node=f"p{page}-{topic}",
        bullets=4,
    )


def test_a_lone_headline_box_is_the_home_for_what_it_leads_from():
    headline = (_column("thesis", 2),)
    later = (
        _column("working", 3),
        _column("key_messages", 3),
        _column("challenges", 3),
    )
    plan = E.plan_deck([headline + later])
    owns = plan.fields["2.thesis"].owns
    assert {"scale", "standing", "lines"} <= set(owns)
    assert "THIS FIELD IS THE HOME FOR" in plan.brief("2.thesis")


def test_the_headline_keeps_a_shared_claim_over_a_later_page():
    """The single-country failure: the country page owned 'standing' and the headline,
    owning nothing, lost its rank line to it."""
    headline = (_column("thesis", 2),)
    later = (_column("key_messages", 3), _column("working", 3))
    plan = E.plan_deck([headline + later])
    later_owner = next(
        fid
        for fid, fp in plan.fields.items()
        if fid != "2.thesis" and "standing" in fp.owns
    )
    kept, dropped = E.dedupe(
        [
            ("2.thesis", "Zurich ranks #5 of 12 in the Marsh book.", ("rank.current",)),
            (later_owner, "Rank improved to #5 of 12.", ("rank.current",)),
        ],
        plan=plan,
    )
    assert kept["2.thesis"], "the headline lost its own KPI to a later page"
    assert [r.field_id for r in dropped] == [later_owner]


# ── 4. the writer is told the allocation the gate applies ────────────────────


def test_the_prompt_carries_each_fields_ownership():
    pack = build_pack(_facts())
    columns = (_column("thesis", 2), _column("key_messages", 3), _column("working", 3))
    section = B.Section(
        label="book0", subject="Zurich", style="balanced", columns=columns
    )
    plan = E.plan_deck([columns])
    payload = B.section_payload(section, pack, "", plan=plan)
    thesis_block = payload.split("--- FIELD 2.thesis ---")[1].split("--- FIELD")[0]
    assert "THIS FIELD IS THE HOME FOR" in thesis_block
    assert "MATERIAL AVAILABLE TO THIS SECTION" in thesis_block
    assert "ALREADY MADE EARLIER IN THIS DECK" in payload


# ── 5. the ask matches the box ───────────────────────────────────────────────


def test_a_full_box_is_asked_to_be_filled():
    rules = CM.column_rules("thesis", 4)
    assert "Write 4 independent bullets" in rules
    assert "account headline" in rules
    assert "share of wallet is deepest or thinnest" in rules


def test_a_one_line_panel_is_not_briefed_as_the_pages_thesis():
    rules = CM.column_rules("challenges", 1)
    assert "ONE PARAGRAPH" not in rules
    assert "Write ONE bullet" in rules


def test_a_country_cell_is_asked_for_its_room_not_its_thinned_draft():
    pending = F._polish(
        "Share fell in Casualty.", "challenges", "balanced", "Zurich", {}, capacity=3
    )
    assert pending.capacity == 3


# ── end to end on the seed book: selection -> plan -> the prompt the model gets ──


@pytest.fixture(scope="module")
def singapore_overall_prompt():
    import os

    from studio.compute import compute_overall
    from studio.data import get_engine
    from studio.template_fill import assemble

    os.environ["STUDIO_AI"] = "off"
    result = compute_overall(
        flow="gpr",
        engine=get_engine(),
        filters={"carrier": "Zurich", "country": "Singapore", "year": 2025},
    )
    planned = assemble.plan_unwritten(result)
    sections = B.group_sections([sub.values for sub in planned])
    plan = E.plan_deck(
        [s.columns for s in sections], markets=[B.section_markets(s) for s in sections]
    )
    overall = next(s for s in sections if any(c.topic == "thesis" for c in s.columns))
    pack = B._pack_for(overall)
    return overall, pack, plan, B.section_payload(overall, pack, "", plan=plan)


def test_a_single_country_overall_cites_product_share_of_wallet(
    singapore_overall_prompt,
):
    _, pack, _, payload = singapore_overall_prompt
    assert (
        pack.get("line.cyber") is not None
        and pack.get("portfolio.share_range") is not None
    )
    thesis = payload.split("--- FIELD thesis.0 ---")[1].split("--- FIELD")[0]
    assert "Write 4 independent bullets" in thesis
    assert "portfolio.share_range" in thesis and "rank.current" in thesis


def test_a_single_country_run_keeps_its_industry_findings(singapore_overall_prompt):
    """Narrowed against the carrier's global book, these were all removed."""
    _, pack, _, _ = singapore_overall_prompt
    assert [
        e
        for e in pack.items
        if e.fact_id.startswith("segment.") and e.fact_id.count(".") == 3
    ]


def test_the_country_page_is_not_asked_for_one_line(singapore_overall_prompt):
    overall, _, plan, _ = singapore_overall_prompt
    country = [c for c in overall.columns if c.node.startswith("feedback-")]
    assert country, "single-country: the country page shares the overall book"
    assert all(c.bullets >= 2 for c in country), [(c.node, c.bullets) for c in country]
    assert plan.fields["thesis.0"].owns, "the headline box owns its findings"
