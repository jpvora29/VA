"""The Carrier Survey page reports the run's OWN cut — its country, its year, its carrier.

Every test here is a defect the page shipped with. The survey book was read on its own
terms and nobody else's: it answered with the latest year IT held while the rest of the
deck reported the year the author picked, and it took the country string verbatim, so a
book that spells the market differently answered nothing. On top of that the year-on-year
comparison was hardcoded to ``year - 1``, so a book not surveyed every year had no
comparison at all — and a page with no comparison lost every band colour in its table,
which is what "the background is not populating" looked like on the slide.

The fixtures are built here rather than seeded because the seed DB is deliberately regular
— every carrier, every practice, every year — and none of these faults can show up in a
book that regular.
"""
from __future__ import annotations

import pytest

from studio.template_fill.survey import facts, page as P, scope

_SUBJECT = "Zurich"
_SECTIONS = ("Underwriting", "Claims")
_PRACTICES = ("Property", "Casualty")


def _book(path, *, years=(2023, 2024, 2025), country="Singapore",
          carriers=("Zurich", "Other Carrier"), practices=_PRACTICES,
          practices_by_carrier=None, peers=None, responses=None):
    """A Carriers/Peers pair with control over the things a live warehouse varies.

    ``practices_by_carrier`` gives one carrier its own practice set — the case the page has
    to report on the SUBJECT's book and not on whatever the template was drawn with.

    A cell's score moves with the YEAR (so every cell has a real move to band) and varies by
    PRACTICE (so an average over the wrong set of practices is a different number, which is
    what the totals tests turn on).

    ``responses`` is ``{practice: how many people answered it}``. Given, the table gains a
    ``Respondent`` column and each cell is repeated once per respondent — which is how a
    real book records them, and the only way to exercise the >4 rule. Omitted, the table has
    no such column at all, which is the OTHER case that has to work: the rule cannot be
    applied and every practice is reported.
    """
    import pandas as pd
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{path}")
    by_carrier = {c: practices for c in carriers}
    by_carrier.update(practices_by_carrier or {})
    rows = [{"Region": "Asia", "SurveyCountry": country, "Carrier": carrier,
             "SurveyPractice": practice, "Sections": section, "Attributes": "Overall",
             "SurveySegment": "Large", "Survey_Year": year,
             "Score": base + 0.5 * (year - min(years)) + 0.1 * i, "NPS Score": base,
             **({"Respondent": f"{practice}-{n}"} if responses else {})}
            for carrier, base in zip(carriers, (7.0, 6.0, 5.0, 4.0))
            for i, practice in enumerate(by_carrier[carrier])
            for section in _SECTIONS
            for year in years
            for n in range(responses.get(practice, 0) if responses else 1)]
    pd.DataFrame(rows).to_sql("Carriers", engine, index=False, if_exists="replace")
    if peers is None:
        peers = [{"Carrier": _SUBJECT, "Peers": "Other Carrier", "Country": country}]
    pd.DataFrame(peers or [{"Carrier": "", "Peers": "", "Country": ""}]).to_sql(
        "Peers", engine, index=False, if_exists="replace")
    return engine


def _result(engine, *, country="Singapore", year=None, subject=_SUBJECT, **kwargs):
    from studio.compute import OverallResult

    filters = {"Country": country}
    if year is not None:
        filters["Year"] = year
    return OverallResult(subject=subject, flow="gpr", resolved_filters=filters,
                         engine=engine, **kwargs)


# ── which year the page reports, as a rule ───────────────────────────────────


def test_no_year_pinned_reports_the_latest_survey():
    assert scope.reporting_years((2023, 2024, 2025)) == (2025, 2024)


def test_the_pinned_year_wins_over_the_latest_survey():
    """The whole defect in one line: the deck said 2024 and the survey table said 2025."""
    assert scope.reporting_years((2023, 2024, 2025), (2024,)) == (2024, 2023)


def test_the_prior_year_is_the_previous_survey_not_the_previous_calendar_year():
    """A book surveyed every other year has no ``year - 1``. Treating that as "nothing to
    compare with" is what left the table with no band colours at all."""
    assert scope.reporting_years((2021, 2024), (2024,)) == (2024, 2021)


def test_the_first_survey_has_nothing_before_it():
    assert scope.reporting_years((2024,), (2024,)) == (2024, None)


def test_a_pinned_year_the_book_missed_falls_back_to_the_latest_before_it():
    assert scope.reporting_years((2022, 2023), (2025,)) == (2023, 2022)


def test_the_page_is_not_built_from_a_year_after_the_one_selected():
    """A 2025 score under a deck titled 2024 is worse than no survey page."""
    assert scope.reporting_years((2025, 2026), (2024,)) == (None, None)


def test_an_empty_book_reports_nothing():
    assert scope.reporting_years(()) == (None, None)
    assert scope.reporting_years((), (2024,)) == (None, None)


def test_several_pinned_years_report_the_latest_of_them():
    assert scope.reporting_years((2023, 2024, 2025), (2023, 2024)) == (2024, 2023)


# ── the selection, read off the run ──────────────────────────────────────────


def test_the_run_s_year_and_country_are_read_from_its_own_filters(tmp_path):
    engine = _book(tmp_path / "sel.db")
    result = _result(engine, year=2024)
    assert scope.selected_years(result) == (2024,)
    assert scope.selected_countries(result) == ("Singapore",)


def test_a_multi_select_year_is_read_whole(tmp_path):
    engine = _book(tmp_path / "multi.db")
    assert scope.selected_years(_result(engine, year=(2023, 2024))) == (2023, 2024)


def test_an_unpinned_year_leaves_the_book_to_answer(tmp_path):
    engine = _book(tmp_path / "noyear.db")
    assert scope.selected_years(_result(engine)) == ()


# ── the country, in the book's own spelling ──────────────────────────────────


def test_the_country_is_matched_on_what_it_says_not_how_it_is_typed(tmp_path):
    engine = _book(tmp_path / "typo.db", country="HONG  KONG")
    result = _result(engine, country="Hong Kong")
    assert scope.book_country(result, "Hong Kong") == "HONG  KONG"
    assert facts.has_survey_data(result, "Hong Kong") is True


def test_a_country_the_book_does_not_hold_gets_no_page(tmp_path):
    engine = _book(tmp_path / "elsewhere.db")
    result = _result(engine, country="Atlantis")
    assert scope.book_country(result, "Atlantis") is None
    assert facts.has_survey_data(result, "Atlantis") is False
    assert scope.resolve(result, "Atlantis") is None


def test_the_scope_carries_the_book_s_own_country_carrier_and_year(tmp_path):
    engine = _book(tmp_path / "scope.db", country="SINGAPORE")
    resolved = scope.resolve(_result(engine, country="Singapore", year=2024), "Singapore")
    assert resolved == scope.SurveyScope(country="SINGAPORE", carrier="Zurich",
                                         year=2024, prior_year=2023)


# ── the numbers follow the selection ─────────────────────────────────────────


def test_the_grid_reports_the_selected_year(tmp_path):
    engine = _book(tmp_path / "gridyear.db")
    grid = facts.load_grid(_result(engine, year=2024), "Singapore")
    assert (grid.year, grid.prior_year) == (2024, 2023)


def test_the_grid_still_reports_the_latest_survey_when_no_year_is_pinned(tmp_path):
    engine = _book(tmp_path / "gridlatest.db")
    grid = facts.load_grid(_result(engine), "Singapore")
    assert (grid.year, grid.prior_year) == (2025, 2024)


def test_the_overall_score_tile_follows_the_same_year(tmp_path):
    """The tile sits on the summary page beside premium figures for the selected year."""
    engine = _book(tmp_path / "tile.db")
    pinned = facts.load_overall_score(_result(engine, year=2023), ("Singapore",))
    latest = facts.load_overall_score(_result(engine), ("Singapore",))
    assert pinned is not None and latest is not None
    assert pinned < latest, "the tile reported the book's latest year, not the run's"


def test_the_ribbon_ranks_the_selected_year(tmp_path):
    engine = _book(tmp_path / "ribbonyear.db")
    subject = lambda year: next(                                       # noqa: E731
        b.score for b in facts.load_ribbon(_result(engine, year=year), "Singapore",
                                           _SECTIONS).columns[0].boxes if b.highlight)
    assert subject(2023) < subject(2025)


# ── the axes are the carrier's, not the template's ───────────────────────────


def test_the_page_reports_the_practices_this_carrier_is_surveyed_on(tmp_path):
    """Two carriers, two practice sets. The page must show the SUBJECT's."""
    engine = _book(tmp_path / "ragged.db", practices=("Property", "Casualty"),
                   practices_by_carrier={"Other Carrier": ("Marine", "Aviation")})
    axes = facts.load_axes(_result(engine, year=2024), "Singapore")
    assert set(axes.practices) == {"Property", "Casualty"}
    assert "Marine" not in axes.practices


def test_the_axes_are_read_at_the_selected_year(tmp_path):
    """A practice retired before the selected year must not reach that year's page."""
    import pandas as pd
    from sqlalchemy import create_engine

    path = tmp_path / "retired.db"
    engine = _book(path)
    rows = [{"Region": "Asia", "SurveyCountry": "Singapore", "Carrier": _SUBJECT,
             "SurveyPractice": "Marine", "Sections": section, "Attributes": "Overall",
             "SurveySegment": "Large", "Survey_Year": 2023, "Score": 5.0, "NPS Score": 5.0}
            for section in _SECTIONS]
    pd.DataFrame(rows).to_sql("Carriers", create_engine(f"sqlite:///{path}"),
                              index=False, if_exists="append")
    assert "Marine" in facts.load_axes(_result(engine, year=2023), "Singapore").practices
    assert "Marine" not in facts.load_axes(_result(engine, year=2024), "Singapore").practices


# ── a Total averages the row printed beside it ───────────────────────────────


def test_a_total_covers_only_the_practices_the_page_shows(tmp_path):
    """The page's columns are the ones the template has room for. A Total that spans the
    carrier's whole book cannot be checked against the row it sits on — and on a page whose
    surplus columns were trimmed away, it visibly does not add up."""
    from statistics import fmean

    engine = _book(tmp_path / "totals.db",
                   practices=("Property", "Casualty", "Marine", "Aviation"))
    result = _result(engine, year=2024)
    shown = ("Property", "Casualty")
    grid = facts.load_grid(result, "Singapore", practices=shown)
    for section in _SECTIONS:
        cells = [grid.score(section, p) for p in shown]
        assert grid.section_total(section) == pytest.approx(fmean(cells))
    assert grid.overall == pytest.approx(
        fmean([grid.score(s, p) for s in _SECTIONS for p in shown]))
    # …and the practices left out are genuinely left out.
    assert grid.practice_total("Marine") is None


def _scored(values, survey_page):
    """``(row indices, column indices)`` that ended up carrying a score on the filled page.

    A slot the carrier's book could not fill is blanked and its line taken off the table, so
    the reader's arithmetic runs over these and nothing else.
    """
    total_col = survey_page.total_col
    rows = [r for r, _ in survey_page.rows
            if isinstance(values.get(P._role(survey_page.slide_idx, r, total_col)), float)]
    cols = [c for c, _ in survey_page.cols
            if rows and isinstance(values.get(P._role(survey_page.slide_idx, rows[0], c)), float)]
    return rows, cols


def test_the_filled_total_column_averages_the_row_printed_beside_it(tmp_path):
    """End to end, over the REAL template. The carrier is surveyed on MORE practices than
    the page has columns, so some never reach the slide — and the Total has to average what
    did, which is the only thing a reader can check with a calculator. Spanning the whole
    book instead is what made the averages look wrong."""
    from statistics import fmean

    from studio.template_fill.analyze import analyze

    template = analyze("template/survey_template.pptx")
    survey_page = P.pages(template)[0]
    wider = tuple(f"Practice {i}" for i in range(len(survey_page.cols) + 2))
    engine = _book(tmp_path / "wider.db", practices=wider)
    values = P.values(template, _result(engine, year=2024))

    rows, shown = _scored(values, survey_page)
    assert 0 < len(shown) < len(wider), "the page must be narrower than the book"
    for row in rows:
        cells = [values[P._role(survey_page.slide_idx, row, c)] for c in shown]
        total = values[P._role(survey_page.slide_idx, row, survey_page.total_col)]
        assert total == pytest.approx(fmean(cells)), "the Total does not average its row"
    corner = values[P._role(survey_page.slide_idx, survey_page.total_row,
                            survey_page.total_col)]
    assert corner == pytest.approx(fmean(
        [values[P._role(survey_page.slide_idx, r, c)] for r in rows for c in shown]))


def test_a_narrower_book_trims_the_page_and_still_totals_what_is_left(tmp_path):
    """The other direction: fewer practices than slots, so the surplus columns come OFF the
    table (:func:`studio.template_fill.fill._drop_table_lines`) and the Total covers the
    columns that survived."""
    from statistics import fmean

    from studio.template_fill.analyze import analyze

    template = analyze("template/survey_template.pptx")
    survey_page = P.pages(template)[0]
    engine = _book(tmp_path / "narrow.db", practices=("Property", "Casualty", "Marine"))
    values = P.values(template, _result(engine, year=2024))

    trim = values["drop_table_lines"][f"{survey_page.slide_idx}:{survey_page.table_id}"]
    assert len(trim["cols"]) == len(survey_page.cols) - 3
    rows, shown = _scored(values, survey_page)
    assert len(shown) == 3
    for row in rows:
        cells = [values[P._role(survey_page.slide_idx, row, c)] for c in shown]
        assert values[P._role(survey_page.slide_idx, row, survey_page.total_col)] == \
            pytest.approx(fmean(cells))


def test_a_total_spans_the_whole_book_when_the_page_shows_all_of_it(tmp_path):
    """The restriction narrows; it must never change the answer for an untrimmed page."""
    engine = _book(tmp_path / "whole.db", practices=("Property", "Casualty", "Marine"))
    result = _result(engine, year=2024)
    everything = facts.load_grid(result, "Singapore")
    restricted = facts.load_grid(result, "Singapore",
                                 practices=("Property", "Casualty", "Marine"))
    assert everything.overall == pytest.approx(restricted.overall)
    assert everything.section_totals == restricted.section_totals


# ── a practice too few people answered ───────────────────────────────────────
#
# An average over four answers swings on any one of them, and in a thin market a named
# carrier's score can identify who gave it. A practice is reported only when MORE THAN four
# distinct responses stand behind it — and because the filter runs where the page's axes are
# decided, a practice it drops is dropped from the table, its totals AND the ribbon at once.

_THIN = {"Property": 9, "Casualty": 4}          # Casualty is at the threshold, not over it


def test_a_practice_with_too_few_responses_is_not_reported(tmp_path):
    engine = _book(tmp_path / "thin.db", responses=_THIN)
    axes = facts.load_axes(_result(engine, year=2024), "Singapore")
    assert axes.practices == ("Property",)


def test_the_threshold_is_strictly_greater_than_four(tmp_path):
    """"Greater than 4" is five, not four — the boundary the rule names."""
    engine = _book(tmp_path / "edge.db", responses={"Property": 5, "Casualty": 4})
    axes = facts.load_axes(_result(engine, year=2024), "Singapore")
    assert axes.practices == ("Property",)
    assert facts.MIN_RESPONSES == 4


def test_responses_are_counted_DISTINCT_not_as_rows(tmp_path):
    """One respondent answering every section is one response, not one per row. Counting
    rows would pass a practice that a single person answered."""
    engine = _book(tmp_path / "distinct.db", responses={"Property": 2, "Casualty": 9})
    counts = facts.response_counts(
        _result(engine, year=2024),
        {facts.COUNTRY_COL: "Singapore", facts.CARRIER_COL: _SUBJECT, facts.YEAR_COL: 2024})
    assert counts == {"Property": 2, "Casualty": 9}       # not 4 and 18, the row counts


def test_the_count_is_scoped_to_the_reported_country_carrier_and_year(tmp_path):
    engine = _book(tmp_path / "scoped.db", responses={"Property": 9, "Casualty": 9})
    result = _result(engine, year=2024)
    everything = facts.response_counts(result, {})
    one_cut = facts.response_counts(
        result, {facts.COUNTRY_COL: "Singapore", facts.CARRIER_COL: _SUBJECT,
                 facts.YEAR_COL: 2024})
    assert everything["Property"] == one_cut["Property"], "respondents are shared per practice"
    assert one_cut and set(one_cut) == {"Property", "Casualty"}


def test_a_book_with_no_response_column_reports_every_practice(tmp_path):
    """The rule cannot be applied without something to count, and inventing a count from
    the row shape would drop practices for a reason no reader could be told."""
    engine = _book(tmp_path / "nocount.db")               # no Respondent column at all
    result = _result(engine, year=2024)
    assert facts.response_column(result) is None
    assert facts.response_counts(result, {}) == {}
    assert set(facts.load_axes(result, "Singapore").practices) == set(_PRACTICES)


def test_the_response_column_must_be_declared_to_be_used(tmp_path):
    """``safe_column`` refuses any identifier the flow does not declare, so a column the
    registry has never heard of must not be reached for — the query would only fail."""
    from core.analytics.sql import flow_spec, safe_column

    spec = flow_spec("survey")
    for candidate in facts.RESPONSE_CANDIDATES:
        assert safe_column(spec, candidate) == candidate


def test_a_practice_the_page_drops_is_dropped_from_the_ribbon_too(tmp_path):
    engine = _book(tmp_path / "ribbonthin.db", responses=_THIN)
    result = _result(engine, year=2024)
    axes = facts.load_axes(result, "Singapore")
    spec = facts.load_ribbon(result, "Singapore", _SECTIONS, axes.practices)
    grid = facts.load_grid(result, "Singapore", practices=axes.practices)
    subject = next(b.score for b in spec.columns[0].boxes if b.highlight)
    assert subject == pytest.approx(grid.section_total(_SECTIONS[0]))


# ── the ribbon agrees with the table above it ────────────────────────────────
#
# The subject's box in each ribbon column IS that section's Total on the table. Averaged
# over the carrier's whole book while the table averaged the practices it shows, the chart
# quietly disagreed with the number printed directly above it — over practices the reader
# cannot see, so there was no way to reconcile the two.


def test_every_ribbon_box_matches_its_row_total(tmp_path):
    engine = _book(tmp_path / "agree.db",
                   practices=("Property", "Casualty", "Marine", "Aviation"))
    result = _result(engine, year=2024)
    shown = ("Property", "Casualty")

    grid = facts.load_grid(result, "Singapore", practices=shown)
    spec = facts.load_ribbon(result, "Singapore", _SECTIONS, shown)

    for column in spec.columns:
        subject = next(b.score for b in column.boxes if b.highlight)
        assert subject == pytest.approx(grid.section_total(column.label)), column.label


def test_an_unrestricted_ribbon_still_averages_the_whole_book(tmp_path):
    """The restriction narrows; passing none must not change the old answer."""
    engine = _book(tmp_path / "wide.db", practices=("Property", "Casualty", "Marine"))
    result = _result(engine, year=2024)
    whole = facts.load_ribbon(result, "Singapore", _SECTIONS)
    grid = facts.load_grid(result, "Singapore")
    subject = next(b.score for b in whole.columns[0].boxes if b.highlight)
    assert subject == pytest.approx(grid.section_total(_SECTIONS[0]))


def test_the_peers_are_averaged_over_the_same_practices(tmp_path):
    """A ranking is only fair if every carrier in a column is averaged over the same cut."""
    engine = _book(tmp_path / "fair.db", carriers=("Zurich", "Other Carrier"),
                   practices=("Property", "Casualty", "Marine"))
    result = _result(engine, year=2024)
    narrow = facts.load_ribbon(result, "Singapore", _SECTIONS, ("Property",))
    wide = facts.load_ribbon(result, "Singapore", _SECTIONS, ("Property", "Marine"))
    peer = lambda spec: next(b.score for b in spec.columns[0].boxes if not b.highlight)  # noqa: E731
    assert peer(narrow) != pytest.approx(peer(wide))


# ── the band colours, and the background they paint ──────────────────────────


def test_a_sparse_book_still_bands_its_cells(tmp_path):
    """Years 2021 and 2024 — no ``year - 1``. Every cell used to come back uncoloured, which
    is what stripped the table's background on the slide."""
    engine = _book(tmp_path / "sparse.db", years=(2021, 2024))
    grid = facts.load_grid(_result(engine, year=2024), "Singapore")
    assert grid.prior_year == 2021
    assert all(grid.delta(s, p) is not None for s in _SECTIONS for p in _PRACTICES)


def test_a_cell_with_no_comparison_keeps_the_template_s_own_background(tmp_path):
    """No band means no claim about direction — so the cell is LEFT ALONE. Emitting a null
    colour instead told the fill engine to clear it, and a first-survey page came out with
    its whole table stripped."""
    from studio.template_fill.analyze import analyze

    engine = _book(tmp_path / "firstyear.db", years=(2024,))
    values = P.values(analyze("template/survey_template.pptx"),
                      _result(engine, year=2024))
    assert values, "a first-survey page still fills its numbers"
    for specs in (values.get("cell_fills") or {}).values():
        assert all(spec.get("hex") for spec in specs), "a null colour CLEARS the cell"


def test_a_page_with_a_comparison_paints_real_colours(tmp_path):
    from studio.template_fill.analyze import analyze
    from studio.template_fill.survey import bands

    engine = _book(tmp_path / "banded.db")
    values = P.values(analyze("template/survey_template.pptx"),
                      _result(engine, year=2024))
    painted = [spec for specs in values["cell_fills"].values() for spec in specs]
    legend = set(bands.LEGEND)
    assert painted and {spec["hex"] for spec in painted} <= legend


# ── who the subject is ranked against ────────────────────────────────────────


def test_the_peer_group_is_keyed_on_the_carrier_not_the_carrier_group(tmp_path):
    """``Peers.Carrier`` is the survey flow's peer key. Looking the premium
    ``Carrier_Group`` up here returns either nothing or somebody else's peers."""
    engine = _book(tmp_path / "peerkey.db",
                   carriers=("Zurich", "Other Carrier", "Third Carrier"),
                   peers=[{"Carrier": _SUBJECT, "Carrier_Group": "Someone Else",
                           "Peers": "Third Carrier", "Country": "Singapore"}])
    assert facts.peer_group(_result(engine), "Singapore", _SUBJECT) == ("Third Carrier",)


def test_the_peer_group_is_scoped_to_the_selected_country(tmp_path):
    engine = _book(tmp_path / "peercountry.db",
                   carriers=("Zurich", "Other Carrier", "Third Carrier"),
                   peers=[{"Carrier": _SUBJECT, "Peers": "Other Carrier",
                           "Country": "Singapore"},
                          {"Carrier": _SUBJECT, "Peers": "Third Carrier",
                           "Country": "Japan"}])
    assert facts.peer_group(_result(engine), "Singapore", _SUBJECT) == ("Other Carrier",)


def test_the_ribbon_ranks_against_the_peers_table_group(tmp_path):
    engine = _book(tmp_path / "peerribbon.db",
                   carriers=("Zurich", "Other Carrier", "Third Carrier"),
                   peers=[{"Carrier": _SUBJECT, "Peers": "Third Carrier",
                           "Country": "Singapore"}])
    spec = facts.load_ribbon(_result(engine, year=2024), "Singapore", ("Underwriting",))
    assert {b.carrier for b in spec.columns[0].boxes} == {_SUBJECT, "Third Carrier"}


def test_each_market_s_page_ranks_against_that_market_s_own_peer_group(tmp_path):
    """Why Setup leaves the survey peer dropdown EMPTY on a multi-country run: a pinned set
    applies to every survey page, and the Peers table already answers per market."""
    import pandas as pd
    from sqlalchemy import create_engine

    path = tmp_path / "twomarkets.db"
    engine = _book(path, carriers=("Zurich", "Other Carrier", "Third Carrier"),
                   peers=[{"Carrier": _SUBJECT, "Peers": "Other Carrier",
                           "Country": "Singapore"},
                          {"Carrier": _SUBJECT, "Peers": "Third Carrier", "Country": "Japan"}])
    japan = [{"Region": "Asia", "SurveyCountry": "Japan", "Carrier": carrier,
              "SurveyPractice": practice, "Sections": section, "Attributes": "Overall",
              "SurveySegment": "Large", "Survey_Year": 2024, "Score": base, "NPS Score": base}
             for carrier, base in (("Zurich", 7.0), ("Other Carrier", 6.0), ("Third Carrier", 5.0))
             for practice in _PRACTICES for section in _SECTIONS]
    pd.DataFrame(japan).to_sql("Carriers", create_engine(f"sqlite:///{path}"),
                               index=False, if_exists="append")

    def ranked(country):
        result = _result(engine, country=country, year=2024)
        spec = facts.load_ribbon(result, country, ("Underwriting",))
        return {b.carrier for b in spec.columns[0].boxes}

    assert ranked("Singapore") == {_SUBJECT, "Other Carrier"}
    assert ranked("Japan") == {_SUBJECT, "Third Carrier"}
