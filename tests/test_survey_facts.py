"""Survey seed data + the deterministic survey queries behind the Carrier Survey page."""
from __future__ import annotations

import pytest

from core.analytics.library import compute_breakdown
from core.analytics.types import PrimitiveArgs
from studio import seed as S


@pytest.fixture(scope="module")
def seeded():
    """The seed DB's engine. Injected explicitly so the suite needs no DB_PATH — the
    repo convention (see tests/test_studio_qbr_generation.py), and the reason these
    tests do not depend on whatever database the developer happens to have configured."""
    from studio.data import get_engine

    S.ensure_seed_db()
    return get_engine()


def test_seed_has_survey_rows(seeded):
    facts = compute_breakdown(
        PrimitiveArgs(flow="survey", metric="score", group_by=("Sections",),
                      filters={"Carrier": S.SUBJECT, "SurveyCountry": "Singapore",
                               "Survey_Year": 2025}),
        engine=seeded,
    )
    sections = {f.dims["Sections"] for f in facts}
    assert sections == set(S.SURVEY_SECTIONS)
    assert all(5.0 <= f.value <= 8.0 for f in facts)


def test_seed_survey_scores_move_year_on_year(seeded):
    def score(year):
        facts = compute_breakdown(
            PrimitiveArgs(flow="survey", metric="score", group_by=("Sections", "SurveyPractice"),
                          filters={"Carrier": S.SUBJECT, "SurveyCountry": "Singapore",
                                   "Survey_Year": year}),
            engine=seeded,
        )
        return {(f.dims["Sections"], f.dims["SurveyPractice"]): f.value for f in facts}

    now, prior = score(2025), score(2024)
    deltas = [now[k] - prior[k] for k in now if k in prior]
    assert deltas, "no comparable cells between 2025 and 2024"
    # The drift table must exercise the whole band range, not just the neutral one.
    assert max(deltas) >= 1.0
    assert min(deltas) <= -1.0


def test_seed_peers_table_serves_both_flows(seeded):
    from studio.data import peer_members

    assert peer_members("gpr", S.SUBJECT, country="Singapore")
    assert peer_members("survey", S.SUBJECT, country="Singapore")
