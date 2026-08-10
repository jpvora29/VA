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


# ── _capped, in isolation ─────────────────────────────────────────────────────
#
# The DB-backed test above exercises `load_ribbon`'s cap end to end, but with the
# seeded data Zurich always lands inside the top MAX_RIBBON_ROWS anyway (rank 5 of 12
# in Underwriting/2025/Singapore), so plain `boxes[:MAX_RIBBON_ROWS]` truncation already
# keeps it — the swap-in branch (`kept[-1] = subject; kept.sort(...)`) never runs there.
# These tests force the subject below the cap by hand so that branch is actually covered,
# independent of wherever a seeded carrier happens to rank.


def test_capped_keeps_the_subject_when_it_ranks_below_the_cap():
    from studio.template_fill.survey import facts
    from studio.template_fill.survey.ribbon import RibbonBox

    # 11 peers, best-score-first, then the subject last — below the cap.
    peers = [RibbonBox(f"Peer{i}", float(12 - i)) for i in range(11)]  # scores 12..2
    subject = RibbonBox("Zurich", 1.0, highlight=True)
    boxes = peers + [subject]

    capped = facts._capped(boxes)

    # Exactly MAX_RIBBON_ROWS boxes, still best-score-first.
    assert len(capped) == facts.MAX_RIBBON_ROWS
    scores = [b.score for b in capped]
    assert scores == sorted(scores, reverse=True)

    # The subject is present, and only once.
    assert sum(1 for b in capped if b.highlight) == 1
    assert next(b for b in capped if b.highlight).carrier == "Zurich"

    # The displaced box is the lowest-scoring PEER that was inside the original
    # top-MAX_RIBBON_ROWS window (Peer8, score 4) — not some other peer.
    displaced = peers[facts.MAX_RIBBON_ROWS - 1]
    assert displaced not in capped
    for kept_peer in peers[: facts.MAX_RIBBON_ROWS - 1]:
        assert kept_peer in capped
    # Peers that were never inside the cap stay excluded too.
    for excluded_peer in peers[facts.MAX_RIBBON_ROWS:]:
        assert excluded_peer not in capped


def test_capped_passes_through_unchanged_at_or_under_the_cap():
    from studio.template_fill.survey import facts
    from studio.template_fill.survey.ribbon import RibbonBox

    at_cap = tuple(RibbonBox(f"Peer{i}", float(9 - i), highlight=(i == 3))
                    for i in range(facts.MAX_RIBBON_ROWS))
    assert facts._capped(at_cap) == at_cap

    under_cap = at_cap[:5]
    assert facts._capped(under_cap) == under_cap


# ── the section column is spelled BOTH ways in the wild ──────────────────────
#
# A live Carriers table names the column ``Section``; the seed DB (and this repo's own
# fixtures) name it ``Sections``. The physical name is resolved at runtime, but the flow
# registry ALSO has to declare it — ``core.analytics.sql.safe_column`` refuses any
# identifier the flow does not list, so a warehouse using the undeclared spelling had every
# cut of the survey page fail with "unknown column 'Section' for flow survey" and shipped an
# empty page.


_CARRIERS = (S.SUBJECT, "Other Carrier", "Third Carrier")


def _carriers_db(path, section_column: str, *, sections=("Underwriting", "Claims"),
                 practices=("Property", "Casualty"), peers=None):
    """A one-country Carriers table, with control over the things live warehouses vary.

    ``section_column`` is the physical column name, ``sections``/``practices`` the values
    it actually holds (which need not be spelled the way a template's axis is), and
    ``peers`` the Peers-table rows (``None`` = the subject's own curated group).
    """
    import pandas as pd
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{path}")
    rows = [{"Region": "Asia", "SurveyCountry": "Singapore", "Carrier": carrier,
             "SurveyPractice": practice, section_column: section, "Attributes": "Overall",
             "SurveySegment": "Large", "Survey_Year": year,
             "Score": score + (0.6 if year == 2025 else 0.0),
             "NPS Score": score}
            for carrier, score in zip(_CARRIERS, (7.0, 6.0, 5.0))
            for practice in practices
            for section in sections
            for year in (2024, 2025)]
    pd.DataFrame(rows).to_sql("Carriers", engine, index=False, if_exists="replace")
    if peers is None:
        peers = [{"Carrier": S.SUBJECT, "Peers": "Other Carrier", "Country": "Singapore"}]
    pd.DataFrame(peers).to_sql("Peers", engine, index=False, if_exists="replace")
    return engine


def _result_on(engine):
    from studio.compute import OverallResult

    return OverallResult(subject=S.SUBJECT, flow="gpr",
                         resolved_filters={"Country": "Singapore"}, engine=engine)


@pytest.mark.parametrize("spelling", ["Sections", "Section"])
def test_either_spelling_of_the_section_column_builds_the_page(tmp_path, spelling):
    from studio.template_fill.survey import facts

    result = _result_on(_carriers_db(tmp_path / f"{spelling}.db", spelling))
    assert facts.section_column(result) == spelling
    assert facts.has_survey_data(result, "Singapore") is True
    grid = facts.load_grid(result, "Singapore")
    assert grid is not None and grid.score("Underwriting", "Property") is not None
    assert facts.load_overall_score(result, ("Singapore",)) is not None


def test_the_registry_declares_every_spelling_the_resolver_may_pick():
    """The resolver picks a PHYSICAL name; the identifier allowlist has to accept it, or
    every query built from it is refused."""
    from core.analytics.sql import flow_spec, safe_column
    from studio.template_fill.survey import facts

    spec = flow_spec("survey")
    for spelling in facts.SECTION_CANDIDATES:
        assert safe_column(spec, spelling) == spelling


def test_a_spelling_the_registry_does_not_declare_is_not_used(tmp_path, monkeypatch):
    """Rather than building a query the allowlist will refuse, the page stands down — the
    warning names the undeclared column, which is the fix a deployment can act on."""
    from studio.template_fill.survey import facts

    result = _result_on(_carriers_db(tmp_path / "undeclared.db", "SectionName"))
    monkeypatch.setattr(facts, "SECTION_CANDIDATES", ("Sections", "Section", "SectionName"))
    assert facts.section_column(result) is None
    assert facts.has_survey_data(result, "Singapore") is False


# ── the template's wording vs the warehouse's wording ────────────────────────
#
# The page's axes are the template's authored labels; the numbers are keyed by the
# warehouse's own values. Matching them raw meant one stray capital, dash or space left the
# whole row or column on its "x.x" and unfilled — indistinguishable, on the slide, from a
# carrier that was never surveyed.

# What a template says, against what a warehouse plausibly holds for the same thing.
_AUTHORED_SECTIONS = ("Underwriting", "Claims \u2013 Claims Professionals")
_STORED_SECTIONS = ("underwriting", "Claims - Claims  Professionals")
_AUTHORED_PRACTICES = ("FINPRO", "Property & Casualty")
_STORED_PRACTICES = ("FinPro", "Property and Casualty")


def _typography_result(tmp_path):
    return _result_on(_carriers_db(tmp_path / "typography.db", "Sections",
                                   sections=_STORED_SECTIONS, practices=_STORED_PRACTICES))


def test_typography_does_not_break_a_cell_match(tmp_path):
    from studio.template_fill.survey import facts

    grid = facts.load_grid(_typography_result(tmp_path), "Singapore")
    assert grid is not None
    for section in _AUTHORED_SECTIONS:
        for practice in _AUTHORED_PRACTICES:
            assert grid.score(section, practice) is not None, (section, practice)
            assert grid.delta(section, practice) is not None, "no delta means no band colour"


def test_typography_does_not_break_the_total_rows_and_columns(tmp_path):
    from studio.template_fill.survey import facts

    grid = facts.load_grid(_typography_result(tmp_path), "Singapore")
    assert all(grid.section_total(s) is not None for s in _AUTHORED_SECTIONS)
    assert all(grid.practice_total(p) is not None for p in _AUTHORED_PRACTICES)
    assert grid.overall is not None and grid.overall_delta() is not None


def test_typography_does_not_break_the_ribbon_columns(tmp_path):
    """The ribbon buckets by section in Python for this reason — a SQL equality cannot be
    told to ignore a dash flavour."""
    from studio.template_fill.survey import facts

    spec = facts.load_ribbon(_typography_result(tmp_path), "Singapore", _AUTHORED_SECTIONS)
    assert spec is not None
    assert [c.label for c in spec.columns] == list(_AUTHORED_SECTIONS)


def test_a_label_that_means_something_else_still_does_not_match(tmp_path):
    """Normalisation is typography only. A wrong number in a QBR cell is worse than none."""
    from studio.template_fill.survey import facts

    grid = facts.load_grid(_typography_result(tmp_path), "Singapore")
    assert grid.score("Loss Control", "FINPRO") is None
    assert grid.practice_total("Marine") is None


def test_the_grid_keeps_the_book_s_own_labels_for_the_mismatch_report(tmp_path):
    from studio.template_fill.survey import facts

    grid = facts.load_grid(_typography_result(tmp_path), "Singapore")
    assert set(grid.sections) == set(_STORED_SECTIONS)
    assert set(grid.practices) == set(_STORED_PRACTICES)


# ── who the subject is ranked against ────────────────────────────────────────


def test_the_ribbon_ranks_against_the_curated_peer_group_when_there_is_one(tmp_path):
    from studio.template_fill.survey import facts

    engine = _carriers_db(tmp_path / "curated.db", "Sections")
    spec = facts.load_ribbon(_result_on(engine), "Singapore", ("Underwriting",))
    assert {b.carrier for b in spec.columns[0].boxes} == {S.SUBJECT, "Other Carrier"}


def test_the_ribbon_falls_back_to_the_surveyed_field_when_the_peers_table_has_no_row(tmp_path):
    """A Peers table with no row for this carrier and country used to leave a chart of one
    box — a ranking with nothing to rank against. The surveyed field is a weaker statement
    than a curated group but a true one, and the ribbon draws peers unnamed either way."""
    from studio.template_fill.survey import facts

    engine = _carriers_db(tmp_path / "nopeers.db", "Sections",
                          peers=[{"Carrier": "Someone Else", "Peers": "Other Carrier",
                                  "Country": "Singapore"}])
    spec = facts.load_ribbon(_result_on(engine), "Singapore", ("Underwriting",))
    assert {b.carrier for b in spec.columns[0].boxes} == set(_CARRIERS)
    assert sum(1 for b in spec.columns[0].boxes if b.highlight) == 1


def test_the_peer_lookup_asks_the_result_s_own_database(tmp_path):
    """``peer_members`` defaults to the APP-WIDE engine. The deck carries its own (an
    injected test DB, an uploaded dataset), and answering from the app's returned a peer
    group whose carriers are absent from the book being reported — one lonely box."""
    from studio.data import peer_members

    engine = _carriers_db(tmp_path / "injected.db", "Sections",
                          peers=[{"Carrier": S.SUBJECT, "Peers": "Third Carrier",
                                  "Country": "Singapore"}])
    assert peer_members("survey", S.SUBJECT, country="Singapore", engine=engine) == \
        ["Third Carrier"]
