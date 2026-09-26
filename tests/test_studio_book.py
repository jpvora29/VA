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
    assert P.describe(P.PeriodChoice(), latest=(2025, 12)) == "YTD 2025 against 2024."


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
