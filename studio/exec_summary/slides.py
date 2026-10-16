"""What the two content slides say — pure functions from analysis + verified findings.

The deterministic renderer of design Section 17: verified JSON findings become the summary
paragraph; the detail slide's charts, tables and note come straight from the SAME metrics
the findings cite, so a chart and a sentence can never disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

from core.analytics.money_units import money_scale, money_text
from studio.exec_summary.analysis import ExecAnalysis
from studio.exec_summary.evidence import pct
from studio.exec_summary.metrics import SliceMetrics
from studio.exec_summary.schemas import StageResult

MAX_CHART_COUNTRIES = 6
MAX_RANK_ROWS = 5
MAX_TABLE_ROWS = 9


@dataclass(frozen=True)
class ChartSeries:
    categories: Tuple[str, ...]
    carrier: Tuple[Optional[float], ...]
    peer: Tuple[Optional[float], ...]
    unit: str                      # "$M", "$B" or "%"
    number_format: str


@dataclass(frozen=True)
class TableRow:
    product: str
    marsh: str
    carrier: str
    yoy: str
    yoy_sign: int
    mix: str
    sow: str
    rank: str
    peers: str


@dataclass(frozen=True)
class SlideContent:
    cover_title: str
    cover_date: str
    summary_title: str
    summary_paragraph: str
    summary_footnote: str
    detail_title: str
    premium_chart: ChartSeries
    sow_chart: ChartSeries
    rank_rows: Tuple[Tuple[str, str], ...]
    table_rows: Tuple[TableRow, ...]
    note: str
    detail_footnote: str


def summary_paragraph(overall: Optional[StageResult]) -> str:
    """The verified overall findings, in order, as one paragraph (user decision)."""
    if overall is None or not overall.findings:
        return ""
    return " ".join(f.statement.strip() for f in overall.findings if f.statement.strip())


def _countries_by_premium(analysis: ExecAnalysis) -> List:
    return sorted(analysis.countries, key=lambda c: -c.metrics.carrier_cur)


def _rounded(value: Optional[float], divisor: float = 1.0) -> Optional[float]:
    return None if value is None else round(value / divisor, 1)


def premium_chart(analysis: ExecAnalysis) -> ChartSeries:
    """Carrier premium vs the mean premium of that country's own peer set."""
    rows = _countries_by_premium(analysis)[:MAX_CHART_COUNTRIES]
    raw = [v for c in rows for v in (c.metrics.carrier_cur, c.metrics.peer.mean_cur)]
    divisor, suffix = money_scale(raw)
    return ChartSeries(
        categories=tuple(c.country for c in rows),
        carrier=tuple(_rounded(c.metrics.carrier_cur, divisor) for c in rows),
        peer=tuple(_rounded(c.metrics.peer.mean_cur, divisor) for c in rows),
        unit=f"{analysis.context.symbol}{suffix}", number_format="#,##0.0")


def sow_chart(analysis: ExecAnalysis) -> ChartSeries:
    """Carrier share of wallet vs the peer average share, per country."""
    rows = _countries_by_premium(analysis)[:MAX_CHART_COUNTRIES]
    return ChartSeries(
        categories=tuple(c.country for c in rows),
        carrier=tuple(_rounded(c.metrics.sow_cur) for c in rows),
        peer=tuple(_rounded(c.metrics.peer.sow_cur) for c in rows),
        unit="%", number_format='0.0"%"')


def rank_text(m: SliceMetrics) -> str:
    """"#6 (+1)" — rank now, and its movement (positive = moved up)."""
    if m.rank_cur is None:
        return "Unranked"
    move = m.rank_movement
    if move is None:
        return f"#{m.rank_cur} (new)"
    if move == 0:
        return f"#{m.rank_cur} (=)"
    return f"#{m.rank_cur} ({move:+d})"


def rank_rows(analysis: ExecAnalysis) -> Tuple[Tuple[str, str], ...]:
    return tuple((c.country, rank_text(c.metrics))
                 for c in _countries_by_premium(analysis)[:MAX_RANK_ROWS])


def _sign(value: Optional[float]) -> int:
    """The sign a reader sees — a value that rounds to 0.0 is neutral, not red."""
    shown = round(value or 0.0, 1)
    return 0 if shown == 0 else (1 if shown > 0 else -1)


def table_rows(analysis: ExecAnalysis) -> Tuple[TableRow, ...]:
    """One row per product line, summed over the selected countries, largest first."""
    rows = analysis.product_totals[:MAX_TABLE_ROWS]
    symbol = analysis.context.symbol
    marsh_scale = money_scale(r.marsh_cur for r in rows)
    carrier_scale = money_scale(r.carrier_cur for r in rows)
    peer_scale = money_scale(r.peer.mean_cur for r in rows)
    out = []
    for r in rows:
        yoy = r.carrier_growth
        out.append(TableRow(
            product=r.scope.product,
            marsh=money_text(r.marsh_cur, symbol=symbol, scale=marsh_scale),
            carrier=money_text(r.carrier_cur, symbol=symbol, scale=carrier_scale),
            yoy=pct(yoy.pct, signed=True) if yoy.valid else ("New" if yoy.status == "new_activity" else "n/a"),
            yoy_sign=_sign(yoy.pct),
            mix=pct(r.mix_pct), sow=pct(r.sow_cur),
            rank=f"#{r.rank_cur}" if r.rank_cur else "—",
            peers=money_text(r.peer.mean_cur, symbol=symbol, scale=peer_scale)
            if r.peer.available else "n/a"))
    return tuple(out)


def portfolio_note(analysis: ExecAnalysis) -> str:
    """The detail slide's one-line rule-based read: how concentrated the portfolio is."""
    rows = analysis.product_totals
    carrier = analysis.context.carrier
    n = len(analysis.countries)
    where = f"across {n} countries" if n > 1 else f"in {analysis.countries[0].country}" if n else ""
    if not rows:
        return ""
    if len(rows) <= 3:
        return f"{len(rows)} lines make up all of {carrier}'s portfolio {where}."
    top3 = sum(r.mix_pct or 0.0 for r in rows[:3])
    return f"Top 3 lines hold {top3:.0f}% of {carrier}'s portfolio {where}."


def _survey_wave(analysis: ExecAnalysis) -> str:
    s = analysis.overall_survey
    if s is None or not s.available:
        return "Survey: not included" if not analysis.context.survey_on else "Survey: unavailable"
    return f"Survey wave {s.year}" + (f" vs {s.prior_year}" if s.prior_year else "")


def summary_footnote(analysis: ExecAnalysis, overall: Optional[StageResult]) -> str:
    ctx = analysis.context
    source = "AI-drafted, fact-checked" if overall and overall.source == "model" else "rule-based"
    return (f"{ctx.current_label} vs {ctx.prior_label} · {ctx.currency} · Marsh-placed premium · "
            f"peers = each country's approved peer set · {_survey_wave(analysis)} · "
            f"commentary {source}")


def detail_footnote(analysis: ExecAnalysis) -> str:
    ctx = analysis.context
    multi = (" (table: summed across countries) · Rank in the combined Marsh book"
             if ctx.multi_country else "")
    return (f"{ctx.current_label} vs {ctx.prior_label} · {ctx.currency} · Peer = mean of each "
            f"country's approved peers{multi} · Share of Portfolio = share of carrier premium")


def build_slide_content(analysis: ExecAnalysis, overall: Optional[StageResult], *,
                        today: Optional[date] = None) -> SlideContent:
    ctx = analysis.context
    day = today or date.today()
    return SlideContent(
        cover_title=f"{ctx.carrier} Executive Summary",
        cover_date=f"{day:%B} {day.day}, {day.year}",
        summary_title=f"{ctx.carrier} — Carrier Performance Executive Summary ({ctx.current_label})",
        summary_paragraph=summary_paragraph(overall),
        summary_footnote=summary_footnote(analysis, overall),
        detail_title=f"{ctx.carrier} — Portfolio & Market Performance Detail",
        premium_chart=premium_chart(analysis),
        sow_chart=sow_chart(analysis),
        rank_rows=rank_rows(analysis),
        table_rows=table_rows(analysis),
        note=portfolio_note(analysis),
        detail_footnote=detail_footnote(analysis),
    )
