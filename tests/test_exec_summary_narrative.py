"""The executive summary reads as a story, names the real period, and fits the slide.

* the period is named for what the data covers (H1, Q1, 9M …) and compared like for like;
* the summary names WHAT moved — the leading product, its rank move, the industry inside
  it, the product that held the total back — rather than listing figures;
* the line-of-business table carries the top 7 lines by carrier premium.

Synthetic where the point is arithmetic; the seed book (with its second half-year cut
off) where the point is the real flow.
"""
from __future__ import annotations

import re
import shutil
import sqlite3

import pandas as pd
import pytest
from sqlalchemy import create_engine

from studio.exec_summary.analysis import analyse
from studio.exec_summary.config import load_config
from studio.exec_summary.context import AnalysisContext
from studio.exec_summary.coverage import month_number, period_label
from studio.exec_summary.fallback import overall_fallback
from studio.exec_summary.slides import MAX_TABLE_ROWS, table_rows
from studio.exec_summary.verify import _direction_issue
from studio.exec_summary.evidence import EvidenceStore, UNIT_MONEY

CFG = load_config()
M = 1_000_000.0


# ── the period (H1, Q1, 9M …) ────────────────────────────────────────────────


@pytest.mark.parametrize("months, label", [
    (range(1, 13), "FY2026"), (range(1, 7), "H1 2026"), (range(7, 13), "H2 2026"),
    (range(1, 4), "Q1 2026"), (range(4, 7), "Q2 2026"), (range(1, 10), "9M 2026"),
    (range(1, 6), "YTD May 2026"), (range(2, 5), "Feb–Apr 2026"),
])
def test_the_period_is_named_for_the_months_the_data_covers(months, label):
    assert period_label(list(months), 2026) == label


@pytest.mark.parametrize("raw, n", [("January", 1), ("jun", 6), ("Sept", 9), ("07", 7),
                                    ("2026-03", 3), ("2026-11-15", 11), ("Q1", None)])
def test_month_values_are_read_in_any_common_spelling(raw, n):
    assert month_number(raw) == n


@pytest.fixture(scope="module")
def h1_engine(tmp_path_factory):
    """The seed book with July–December of 2025 removed: a book loaded to June."""
    from studio.data import get_engine

    path = tmp_path_factory.mktemp("h1") / "h1.db"
    shutil.copyfile(get_engine().url.database, path)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM GPR WHERE Year = 2025 AND Month_Name IN "
                     "('July','August','September','October','November','December')")
    engine = create_engine(f"sqlite:///{path}")
    yield engine, str(path)
    engine.dispose()


def test_a_half_year_book_is_named_h1_and_compared_with_the_prior_h1(h1_engine, tmp_path,
                                                                    monkeypatch):
    from studio.compute import compute_overall
    from studio.exec_summary.llm import NoModel
    from studio.exec_summary.pipeline import build_exec_summary

    monkeypatch.setenv("STUDIO_COMMENTARY_CACHE", "off")
    engine, path = h1_engine
    result = compute_overall(filters={"carrier": "Zurich", "country": ["Singapore", "Hong Kong"],
                                      "year": 2025}, engine=engine)
    built = build_exec_summary(result, out_path=str(tmp_path / "h1.pptx"), data_basis="premium",
                               model=NoModel())
    ctx, overall = built.analysis.context, built.analysis.overall
    assert (ctx.current_label, ctx.prior_label) == ("H1 2025", "H1 2024")

    h1 = ("January", "February", "March", "April", "May", "June")
    with sqlite3.connect(path) as conn:
        by_year = dict(conn.execute(
            f"SELECT Year, SUM(Premium) FROM GPR WHERE Carrier_Group = 'Zurich' AND Country IN "
            f"('Singapore','Hong Kong') AND Month_Name IN ({','.join('?' * 6)}) "
            f"AND Year IN (2024, 2025) GROUP BY Year", h1).fetchall())
    assert overall.carrier_cur == pytest.approx(by_year[2025])
    assert overall.carrier_prior == pytest.approx(by_year[2024])     # H1 2024, not FY2024

    from pptx import Presentation
    summary = " ".join(s.text_frame.text for s in Presentation(built.deck_path).slides[1].shapes
                       if s.has_text_frame)
    assert "Executive Summary (H1 2025)" in summary
    assert "in H1 2025" in summary and "FY2025" not in summary


# ── the story: named movers, not a list of figures ───────────────────────────


def _book(products=("Cyber", "Property", "Casualty")) -> pd.DataFrame:
    rows = []
    plan = {"Cyber": (10, 30, "Technology"), "Property": (40, 42, "Manufacturing"),
            "Casualty": (30, 24, "Wholesale")}
    for p in products:
        prior, cur, industry = plan.get(p, (5, 6, "Retail"))
        for year, focal in ((2024, prior), (2025, cur)):
            rows += [
                {"country": "SG", "product": p, "industry": industry, "segment": "Corporate",
                 "carrier": "Focal", "year": year, "premium": focal * M},
                {"country": "SG", "product": p, "industry": "Other", "segment": "Corporate",
                 "carrier": "Focal", "year": year, "premium": 1 * M},
                {"country": "SG", "product": p, "industry": industry, "segment": "Corporate",
                 "carrier": "Rival", "year": year, "premium": (100 if year == 2024 else 120) * M},
            ]
    return pd.DataFrame(rows)


def _analysis(products=("Cyber", "Property", "Casualty")):
    ctx = AnalysisContext(carrier="Focal", countries=("SG",), current_year=2025, prior_year=2024,
                          current_label="H1 2025", prior_label="H1 2024", currency="USD",
                          symbol="$")
    return analyse(ctx, _book(products), {}, None, CFG)


def test_the_summary_names_the_leader_its_rank_move_its_industry_and_the_drag():
    a = _analysis()
    statements = [f.statement for f in overall_fallback(a, {}).findings]
    text = " ".join(statements)
    assert "led by Cyber" in statements[0] and "in H1 2025" in statements[0]
    assert statements[1].startswith("Cyber added $20.0M")            # what drove it
    assert "Technology adding the most" in statements[1]              # the industry inside
    assert re.search(r"(climbed to|slipped to|held) #\d", statements[1])  # its rank
    assert statements[2].startswith("Casualty held the total back")   # what held it back
    assert "fell 19.4%" in statements[2] and "mainly in Wholesale" in statements[2]
    # Every sentence names something that moved — no sentence is just figures.
    names = ("Cyber", "Property", "Casualty", "Technology", "Wholesale", "SG", "Focal")
    assert all(any(n in s for n in names) for s in statements)


def test_every_fallback_sentence_still_passes_the_claim_checks():
    from studio.exec_summary import payloads as P
    from studio.exec_summary.stages import StageCall, StageEnv, run_stage
    from studio.exec_summary.llm import NoModel
    from functools import partial
    from studio.exec_summary import fallback as FB

    a = _analysis()
    env = StageEnv(model=NoModel(), store=a.evidence, run_id="t", rule_version="r",
                   budgets=CFG.budgets, concurrency=1)
    result = run_stage(StageCall(P.overall_payload(a, {}, {}), partial(FB.overall_fallback, a, {})),
                       env)
    assert result.errors == ("model unavailable (none)",)
    assert len(result.findings) >= 3


def test_a_repeated_magnitude_is_not_read_against_the_wrong_verb():
    store = EvidenceStore()
    gain = store.add("carrier_premium_change", "s", "A", "p", 0.5 * M, "+$0.5M", UNIT_MONEY)
    loss = store.add("carrier_premium_change", "s", "B", "p", -0.5 * M, "-$0.5M", UNIT_MONEY)
    ok = "Inside Casualty, Retail added $0.5M while Wholesale lost $0.5M."
    assert _direction_issue(ok, store, [gain, loss]) == ""
    wrong = "Inside Casualty, Wholesale grew $0.5M."
    assert "rose beside a negative" in _direction_issue(wrong, store, [loss])


# ── the detail table fits ────────────────────────────────────────────────────


def test_the_table_carries_the_top_seven_lines_by_carrier_premium():
    products = ("Cyber", "Property", "Casualty", "Marine", "Energy", "Surety", "Aviation",
                "Credit", "Terror")
    a = _analysis(products)
    rows = table_rows(a)
    assert MAX_TABLE_ROWS == 7 and len(rows) == 7
    premiums = [p.carrier_cur for p in a.product_totals]
    assert premiums == sorted(premiums, reverse=True)
    assert [r.product for r in rows] == [p.scope.product for p in a.product_totals[:7]]
