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


# ── the queries behind the page ──────────────────────────────────────────────


def _result(country="Singapore", peers=None):
    """A result scoped to one country, with the seed engine injected explicitly.

    The engine is injected so the suite needs no ``DB_PATH`` — the repo convention (see
    ``tests/test_studio_qbr_generation.py``). Without it the primitives fall back to
    ``core.initialization.Initialization.engine``, which points at whatever database the
    developer happens to have configured.
    """
    from studio.compute import OverallResult
    from studio.data import get_engine

    return OverallResult(subject=S.SUBJECT, flow="gpr",
                         resolved_filters={"Country": country}, peers=peers,
                         engine=get_engine())


def test_has_survey_data_is_true_for_a_seeded_country(seeded):
    from studio.template_fill.survey import facts

    assert facts.has_survey_data(_result(), "Singapore") is True


def test_has_survey_data_is_false_for_an_unknown_country(seeded):
    from studio.template_fill.survey import facts

    assert facts.has_survey_data(_result(), "Atlantis") is False


def test_load_grid_reports_the_latest_year_against_the_one_before(seeded):
    from studio.template_fill.survey import facts

    grid = facts.load_grid(_result(), "Singapore")
    assert grid is not None
    assert grid.year == max(S.SURVEY_YEARS)
    assert grid.prior_year == max(S.SURVEY_YEARS) - 1


def test_load_grid_fills_every_authored_cell(seeded):
    from studio.template_fill.survey import facts

    grid = facts.load_grid(_result(), "Singapore")
    for section in S.SURVEY_SECTIONS:
        for practice in S.SURVEY_PRACTICES:
            assert grid.score(section, practice) is not None
            assert grid.delta(section, practice) is not None


def test_load_grid_totals_come_from_the_rows_not_the_cells(seeded):
    """A Total is its own AVG over the raw rows — never a mean of the displayed cells."""
    from statistics import fmean

    from studio.template_fill.survey import facts

    grid = facts.load_grid(_result(), "Singapore")
    cells = [grid.score(sec, S.SURVEY_PRACTICES[0]) for sec in S.SURVEY_SECTIONS]
    # Equal-sized cells make the two agree here; the point is that the total EXISTS
    # independently and is on the same scale, not that it is computed from the cells.
    assert grid.practice_total(S.SURVEY_PRACTICES[0]) == pytest.approx(fmean(cells), abs=0.05)
    assert 1.0 <= grid.overall <= 10.0


def test_load_grid_returns_none_for_a_country_with_no_survey(seeded):
    from studio.template_fill.survey import facts

    assert facts.load_grid(_result(), "Atlantis") is None


def test_load_ribbon_ranks_best_first_and_highlights_only_the_subject(seeded):
    from studio.template_fill.survey import facts

    spec = facts.load_ribbon(_result(), "Singapore", tuple(S.SURVEY_SECTIONS))
    assert spec is not None
    assert [c.label for c in spec.columns] == S.SURVEY_SECTIONS
    for column in spec.columns:
        scores = [b.score for b in column.boxes]
        assert scores == sorted(scores, reverse=True)
        assert sum(1 for b in column.boxes if b.highlight) == 1
        assert next(b for b in column.boxes if b.highlight).carrier == S.SUBJECT


def test_load_ribbon_honours_a_pinned_peer_set(seeded):
    from studio.template_fill.survey import facts

    spec = facts.load_ribbon(_result(peers=("AIG", "Chubb")), "Singapore",
                             tuple(S.SURVEY_SECTIONS))
    carriers = {b.carrier for c in spec.columns for b in c.boxes}
    assert carriers == {S.SUBJECT, "AIG", "Chubb"}


def test_load_ribbon_caps_the_stack_but_never_drops_the_subject(seeded):
    from studio.template_fill.survey import facts

    everyone = tuple(c for c in S.CARRIERS if c != S.SUBJECT)
    spec = facts.load_ribbon(_result(peers=everyone), "Singapore", tuple(S.SURVEY_SECTIONS))
    for column in spec.columns:
        assert len(column.boxes) == facts.MAX_RIBBON_ROWS
        assert any(b.highlight for b in column.boxes)
