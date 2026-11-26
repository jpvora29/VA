"""Deck wording follows the period picked, Premium KPIs carry one decimal, and the GWP
page's changes are coloured by their own sign.

The regressions:

* a deck pinned to a quarter still said "FY 2026" on every page;
* the Country page's period table said "TTM …" on a YTD deck;
* R12M ignored the Quarter — "R12M, Q2 2026" reported April–June, and the picker's
  "Ends" month never moved;
* the GWP Performance YoY badge was red even for growth (the template's example colour);
* the Overall page's Premium KPIs were rounded to whole millions.
"""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

import pytest

from studio import period as P
from studio.quarter_period import (
    latest_quarter,
    picked_quarters,
    quarter_anchor,
    quarter_label,
    quarters_in_filters,
)

LATEST = (2026, 8)


# ── what a quarter means ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "values,expected",
    [
        ("Q2", (2,)),
        (["Q3", "Q1"], (1, 3)),
        (["2026 Q4"], (4,)),
        ([], ()),
        (None, ()),
    ],
)
def test_picked_quarters_reads_any_label(values, expected):
    assert picked_quarters(values) == expected


def test_the_last_quarter_picked_anchors_r12m():
    assert latest_quarter(["Q1", "Q2"]) == 2
    assert latest_quarter(None) is None


@pytest.mark.parametrize(
    "quarters,expected",
    [
        ((2,), "Q2 2026"),
        ((1, 2), "Q1–Q2 2026"),
        ((1, 3), "Q1, Q3 2026"),
        ((1, 2, 3, 4), None),
        ((), None),
    ],
)
def test_quarter_label(quarters, expected):
    assert quarter_label(quarters, 2026) == expected


def test_quarter_anchor_is_capped_at_the_latest_month():
    assert quarter_anchor(2026, 2, LATEST) == (2026, 6)
    assert quarter_anchor(2026, 3, LATEST) == (2026, 8)
    assert quarter_anchor(2025, 4, LATEST) == (2025, 12)


def test_quarters_in_resolved_filters():
    assert quarters_in_filters({"Quarter": ("Q2",)}) == (2,)
    assert quarters_in_filters({"Month_Name": ("April", "May", "June")}) == (2,)
    assert quarters_in_filters({"Month_Name": ("April", "May")}) == ()
    assert quarters_in_filters({}) == ()


# ── R12M honours the quarter ─────────────────────────────────────────────────


def _choice(basis="calendar", quarter=None, year=None, date_to=None):
    selection = {"period_basis": basis, "filters": {}}
    if quarter:
        selection["filters"]["quarter"] = quarter
    if year:
        selection["filters"]["year"] = year
    if date_to:
        selection["date_to"] = date_to
    return P.period_choice(selection)


def test_r12m_with_a_quarter_ends_at_the_quarter_end():
    window = P.window_for(_choice("r12m", ["Q2"]), latest=LATEST, year_pin=2026)

    assert (window.start, window.end) == (date(2025, 7, 1), date(2026, 6, 30))
    assert window.label() == "TTM Jun 2026"


def test_r12m_quarter_in_a_pinned_earlier_year():
    window = P.window_for(_choice("r12m", ["Q4"]), latest=LATEST, year_pin=2025)

    assert window.end == date(2025, 12, 31)


def test_r12m_explicit_end_month_wins_over_the_quarter():
    window = P.window_for(
        _choice("r12m", ["Q2"], date_to="2026-03-31"),
        latest=LATEST,
        year_pin=2026,
    )

    assert window.end == date(2026, 3, 31)


def test_r12m_without_a_quarter_is_unchanged():
    window = P.window_for(_choice("r12m"), latest=LATEST)

    assert window.end == date(2026, 8, 31)


def test_on_r12m_the_quarter_does_not_narrow_rows():
    r12m = P.r12m_window(2026, 6)
    filters = {"carrier": "Zurich", "quarter": ["Q2"]}

    assert "quarter" not in P.row_filters(filters, r12m)
    assert P.row_filters(filters, None) == filters


def test_setup_sentence_names_the_quarter():
    text = P.describe(_choice("calendar", ["Q2"]), latest=LATEST, year_pin=2026)

    assert text.startswith("Q2 2026 against Q2 2025")


def test_setup_sentence_on_r12m_quarter():
    text = P.describe(_choice("r12m", ["Q2"]), latest=LATEST, year_pin=2026)

    assert text.startswith("R12M Jun 2026")


# ── what pages call the period ───────────────────────────────────────────────


def test_display_period_names_the_quarter():
    assert P.display_period(None, 2026, quarters=(2,)) == "Q2 2026"
    assert P.display_period(None, 2026, prior=True, quarters=(2,)) == "Q2 2025"


def test_display_period_without_a_quarter_is_unchanged():
    assert P.display_period(None, 2026) == "FY2026"
    assert P.display_period(P.r12m_window(2026, 8), 2026) == "TTM Aug 2026"


def test_a_quarter_beats_a_ytd_window():
    ytd = P.PeriodWindow(date(2026, 1, 1), date(2026, 8, 31), kind=P.KIND_RANGE)

    assert P.display_period(ytd, 2026, quarters=(2,)) == "Q2 2026"
    assert P.display_period(ytd, 2026) == "YTD Aug 2026"


def test_deck_period_labels_follow_a_quarter():
    from studio.template_fill.bindings import period_labels

    result = SimpleNamespace(period=None, resolved_filters={"Quarter": ("Q2",)})

    assert period_labels(result, 2026) == {
        "period_labels": {"2026": "Q2 2026", "2025": "Q2 2025"}
    }
    plain = SimpleNamespace(period=None, resolved_filters={})
    assert period_labels(plain, 2026) == {}


def test_fy_heading_becomes_the_quarter():
    from studio.template_fill.year_labels import year_subs

    values = {
        "template_year": 2025,
        "period_year": 2026,
        "period_labels": {"2026": "Q2 2026", "2025": "Q2 2025"},
    }
    text = "Carrier trading highlights FY 2025"
    for pattern, repl in year_subs(values, today=date(2026, 9, 1)):
        text = pattern.sub(repl, text)

    assert text == "Carrier trading highlights Q2 2026"


def test_country_table_follows_the_deck_basis_not_ttm():
    from studio.template_fill.gwp_page import Reading, _ttm_readings

    readings = {"carrier_gwp": Reading(current_year=2026, prior_year=2025)}
    calendar = SimpleNamespace(period=None, resolved_filters={})
    quarter = SimpleNamespace(period=None, resolved_filters={"Quarter": ("Q2",)})
    ytd = SimpleNamespace(
        period=P.PeriodWindow(date(2026, 1, 1), date(2026, 8, 31), kind=P.KIND_RANGE),
        resolved_filters={},
    )

    assert _ttm_readings(calendar, readings).current_label == "FY2026"
    assert _ttm_readings(quarter, readings).prior_label == "Q2 2025"
    assert _ttm_readings(ytd, readings).current_label == "YTD Aug 2026"


def test_ttm_header_is_renamed_to_the_basis_label():
    from studio.template_fill.gwp_page import _period_header

    assert _period_header("TTM April 2026", 2026, "YTD Aug 2026") == "YTD Aug 2026"


# ── the picker's "Ends" month follows the quarter ────────────────────────────


def test_quarter_change_on_r12m_moves_the_end_month():
    from studio.authoring.period_picker import _QUARTER_FILTER, next_state

    dates, view, _basis = next_state(
        _QUARTER_FILTER,
        dates={"from": None, "to": None, "custom": False},
        view={},
        basis="r12m",
        meta={"latest": list(LATEST)},
        quarters=["Q2"],
        years=["2026"],
    )

    assert dates == {"from": None, "to": "2026-06-30", "custom": False}
    assert view["year"] == 2026


def test_switching_to_r12m_with_a_quarter_pinned_anchors_it():
    from studio.authoring.period_picker import next_state

    dates, _view, _basis = next_state(
        "studio-period-basis",
        dates={"from": None, "to": None, "custom": False},
        view={},
        basis="r12m",
        meta={"latest": list(LATEST)},
        quarters=["Q1"],
        years=None,
    )

    assert dates["to"] == "2026-03-31"


def test_quarter_on_ytd_shows_the_quarter_end_without_a_window():
    """YTD + Q2: the rows are the quarter, so "Ends" reads Jun and the line names Q2 —
    while the store stays on "latest" (no date window, so no warehouse copy)."""
    from studio.authoring.period_picker import _QUARTER_FILTER, next_state, paint

    meta = {"latest": list(LATEST)}
    stale = {"from": "2026-01-01", "to": "2026-08-31", "custom": False}
    dates, view, _basis = next_state(
        _QUARTER_FILTER,
        dates=stale,
        view={},
        basis="calendar",
        meta=meta,
        quarters=["Q2"],
        years=["2026"],
    )

    assert dates == {"from": None, "to": None, "custom": False}
    painted = paint(dates, view, "calendar", meta, ["2026"], ["Q2"])
    assert painted[5] == "Jun 2026"
    assert painted[10] == "Q2 2026 vs Q2 2025"


def test_clearing_the_quarter_on_ytd_goes_back_to_the_year():
    from studio.authoring.period_picker import paint

    meta = {"latest": list(LATEST)}
    latest_store = {"from": None, "to": None, "custom": False}

    assert (
        paint(latest_store, {}, "calendar", meta, ["2026"], None)[5]
        == "Aug 2026 (latest)"
    )
    assert paint(latest_store, {}, "calendar", meta, ["2025"], [])[5] == "Dec 2025"


def test_ytd_quarter_in_an_earlier_year():
    from studio.page.authoring import period_picker as PP

    answer = PP.read_answer({})
    assert PP.trigger_label(answer, "calendar", LATEST, 2025, ["Q1"]) == "Mar 2025"
    assert (
        PP.summary_line(answer, "calendar", LATEST, 2025, ["Q1"])
        == "Q1 2025 vs Q1 2024"
    )


# ── Premium KPIs: one decimal ────────────────────────────────────────────────


def test_money_decimals_from_the_map():
    from studio.template_fill.render import render_token

    assert render_token("$xxx.xm", 123_456_789.0, "money", decimals=1).endswith(
        "123.5M"
    )
    assert render_token("$xx,xxxm", 9_234_000_000.0, "money", decimals=1).endswith(
        "9.2B"
    )
    assert render_token("$xxx.xm", 123_456_789.0, "money").endswith("123M")


def test_overall_premium_kpis_ask_for_one_decimal_and_keep_it_through_the_manifest():
    from studio.template_fill import roles as R
    from studio.template_fill.binding_map import get_binding_map

    bmap = get_binding_map("overall")
    kpis = {
        b.role: b.decimals
        for b in bmap.bindings
        if b.role in ("carrier_gwp", "marsh_gwp")
    }
    assert kpis == {"carrier_gwp": 1, "marsh_gwp": 1}

    round_trip = R.manifest_to_dicts(R.manifest_from_dicts(bmap.manifest()))
    kept = {
        d["role"]: d["slot"].get("decimals") for d in round_trip if d["role"] in kpis
    }
    assert kept == kpis


def test_materialized_premium_kpi_has_one_decimal():
    from studio.template_fill.binding_map import get_binding_map
    from studio.template_fill.model import materialize_fields

    doc = {
        "manifest": get_binding_map("overall").manifest(),
        "values": {"carrier_gwp": 241_330_000.0, "marsh_gwp": 812_400_000.0},
    }
    texts = {f["role"]: f["text"] for f in materialize_fields(doc).values()}

    assert re.search(r"241\.3M$", texts["carrier_gwp"])
    assert re.search(r"812\.4M$", texts["marsh_gwp"])


def _headline_facts() -> dict:
    return {
        "subject": "Zurich",
        "carrier": {
            "current": 410_100_000.0,
            "prior": 324_400_000.0,
            "pct": 26.4,
            "delta": 85_700_000.0,
            "current_year": 2025,
        },
        "marsh": {"current": 812_400_000.0, "prior": 737_100_000.0, "pct": 10.2},
    }


def test_commentary_headline_premium_matches_the_one_decimal_kpi():
    """The Highlights page's commentary sat beside a "$410.1M" tile and said "$410M"."""
    from studio.template_fill import commentary_evidence as E

    pack = E.build_pack(_headline_facts())
    rendered = {e.fact_id: e.rendered for e in pack.items}

    assert rendered["carrier.premium"].endswith("410.1M")
    assert rendered["carrier.prior"].endswith("324.4M")
    assert rendered["carrier.delta"].endswith("85.7M")
    assert rendered["marsh.premium"].endswith("812.4M")
    assert rendered["marsh.prior"].endswith("737.1M")


def test_a_one_decimal_premium_sentence_passes_the_number_check():
    from studio.template_fill import commentary_evidence as E
    from studio.template_fill.commentary_verify import Judged, check_numbers

    pack = E.build_pack(_headline_facts())
    sentence = "Zurich's Marsh-placed premium grew 26.4% to $410.1M."
    verdict = check_numbers(
        [Judged(sentence, fact_ids=("carrier.premium", "carrier.yoy"))], pack
    )

    assert verdict.kept == (sentence,)


def test_fallback_commentary_says_the_headline_premium_to_one_decimal():
    from studio.template_fill.feedback import _thesis_points

    facts = _headline_facts()
    facts["period"] = {}

    assert "$410.1M" in _thesis_points(facts)[0]


# ── GWP page: colour by sign ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("23.0%", 1),
        ("+9.1%▲", 1),
        ("-0.2 pp", -1),
        ("−1.0%", -1),
        ("0.0%", 0),
        ("n/a", 0),
    ],
)
def test_sign_of(text, expected):
    from studio.template_fill.sign_color import sign_of

    assert sign_of(text) == expected


def _badge_slide():
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    badge = slide.shapes.add_shape(MSO_SHAPE.OVAL, 0, 0, Inches(1), Inches(1))
    badge.fill.solid()
    badge.fill.fore_color.rgb = RGBColor.from_string("C53532")
    badge.text_frame.text = "-1.0%"
    return badge


def test_positive_yoy_badge_turns_green():
    from studio.template_fill.fill import _write_field

    badge = _badge_slide()
    _write_field(
        badge, {"where": ["para", 0], "text": "23.0%", "role": "gwp:1:panel:yoy"}, None
    )

    assert str(badge.fill.fore_color.rgb) == "2F7500"


def test_negative_yoy_badge_stays_red():
    from studio.template_fill.fill import _write_field

    badge = _badge_slide()
    _write_field(
        badge, {"where": ["para", 0], "text": "-4.2%", "role": "gwp:1:panel:yoy"}, None
    )

    assert str(badge.fill.fore_color.rgb) == "C53532"


def test_table_change_text_is_inked_by_sign():
    from studio.template_fill.fill import _write_field

    badge = _badge_slide()
    _write_field(
        badge, {"where": ["para", 0], "text": "-0.2 pp", "role": "gwp:1:sow:chg"}, None
    )

    run = badge.text_frame.paragraphs[0].runs[0]
    assert str(run.font.color.rgb) == "C53532"


# ── end to end: a quarter deck ───────────────────────────────────────────────


def _leaves(shapes):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for sh in shapes:
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _leaves(sh.shapes)
        else:
            yield sh


def _texts(path):
    from pptx import Presentation

    for index, slide in enumerate(Presentation(path).slides):
        for sh in _leaves(slide.shapes):
            if sh.has_text_frame:
                yield index, sh, sh.text_frame.text
            elif getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    for cell in row.cells:
                        yield index, sh, cell.text


@pytest.mark.e2e
def test_a_quarter_deck_names_the_quarter_everywhere(tmp_path, monkeypatch):
    from studio.compute import compute_overall
    from studio.template_fill.assemble import assemble_deck

    monkeypatch.setenv("COMMENTARY_MODE", "auto")
    result = compute_overall(
        filters={
            "carrier": "Zurich",
            "country": ["Singapore"],
            "year": [2024],
            "quarter": ["Q2"],
        }
    )
    out = assemble_deck(
        result,
        out_path=str(tmp_path / "deck.pptx"),
        work_dir=str(tmp_path / "work"),
    )
    texts = list(_texts(out))
    joined = "\n".join(text for _i, _sh, text in texts)

    assert "Q2 2024" in joined
    assert not re.search(r"\bFY\s?20\d\d\b", joined), "no FY label on a quarter deck"
    assert not re.search(r"\bTTM\b", joined), "a quarter deck carries no TTM table"
    assert re.search(r"\d+\.\dM\b", joined), "Premium KPIs carry one decimal"


# ── like-for-like YTD: the plain YTD compares the same months ────────────────

_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@pytest.fixture(scope="module")
def running_year_engine(tmp_path_factory):
    """A book with all of 2025 and January–August 2026, 100 a month per carrier."""
    import pandas as pd
    from sqlalchemy import create_engine

    rows = []
    for year, last in ((2025, 12), (2026, 8)):
        for month in range(1, last + 1):
            for carrier in ("Zurich", "AIG"):
                rows.append(
                    {
                        "Carrier_Group": carrier,
                        "Country": "Singapore",
                        "Product_Line": "Cyber",
                        "Year": year,
                        "Month_Name": _MONTH_NAMES[month - 1],
                        "Premium": 100.0,
                    }
                )
    path = tmp_path_factory.mktemp("ytd") / "book.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    pd.DataFrame(rows).to_sql("GPR", engine, index=False)
    return engine


def test_default_ytd_window_only_for_a_running_year():
    assert P.default_ytd_window(2026, (2026, 8)).label() == "YTD Aug 2026"
    assert P.default_ytd_window(2025, (2025, 12)) is None
    assert P.default_ytd_window(2025, (2026, 8)) is None
    assert P.default_ytd_window(2026, None) is None


def test_plain_ytd_compares_the_same_months(running_year_engine):
    from studio.compute import build_compute_request, period_totals

    request = build_compute_request(
        filters={"carrier": "Zurich", "country": ["Singapore"], "year": [2026]},
        engine=running_year_engine,
    )

    assert request.period.label() == "YTD Aug 2026"
    assert set(request.filters["Month_Name"]) == set(_MONTH_NAMES[:8])
    totals = period_totals("gpr", request.filters, running_year_engine)
    assert (totals["current"], totals["prior"]) == (800.0, 800.0)
    assert totals["pct"] == 0.0


def test_plain_ytd_labels_pages_ytd(running_year_engine):
    from studio.compute import build_compute_request

    request = build_compute_request(
        filters={"carrier": "Zurich", "year": [2026]},
        engine=running_year_engine,
    )
    result = SimpleNamespace(period=request.period, resolved_filters=request.filters)

    assert P.result_period_names(result, 2026) == ("YTD Aug 2026", "YTD Aug 2025")


def test_a_complete_year_is_compared_whole(running_year_engine):
    from studio.compute import build_compute_request

    request = build_compute_request(
        filters={"carrier": "Zurich", "year": [2025]},
        engine=running_year_engine,
    )

    assert request.period is None
    assert "Month_Name" not in request.filters


def test_a_pinned_quarter_is_left_to_the_quarter(running_year_engine):
    from studio.compute import build_compute_request

    request = build_compute_request(
        filters={"carrier": "Zurich", "year": [2026], "quarter": ["Q1"]},
        engine=running_year_engine,
    )

    assert request.period is None
    assert set(request.filters["Month_Name"]) == {"January", "February", "March"}


def test_ytd_months_are_not_read_as_quarters():
    assert quarters_in_filters({"Month_Name": _MONTH_NAMES[:8]}) == ()
    ytd_jun = P.default_ytd_window(2026, (2026, 6))
    assert P.display_period(ytd_jun, 2026, quarters=(1, 2)) == "YTD Jun 2026"


# ── "Ends" follows a cleared quarter and a changed year ──────────────────────


def _after(trigger, *, basis, quarters=None, years=None, dates=None):
    from studio.authoring.period_picker import next_state

    return next_state(
        trigger,
        dates=dates or {"from": None, "to": None, "custom": False},
        view={},
        basis=basis,
        meta={"latest": list(LATEST)},
        quarters=quarters,
        years=years,
    )


def test_clearing_the_quarter_on_r12m_goes_back_to_the_latest_month():
    from studio.authoring.period_picker import _QUARTER_FILTER

    picked = {"from": None, "to": "2026-03-31", "custom": False}
    dates, view, _ = _after(_QUARTER_FILTER, basis="r12m", years=["2026"], dates=picked)

    assert dates == {"from": None, "to": None, "custom": False}
    assert view["year"] == 2026


def test_changing_the_year_on_r12m_moves_the_end_into_that_year():
    from studio.authoring.period_picker import _YEAR_FILTER, paint

    dates, view, _ = _after(_YEAR_FILTER, basis="r12m", years=["2025"])

    assert dates["to"] is None and view["year"] == 2025
    painted = paint(dates, view, "r12m", {"latest": list(LATEST)}, ["2025"])
    assert painted[5] == "Aug 2025"  # the trigger: R12M to Aug 2025, not "latest 2026"


def test_changing_the_year_with_a_quarter_keeps_the_quarter_end():
    from studio.authoring.period_picker import _YEAR_FILTER

    dates, _view, _ = _after(
        _YEAR_FILTER, basis="r12m", quarters=["Q1"], years=["2025"]
    )

    assert dates["to"] == "2025-03-31"


def test_changing_the_year_on_ytd_clears_a_stale_end_month():
    from studio.authoring.period_picker import _YEAR_FILTER, paint

    picked = {"from": "2026-01-01", "to": "2026-08-31", "custom": False}
    dates, view, _ = _after(
        _YEAR_FILTER, basis="calendar", years=["2025"], dates=picked
    )

    assert dates == {"from": None, "to": None, "custom": False}
    painted = paint(dates, view, "calendar", {"latest": list(LATEST)}, ["2025"])
    assert painted[5] == "Dec 2025"
    assert painted[10] == "FY2025 vs FY2024"


def test_a_ytd_custom_range_survives_a_year_change():
    from dash import no_update

    from studio.authoring.period_picker import _YEAR_FILTER

    custom = {"from": "2026-03-01", "to": "2026-08-31", "custom": True}
    dates, _view, _ = _after(
        _YEAR_FILTER, basis="calendar", years=["2025"], dates=custom
    )

    assert dates is no_update


def test_the_latest_year_still_reads_latest():
    from studio.page.authoring import period_picker as PP

    answer = PP.read_answer({})
    assert PP.trigger_label(answer, "r12m", LATEST, 2026) == "Aug 2026 (latest)"
