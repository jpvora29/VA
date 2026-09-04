"""Peer confidentiality is enforced in code, at the evidence boundary.

The rule: an answer may name the subject carrier and Marsh, and may never name an
individual peer. It used to live only in two system prompts, so it held only when
the model felt like it — and the data table under a chart and the chart's own
axis labels never saw a prompt at all.
"""
from __future__ import annotations

import pytest

from core.agents.common.peer_privacy import (
    ALWAYS_NAMEABLE,
    PeerPolicy,
    PeerRedactor,
    build_policy,
    redact_text,
    redacted_names,
    redactor_for,
    registry_identity_columns,
    subjects_from_resolved,
)


@pytest.fixture
def redactor():
    """A turn about ZURICH GROUP on the premium flow."""
    return PeerRedactor(build_policy("gpr", ["ZURICH GROUP"]))


PEER_ROWS = [
    {"Carrier_Group": "ZURICH GROUP", "Premium": 12_400_000},
    {"Carrier_Group": "AIG", "Premium": 9_100_000},
    {"Carrier_Group": "CHUBB", "Premium": 8_000_000},
]


# ── rows ─────────────────────────────────────────────────────────────────────

def test_individual_peers_are_anonymised(redactor):
    names = [r["Carrier_Group"] for r in redactor.rows(PEER_ROWS)]
    assert names == ["ZURICH GROUP", "Peer 1", "Peer 2"]


def test_the_numbers_are_never_touched(redactor):
    """Anonymising, not aggregating — every figure survives exactly."""
    out = redactor.rows(PEER_ROWS)
    assert [r["Premium"] for r in out] == [12_400_000, 9_100_000, 8_000_000]


def test_the_subject_keeps_its_name(redactor):
    assert redactor.rows(PEER_ROWS)[0]["Carrier_Group"] == "ZURICH GROUP"


def test_marsh_is_nameable_as_the_market_proxy(redactor):
    out = redactor.rows([{"Carrier_Group": "Marsh", "Premium": 1}])
    assert out[0]["Carrier_Group"] == "Marsh"
    assert "marsh" in ALWAYS_NAMEABLE


def test_a_peer_keeps_one_label_across_calls(redactor):
    """One redactor per solver, so a peer reads the same way all answer long."""
    first = redactor.rows([{"Carrier_Group": "AIG", "Premium": 1}])
    second = redactor.rows([{"Carrier_Group": "AIG", "Premium": 2}])
    assert first[0]["Carrier_Group"] == second[0]["Carrier_Group"] == "Peer 1"


def test_case_and_spacing_do_not_create_a_second_label(redactor):
    out = redactor.rows([{"Carrier_Group": "AIG"}, {"Carrier_Group": "  aig "}])
    assert out[0]["Carrier_Group"] == out[1]["Carrier_Group"] == "Peer 1"


def test_the_peer_membership_lookup_is_defanged(redactor):
    """The exact query whose rows used to surface as the answer's table."""
    rows = [{"Overall_Peer_Group": "AIG"}, {"Overall_Peer_Group": "CHUBB"}]
    assert [r["Overall_Peer_Group"] for r in redactor.rows(rows)] == ["Peer 1", "Peer 2"]


def test_measure_columns_pass_through_untouched(redactor):
    row = {"Year": 2025, "Product_Line": "Property", "Premium": 5, "Country": "Canada"}
    assert redactor.rows([row])[0] == row


def test_a_computed_peer_average_is_unchanged(redactor):
    """The primitive already returns a peer COUNT and no name.

    Regression: the column regex matches `peer_average` and `peers` (it must stay
    loose enough to catch an invented `AS competitor` alias), so without the
    "an identity is text" guard the benchmark's own FIGURE was replaced by a
    label — silently destroying the number the comparison exists to report.
    """
    rows = [{"peer_average": 9_800_000, "peers": 6}]
    assert redactor.rows(rows) == rows
    assert redactor.redacted == ()


def test_a_numeric_value_in_an_identity_column_is_never_a_name(redactor):
    rows = [{"peer_average": "9800000.0", "peer_count": 6, "Carrier_Group": "AIG"}]
    out = redactor.rows(rows)[0]
    assert out["peer_average"] == "9800000.0"
    assert out["peer_count"] == 6
    assert out["Carrier_Group"] == "Peer 1"


def test_sql_aliases_are_caught_even_though_the_registry_cannot_know_them(redactor):
    """A solver writing `SELECT Carrier_Group AS competitor` must not slip past."""
    for alias in ("peer", "peer_name", "competitor", "insurer"):
        out = PeerRedactor(build_policy("gpr", ["ZURICH GROUP"])).rows([{alias: "AIG"}])
        assert out[0][alias] == "Peer 1", alias


def test_non_dict_rows_and_nulls_survive(redactor):
    assert redactor.rows([["raw"], None, {"Carrier_Group": None}]) == [
        ["raw"],
        None,
        {"Carrier_Group": None},
    ]
    assert redactor.rows([]) == []


# ── prose ────────────────────────────────────────────────────────────────────

def test_a_leaked_name_in_prose_becomes_its_label(redactor):
    redactor.rows(PEER_ROWS)
    text = redactor.text("AIG outgrew ZURICH GROUP while CHUBB lagged; Marsh is the market.")
    assert text == "Peer 1 outgrew ZURICH GROUP while Peer 2 lagged; Marsh is the market."


def test_a_peer_name_inside_the_subjects_name_does_not_corrupt_it():
    """The substring trap: subject "AXA XL", peer "AXA"."""
    r = PeerRedactor(build_policy("gpr", ["AXA XL"]))
    r.rows([{"Carrier_Group": "AXA XL"}, {"Carrier_Group": "AXA"}])
    assert r.text("AXA XL grew while AXA fell.") == "AXA XL grew while Peer 1 fell."


def test_a_name_with_no_label_falls_back_to_a_peer():
    """The writer_node scrub has no alias map to restore."""
    policy = build_policy("gpr", ["ZURICH GROUP"])
    out = redact_text("AIG led the market.", ["AIG"], policy)
    assert out == "a peer led the market."


def test_scrubbing_never_matches_inside_a_longer_word():
    policy = build_policy("gpr", [])
    assert redact_text("AIGON is unrelated.", ["AIG"], policy) == "AIGON is unrelated."


def test_nothing_to_scrub_returns_the_text_unchanged():
    policy = build_policy("gpr", ["ZURICH GROUP"])
    assert redact_text("All quiet.", [], policy) == "All quiet."
    assert redact_text("", ["AIG"], policy) == ""


# ── policy construction ──────────────────────────────────────────────────────

def test_identity_columns_come_from_the_flow_registry():
    """Registry-driven, so a schema rename moves this with it."""
    assert {"Carrier_Group", "Overall_Peer_Group"} <= set(registry_identity_columns("gpr"))
    assert "Carrier" in registry_identity_columns("survey")


def test_an_unknown_flow_still_gets_the_regex_safety_net():
    policy = build_policy("nope", [])
    assert registry_identity_columns("nope") == frozenset()
    assert policy.is_identity_column("Carrier_Group")


def test_the_subject_is_read_off_the_grounded_slice():
    resolved = {"Carrier_Group": ["ZURICH GROUP"], "Country": ["Canada"]}
    assert subjects_from_resolved(resolved, "gpr") == ("ZURICH GROUP",)


def test_a_head_to_head_question_may_name_both_carriers():
    resolved = {"Carrier_Group": ["ZURICH GROUP", "AIG"]}
    r = PeerRedactor(build_policy("gpr", subjects_from_resolved(resolved, "gpr")))
    out = r.rows([{"Carrier_Group": "AIG"}, {"Carrier_Group": "CHUBB"}])
    assert out[0]["Carrier_Group"] == "AIG"
    assert out[1]["Carrier_Group"] == "Peer 1"


def test_a_pinned_custom_peer_set_still_names_its_subject():
    r = redactor_for("gpr", {}, {"carrier": "ZURICH GROUP", "peers": ["AIG"]})
    assert r.rows([{"Carrier_Group": "ZURICH GROUP"}])[0]["Carrier_Group"] == "ZURICH GROUP"


def test_subjects_from_an_empty_or_missing_slice():
    assert subjects_from_resolved(None, "gpr") == ()
    assert subjects_from_resolved({}, "gpr") == ()


def test_an_empty_policy_still_protects():
    """A turn with no resolved subject treats every carrier as a peer."""
    assert PeerPolicy().is_identity_column("Carrier_Group")
    assert not PeerPolicy().may_name("AIG")
    assert PeerPolicy().may_name("Marsh")


# ── the vocabulary carried to the writer ─────────────────────────────────────

def test_redacted_names_unions_across_evidence():
    evidence = [
        {"rows": [], "redacted_peers": ("AIG", "CHUBB")},
        {"rows": [], "redacted_peers": ("CHUBB", "AXA XL")},
        {"rows": []},
    ]
    assert redacted_names(evidence) == ("AIG", "CHUBB", "AXA XL")


def test_redacted_names_tolerates_junk():
    assert redacted_names([]) == ()
    assert redacted_names([None, "x", {"rows": []}]) == ()
