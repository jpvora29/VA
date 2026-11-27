"""The working book and the reporting period.

Two promises, and the tests below hold each against the real seed book:

* **The book changes speed, never answers.** A calendar-basis deck computed on the sliced,
  aggregated, re-indexed working book must report exactly what it reports off the
  warehouse directly.
* **The period basis changes every figure, and correctly.** An R12M or date-range book
  relabels ``Year`` so that "this year vs last year" means "this window vs the same window a
  year before" — checked against hand-written SQL over the raw billing dates, and against the
  pandas twin an uploaded dataset uses.

Deterministic: the seed DB (Jan 2023 – Dec 2025), no LLM.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from studio import period as P
from studio.book import BookSpec, open_book
from studio.compute import compute_overall, period_totals, rank_movement, sow_movement, _resolve_filters


@pytest.fixture(autouse=True)
def _books_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_BOOK_DIR", str(tmp_path / "books"))


@pytest.fixture
def engine():
    from studio.data import get_engine

    return get_engine()


def _manual(engine, sql, *params):
    with sqlite3.connect(engine.url.database) as conn:
        return conn.execute(sql, params).fetchone()[0]


# ── the window rules (pure) ──────────────────────────────────────────────────


def test_r12m_is_the_twelve_months_ending_in_the_anchor_month():
    w = P.r12m_window(2026, 8)
    assert (w.start, w.end, w.kind) == (date(2025, 9, 1), date(2026, 8, 31), P.KIND_R12M)
    assert (w.label(), w.label(2025)) == ("TTM Aug 2026", "TTM Aug 2025")
    december = P.r12m_window(2025, 12)
    assert (december.start, december.end, december.crosses_year) == (
        date(2025, 1, 1), date(2025, 12, 31), False)


def test_r12m_anchors_on_the_latest_month_in_the_pinned_year():
    """A book to Aug 2026 with 2025 pinned reports TTM Aug 2025 — the same month-end."""
    choice = P.PeriodChoice(P.BASIS_R12M)
    assert P.window_for(choice, latest=(2026, 8)).end == date(2026, 8, 31)
    assert P.window_for(choice, latest=(2026, 8), year_pin=2025).end == date(2025, 8, 31)


def test_the_to_date_sets_the_r12m_anchor():
    choice = P.PeriodChoice(P.BASIS_R12M, date_to=date(2025, 6, 10))
    assert P.window_for(choice, latest=(2026, 8)) == P.r12m_window(2025, 6)


def test_a_short_range_is_a_period_and_a_long_one_only_restricts():
    short = P.window_for(P.PeriodChoice(date_from=date(2025, 1, 1), date_to=date(2025, 3, 31)),
                         latest=(2025, 12))
    assert short.kind == P.KIND_RANGE and short.relabels
    long = P.window_for(P.PeriodChoice(date_from=date(2023, 1, 1), date_to=date(2025, 3, 31)),
                        latest=(2025, 12))
    assert long.kind == P.KIND_RESTRICT and not long.relabels


def test_the_calendar_default_resolves_to_no_window():
    assert P.window_for(P.PeriodChoice(), latest=(2025, 12)) is None
    assert P.period_choice({}).is_default
    assert P.period_choice({"period_basis": "nonsense"}).basis == P.BASIS_CALENDAR


def test_the_form_sentence_names_the_period():
    text = P.describe(P.PeriodChoice(P.BASIS_R12M), latest=(2026, 8))
    assert text.startswith("R12M Aug 2026 (1 Sep 2025 – 31 Aug 2026) against R12M Aug 2025")
    assert "latest month" in P.describe(P.PeriodChoice(P.BASIS_R12M), latest=None)
    assert P.describe(P.PeriodChoice(), latest=(2025, 12)) == "FY2025 against FY2024."


# ── the book never changes an answer ─────────────────────────────────────────


@pytest.mark.parametrize("countries", [("Singapore",), ("Singapore", "Japan", "Australia")])
def test_a_calendar_book_reports_what_the_warehouse_reports(engine, countries):
    filters = {"carrier": "Zurich", "country": list(countries), "year": [2025]}
    direct = compute_overall(filters=filters, engine=engine)
    booked = compute_overall(filters=filters, book=open_book(engine, BookSpec(countries=countries)))
    assert booked.kpis == direct.kpis
    assert [(b.label, b.rows) for b in booked.breakdowns] == [
        (b.label, b.rows) for b in direct.breakdowns]
    assert booked.period is None


def test_the_book_holds_only_the_runs_markets(engine):
    book = open_book(engine, BookSpec(countries=("Japan",)))
    with book.engine.connect() as conn:
        from sqlalchemy import text

        assert [r[0] for r in conn.execute(text('SELECT DISTINCT "Country" FROM "GPR"'))] == ["Japan"]


# ── R12M and date ranges change every figure, correctly ──────────────────────


def test_an_r12m_book_totals_the_twelve_months_to_the_anchor(engine):
    """TTM Jun 2025 = Jul 2024 – Jun 2025, straight off the billing dates."""
    spec = BookSpec(countries=("Singapore",),
                    choice=P.PeriodChoice(P.BASIS_R12M, date_to=date(2025, 6, 30)))
    book = open_book(engine, spec)
    assert book.window.label() == "TTM Jun 2025"
    f = _resolve_filters({"carrier": "Zurich", "country": ["Singapore"], "year": [2025]},
                         has_quarter=True)
    totals = period_totals("gpr", f, book.engine)
    q = ('SELECT SUM(Premium) FROM GPR WHERE Country = ? AND Carrier_Group = ? '
         'AND Billing_Date BETWEEN ? AND ?')
    assert totals["current"] == pytest.approx(
        _manual(engine, q, "Singapore", "Zurich", "2024-07-01", "2025-06-30"))
    assert totals["prior"] == pytest.approx(
        _manual(engine, q, "Singapore", "Zurich", "2023-07-01", "2024-06-30"))
    # …and the share of wallet and rank are over the same twelve months.
    sow = sow_movement("gpr", f, book.engine, "Zurich")
    market = _manual(engine, 'SELECT SUM(Premium) FROM GPR WHERE Country = ? AND Billing_Date '
                             'BETWEEN ? AND ?', "Singapore", "2024-07-01", "2025-06-30")
    assert sow["current"] == pytest.approx(totals["current"] / market * 100, abs=0.05)
    assert rank_movement("gpr", f, book.engine, "Zurich")["current"] >= 1


def test_a_date_range_compares_the_window_with_the_same_window_a_year_earlier(engine):
    spec = BookSpec(countries=("Singapore",),
                    choice=P.PeriodChoice(date_from=date(2025, 1, 1), date_to=date(2025, 3, 31)))
    book = open_book(engine, spec)
    result = compute_overall(filters={"carrier": "Zurich", "country": ["Singapore"]}, book=book)
    f = {k: v for k, v in result.resolved_filters.items()}
    totals = period_totals("gpr", {**f, "Year": 2025}, book.engine)
    q = ('SELECT SUM(Premium) FROM GPR WHERE Country = ? AND Carrier_Group = ? '
         'AND Billing_Date BETWEEN ? AND ?')
    assert totals["current"] == pytest.approx(
        _manual(engine, q, "Singapore", "Zurich", "2025-01-01", "2025-03-31"))
    assert totals["prior"] == pytest.approx(
        _manual(engine, q, "Singapore", "Zurich", "2024-01-01", "2024-03-31"))


def test_every_country_book_can_answer_r12m_whatever_its_basis(engine):
    """The Country page's TTM table reads ``book.r12m()`` even on a calendar deck."""
    book = open_book(engine, BookSpec(countries=("Singapore",)))
    assert book.window is None
    r12m = book.r12m()
    assert r12m.window is not None and r12m.window.label() == "TTM Dec 2025"


def test_an_uploaded_dataset_gets_the_same_relabel_in_pandas(engine):
    """The pandas twin must agree with the SQL book to the cent."""
    import pandas as pd

    from core.analytics.frames import frame_source

    with sqlite3.connect(engine.url.database) as conn:
        frame = pd.read_sql('SELECT * FROM GPR WHERE Country = "Singapore"', conn)
        peers = pd.read_sql("SELECT * FROM Peers", conn)
    source = frame_source({"GPR": frame, "Peers": peers}, label="seed-frames")
    choice = P.PeriodChoice(P.BASIS_R12M, date_to=date(2025, 6, 30))
    frames_book = open_book(source, BookSpec(choice=choice))
    sql_book = open_book(engine, BookSpec(countries=("Singapore",), choice=choice))
    f = {"Carrier_Group": "Zurich", "Country": "Singapore", "Year": 2025}
    assert period_totals("gpr", f, frames_book.engine)["current"] == pytest.approx(
        period_totals("gpr", f, sql_book.engine)["current"])
    assert "Quarter" in frames_book.engine.columns("GPR")


# ── what the slides call the period ──────────────────────────────────────────


def test_slide_years_become_period_labels_on_an_r12m_run():
    from studio.template_fill.fill import _label_subs

    subs = _label_subs({"template_year": 2025, "period_year": 2026,
                        "period_labels": {"2026": "TTM Aug 2026", "2025": "TTM Aug 2025"}})
    text = "Carrier trading highlights FY 2025 · SoW% 2025 · Opportunities for 2026"
    for pattern, repl in subs:
        text = pattern.sub(repl, text)
    assert text == ("Carrier trading highlights TTM Aug 2026 · SoW% TTM Aug 2026 · "
                    "Opportunities for the next twelve months")


def test_the_ttm_table_headers_name_the_real_month():
    from studio.template_fill.gwp_page import _period_header

    assert _period_header("TTM April 2026", 2026, "TTM Aug 2026") == "TTM Aug 2026"
    assert _period_header("TTM April 2025", 2025, None) == "TTM April 2025"
    assert _period_header("CY", 2026, "TTM Aug 2026") == "TTM Aug 2026"


# ── YTD: one window, whichever way the author got there ──────────────────────

_YTD_Q2 = {"carrier": "Zurich", "country": ["Singapore"], "year": [2025], "quarter": ["Q2"]}


def _ytd_total(engine, choice):
    """The deck's current-period premium for 2025 · Q2 on ``choice``, off the working book."""
    selection = {"filters": _YTD_Q2}
    spec = BookSpec(countries=("Singapore",), choice=choice, year_pin=2025)
    book = open_book(engine, spec)
    result = compute_overall(
        filters=_YTD_Q2, book=book, period_basis=choice.basis, engine=engine
    )
    assert P.period_choice(selection).quarters == (2,)
    pinned = {**result.resolved_filters, "Year": 2025}
    return book, result, period_totals("gpr", pinned, book.engine)


def test_ytd_picked_directly_reports_january_to_the_quarter_end(engine):
    """2025 · Q2 on YTD = January to June, NOT April to June — and names itself YTD."""
    book, result, totals = _ytd_total(engine, P.PeriodChoice(P.BASIS_YTD, quarters=(2,)))
    half = compute_overall(filters={**_YTD_Q2, "quarter": ["Q1", "Q2"]})
    q2 = compute_overall(filters=_YTD_Q2)
    half_totals = period_totals("gpr", half.resolved_filters, half.engine)
    q2_totals = period_totals("gpr", q2.resolved_filters, q2.engine)

    assert book.window is not None and book.window.label() == "YTD Jun 2025"
    assert "Quarter" not in result.resolved_filters
    assert totals["current"] == pytest.approx(half_totals["current"], rel=1e-9)
    assert totals["prior"] == pytest.approx(half_totals["prior"], rel=1e-9)
    assert totals["current"] > q2_totals["current"]
    assert P.result_period_names(result, 2025) == ("YTD Jun 2025", "YTD Jun 2024")


def test_ytd_reached_from_r12m_reports_the_same_as_ytd_picked_directly(engine):
    """Switching R12M → YTD leaves an ending month in the store; it must be the same deck."""
    direct = _ytd_total(engine, P.PeriodChoice(P.BASIS_YTD, quarters=(2,)))
    via_r12m = _ytd_total(
        engine,
        P.PeriodChoice(
            P.BASIS_YTD,
            date_from=date(2025, 1, 1),
            date_to=date(2025, 6, 30),
            quarters=(2,),
        ),
    )

    assert direct[0].window == via_r12m[0].window
    assert direct[2] == via_r12m[2]
    assert P.result_period_names(direct[1], 2025) == P.result_period_names(
        via_r12m[1], 2025
    )


def test_ytd_of_a_complete_year_with_no_quarter_is_the_whole_year(engine):
    choice = P.PeriodChoice(P.BASIS_YTD)
    assert P.window_for(choice, latest=(2025, 12), year_pin=2025) is None


def test_the_setup_preview_names_and_counts_ytd_picked_directly(engine):
    """The Period tile reads "YTD Jun 2025" (not "2025 · Q2") the moment YTD is clicked."""
    from studio.authoring.setup import _period_scope_figures, period_selection

    key = tuple(
        sorted((c, tuple(v) if isinstance(v, list) else v) for c, v in _YTD_Q2.items())
    )
    period_key = tuple(sorted(period_selection("ytd", None, None).items()))
    tiles = {t["label"]: t for t in _period_scope_figures(key, None, period_key)}
    half = compute_overall(filters={**_YTD_Q2, "quarter": ["Q1", "Q2"]})

    assert tiles["Period"]["value"] == "YTD Jun 2025"
    assert tiles["Total GWP"]["value"] == half.kpis[0]["value"]   # Jan–Jun 2025 only


def test_a_quarter_filter_read_as_ytd_runs_from_q1():
    from studio.quarter_period import quarters_to_date

    assert quarters_to_date(["Q2"]) == ["Q1", "Q2"]
    assert quarters_to_date("2024 Q3") == ["2024 Q1", "2024 Q2", "2024 Q3"]
    assert quarters_to_date(["Q1-2023", "Q3-2023"]) == ["Q1-2023", "Q2-2023", "Q3-2023"]
    assert quarters_to_date(None) is None


_CARRIER_ONLY_Q2 = {"carrier": "Zurich", "year": [2025], "quarter": ["Q2"]}


def test_setup_and_deck_agree_on_ytd_with_no_market_picked(engine):
    """No market pinned: no working book, so Setup reads the rollup and the deck a month
    filter. Both must report January to June 2025 for "2025 · Q2" on YTD (the default)."""
    from studio.authoring.setup import _period_scope_figures, period_selection

    key = tuple(
        sorted(
            (c, tuple(v) if isinstance(v, list) else v) for c, v in _CARRIER_ONLY_Q2.items()
        )
    )
    period_key = tuple(sorted(period_selection("ytd", None, None).items()))
    tiles = {t["label"]: t for t in _period_scope_figures(key, None, period_key)}

    spec = BookSpec(choice=P.PeriodChoice(P.BASIS_YTD, quarters=(2,)), year_pin=2025)
    book = open_book(engine, spec)
    deck = compute_overall(filters=_CARRIER_ONLY_Q2, book=book, period_basis="ytd")
    half = compute_overall(filters={**_CARRIER_ONLY_Q2, "quarter": ["Q1", "Q2"]})

    assert book.engine is engine                      # no copy of the whole warehouse
    assert tiles["Period"]["value"] == "YTD Jun 2025"
    assert deck.kpis[0]["value"] == half.kpis[0]["value"]
    assert tiles["Total GWP"]["value"] == deck.kpis[0]["value"]
    assert P.result_period_names(deck, 2025) == ("YTD Jun 2025", "YTD Jun 2024")


def test_setup_and_deck_agree_on_ytd_of_a_complete_year_with_no_quarter(engine):
    """No quarter: YTD runs to the latest month of the year, which for 2025 is December."""
    from studio.authoring.setup import _period_scope_figures, period_selection

    filters = {"carrier": "Zurich", "country": ["Singapore"], "year": [2025]}
    key = tuple(sorted((c, tuple(v) if isinstance(v, list) else v) for c, v in filters.items()))
    period_key = tuple(sorted(period_selection("ytd", None, None).items()))
    tiles = {t["label"]: t for t in _period_scope_figures(key, None, period_key)}

    spec = BookSpec(countries=("Singapore",), choice=P.PeriodChoice(P.BASIS_YTD), year_pin=2025)
    deck = compute_overall(filters=filters, book=open_book(engine, spec), period_basis="ytd")
    calendar = compute_overall(filters=filters)

    assert tiles["Total GWP"]["value"] == deck.kpis[0]["value"] == calendar.kpis[0]["value"]


def test_a_ytd_book_total_is_one_year_not_every_year(engine):
    """The YTD book holds Jan–Mar of 2023, 2024 and 2025; the deck must report 2025's only.

    Regression: the Year pin used to be dropped on a date-range book, so the Total GWP and
    the Setup preview summed all three years (USD 102.0M against a Q1 2025 of 41.4M).
    """
    filters = {"carrier": "Zurich", "country": ["Singapore"], "year": [2025], "quarter": ["Q1"]}
    choice = P.PeriodChoice(P.BASIS_YTD, quarters=(1,))
    book = open_book(engine, BookSpec(countries=("Singapore",), choice=choice, year_pin=2025))
    ytd = compute_overall(filters=filters, book=book, period_basis="ytd")
    q1 = compute_overall(filters=filters)

    assert P.year_pin(ytd.resolved_filters["Year"]) == 2025
    assert ytd.kpis[0]["value"] == q1.kpis[0]["value"]           # Total GWP: Jan–Mar 2025


def test_pin_period_year_follows_the_window():
    ytd = P.ytd_window(2025, (2025, 12), (1,))
    assert P.pin_period_year({"Year": (2025,)}, ytd) == {"Year": (2025,)}
    assert P.pin_period_year({}, ytd) == {"Year": 2025}
    assert P.pin_period_year({"Year": 2024}, ytd) == {"Year": 2025}
    r12m = P.r12m_window(2025, 6)
    assert P.pin_period_year({}, r12m) == {}
