"""Who the subject is in the SURVEY book — the two books name carriers differently.

The premium book groups carriers (``Carrier_Group``: "Zurich"); the survey book records the
entity that was surveyed (``Carrier``: "Zurich Insurance Company Ltd"). A deck is driven
from the premium side, so asking the survey book for the subject verbatim found nothing —
an empty page — or, worse, another carrier's rows reported under this carrier's name.

Hermetic: a small Carriers table per case, no seed DB, no LLM.
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine

from studio.compute import OverallResult
from studio.template_fill.survey import identity


def _book(tmp_path, carriers, *, country="Singapore", name="book.db"):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    rows = [{"SurveyCountry": country, "Carrier": carrier, "SurveyPractice": "CE/CM",
             "Sections": "Underwriting", "Survey_Year": 2025, "Score": 6.0}
            for carrier in carriers]
    pd.DataFrame(rows).to_sql("Carriers", engine, index=False, if_exists="replace")
    return engine


def _result(engine, subject, **kw):
    return OverallResult(subject=subject, flow="gpr", engine=engine,
                         resolved_filters={"Country": "Singapore"}, **kw)


# ── resolving the subject ────────────────────────────────────────────────────


@pytest.mark.parametrize("stored", [
    "Zurich",                               # identical
    "ZURICH",                               # case
    "Zurich Insurance Company Ltd",         # the entity behind the group
    "Zurich Insurance (Singapore) Pte Ltd",
    "Zurich  Insurance   Co.",              # punctuation and spacing
])
def test_the_premium_group_finds_its_carrier_in_the_survey_book(tmp_path, stored):
    engine = _book(tmp_path, [stored, "AIG Asia Pacific Pte Ltd"], name=f"{abs(hash(stored))}.db")
    assert identity.resolve_carrier(_result(engine, "Zurich"), ("Singapore",)) == stored


def test_a_carrier_the_book_does_not_survey_resolves_to_nothing(tmp_path):
    """``None`` is the answer that prevents the real failure: a survey page built from
    whoever matched loosely, reported under this carrier's name."""
    engine = _book(tmp_path, ["AIG Asia Pacific Pte Ltd", "Chubb Ltd"])
    assert identity.resolve_carrier(_result(engine, "Zurich"), ("Singapore",)) is None


def test_two_different_carriers_are_never_confused(tmp_path):
    engine = _book(tmp_path, ["AIG Asia Pacific Pte Ltd"])
    assert identity.resolve_carrier(_result(engine, "AXA XL"), ("Singapore",)) is None


def test_the_corporate_form_alone_is_not_a_match(tmp_path):
    """"Insurance Company Ltd" is on every row in the book and identifies nothing."""
    engine = _book(tmp_path, ["Tokio Marine Insurance Company Ltd"])
    assert identity.resolve_carrier(_result(engine, "Insurance Company Ltd"),
                                    ("Singapore",)) is None


def test_a_pinned_carrier_wins_over_the_match(tmp_path):
    """Setup shows the match it would make; the author has seen both lists and decides."""
    engine = _book(tmp_path, ["Zurich Insurance Company Ltd", "Zurich Global Corporate"])
    result = _result(engine, "Zurich", survey_carrier="Zurich Global Corporate")
    assert identity.resolve_carrier(result, ("Singapore",)) == "Zurich Global Corporate"


def test_the_scope_narrows_who_can_be_matched(tmp_path):
    """A carrier surveyed in Japan but not Singapore must not answer a Singapore page."""
    engine = create_engine(f"sqlite:///{tmp_path / 'scoped.db'}")
    pd.DataFrame([
        {"SurveyCountry": "Japan", "Carrier": "Zurich Insurance Company Ltd",
         "SurveyPractice": "CE/CM", "Sections": "Underwriting", "Survey_Year": 2025,
         "Score": 6.0},
    ]).to_sql("Carriers", engine, index=False, if_exists="replace")
    result = _result(engine, "Zurich")
    assert identity.resolve_carrier(result, ("Japan",)) == "Zurich Insurance Company Ltd"
    assert identity.resolve_carrier(result, ("Singapore",)) is None


def test_the_options_are_the_book_s_own_names(tmp_path):
    engine = _book(tmp_path, ["Chubb Ltd", "AIG Asia Pacific Pte Ltd"])
    assert identity.carrier_options(_result(engine, "Zurich"), ("Singapore",)) == (
        "AIG Asia Pacific Pte Ltd", "Chubb Ltd")


# ── resolving the peers ──────────────────────────────────────────────────────


def test_peers_pinned_on_the_premium_side_are_matched_into_the_survey_book(tmp_path):
    """A premium peer set names carrier GROUPS. Dropping them left the ribbon with one box;
    matching them means a Setup peer choice says the same thing on both pages."""
    engine = _book(tmp_path, ["Zurich Insurance Company Ltd", "AIG Asia Pacific Pte Ltd",
                              "Chubb Ltd"])
    result = _result(engine, "Zurich", peers=("AIG", "Chubb"))
    assert identity.resolve_peers(result, "Zurich Insurance Company Ltd", ("Singapore",)) == (
        "AIG Asia Pacific Pte Ltd", "Chubb Ltd")


def test_survey_peers_pinned_in_setup_win_over_the_premium_ones(tmp_path):
    engine = _book(tmp_path, ["Zurich Insurance Company Ltd", "AIG Asia Pacific Pte Ltd",
                              "Chubb Ltd"])
    result = _result(engine, "Zurich", peers=("AIG",), survey_peers=("Chubb Ltd",))
    assert identity.resolve_peers(result, "Zurich Insurance Company Ltd", ("Singapore",)) == (
        "Chubb Ltd",)


def test_a_pinned_peer_the_book_never_surveyed_is_dropped_not_guessed(tmp_path):
    engine = _book(tmp_path, ["Zurich Insurance Company Ltd", "Chubb Ltd"])
    result = _result(engine, "Zurich", peers=("Chubb", "Some Mutual Nobody Surveyed"))
    assert identity.resolve_peers(result, "Zurich Insurance Company Ltd", ("Singapore",)) == (
        "Chubb Ltd",)


def test_the_subject_is_never_its_own_peer(tmp_path):
    engine = _book(tmp_path, ["Zurich Insurance Company Ltd", "Chubb Ltd"])
    result = _result(engine, "Zurich", peers=("Zurich", "Chubb"))
    assert identity.resolve_peers(result, "Zurich Insurance Company Ltd", ("Singapore",)) == (
        "Chubb Ltd",)


def test_no_pinned_peers_means_no_opinion(tmp_path):
    """An empty answer sends the ribbon to the Peers table, then to the surveyed field."""
    engine = _book(tmp_path, ["Zurich Insurance Company Ltd", "Chubb Ltd"])
    assert identity.resolve_peers(_result(engine, "Zurich"),
                                  "Zurich Insurance Company Ltd", ("Singapore",)) == ()
