"""Onboarding, and the calculation panel a business reader can actually use.

Two of this round's reports:

  * there was no way in for a new user — the app opened on a prompt box and left
    them to guess what it could do;
  * "How this was calculated" showed the raw SQL, which is the wrong artefact for
    the person asking whether they can trust a number.

Run:  pytest tests/test_tour_and_steps.py -q -o pythonpath=.
"""
from __future__ import annotations

from dash.development.base_component import Component

from core.answers.steps import describe, describe_all, humanise
from ui.components.tour import tour_button, tour_dialog
from ui.shell.layout import app_shell
from ui.shell.tour import STEPS

QUERY = (
    "SELECT Product_Line, SUM(Premium) AS Premium FROM gpr_fact "
    "WHERE Country = 'Singapore' AND Year IN ('2024','2025') "
    "GROUP BY Product_Line ORDER BY Premium DESC LIMIT 10"
)


def walk(node):
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)


def ids(node) -> list:
    return [getattr(n, "id", None) for n in walk(node)]


def classes(node) -> list:
    return [(getattr(n, "className", "") or "") for n in walk(node)]


def text_of(node) -> str:
    out = []
    for n in walk(node):
        children = getattr(n, "children", None)
        if isinstance(children, str):
            out.append(children)
    return " ".join(out)


# ── the calculation, in English ─────────────────────────────────────────────


def test_a_query_becomes_steps_a_business_reader_can_follow():
    steps = describe(QUERY, row_count=12, lens="premium")
    assert steps == [
        "Read the gpr fact data",
        "Limited to country Singapore",
        "Limited to year 2024, 2025",
        "Added up premium",
        "Split it by product line",
        "Ordered by premium, highest first",
        "Kept the top 10",
        "12 rows came back",
    ]


def test_no_step_leaks_sql_vocabulary():
    import re

    joined = " ".join(describe(QUERY, row_count=12)).lower()
    # Word-boundary matched: "Limited to country Singapore" is English that
    # happens to contain "limit", and banning the substring would ban the phrase.
    for token in ("select", "group by", "where", "sum", "order by", "desc"):
        assert not re.search(rf"\b{token}\b", joined), token
    # "Limited to country Singapore" is English that happens to begin with the
    # letters of LIMIT, so that clause is checked as the SQL it would be.
    assert "limit 10" not in joined


def test_a_signed_off_metric_says_so_instead_of_showing_a_query():
    steps = describe("-- computed: share_of_wallet", row_count=3)
    assert steps[0] == "Used the approved share_of_wallet calculation"


def test_an_unreadable_query_degrades_to_what_is_still_true():
    """Never guess: the source and the row count are always honest."""
    steps = describe("something that is not sql", row_count=5, lens="survey")
    assert steps == ["Read the survey data", "5 rows came back"]


def test_a_column_name_is_said_the_way_a_person_says_it():
    assert humanise("Product_Line") == "product line"
    assert humanise("dim_Carrier_Group") == "carrier group"
    assert humanise('"gpr"."Billing_Date"') == "billing date"


def test_one_row_is_not_pluralised():
    assert "1 row came back" in describe(QUERY, row_count=1)


def test_every_query_is_described_in_order():
    described = describe_all(
        [
            {"lens": "premium", "sql": QUERY, "row_count": 12},
            {"lens": "survey", "sql": "SELECT AVG(Score) FROM survey", "row_count": 4},
        ]
    )
    assert [d["lens"] for d in described] == ["premium", "survey"]
    assert "Averaged score" in described[1]["steps"]


# ── the tour ────────────────────────────────────────────────────────────────


def test_the_tour_covers_the_whole_loop():
    titles = [step.title for step in STEPS]
    assert len(titles) >= 6
    joined = " ".join(t.lower() for t in titles)
    for topic in ("ask", "answer", "check", "drove", "board"):
        assert topic in joined, topic


def test_every_step_has_a_drawing_of_its_own():
    """A tour that only tells is a help page; the pictures are the point."""
    for step in STEPS:
        art = step.art()
        assert art is not None
        assert any("tour-shape" in c or "tour-label" in c for c in classes(art)), step.title


def test_the_dialog_shows_one_step_at_a_time():
    dialog = tour_dialog()
    panels = [n for n in walk(dialog) if (getattr(n, "className", "") or "") == "tour-step"]
    assert len(panels) == len(STEPS)
    assert panels[0].style == {}
    assert all(p.style == {"display": "none"} for p in panels[1:])


def test_the_dialog_has_a_dot_per_step_and_a_way_forward():
    dialog = tour_dialog()
    flat = [i for i in ids(dialog) if isinstance(i, str)]
    assert {"tour-next", "tour-back", "tour-close"} <= set(flat)
    dots = [i for i in ids(dialog) if isinstance(i, dict) and i.get("type") == "tour-dot"]
    assert len(dots) == len(STEPS)


def test_the_first_step_cannot_go_back():
    dialog = tour_dialog()
    back = next(n for n in walk(dialog) if getattr(n, "id", None) == "tour-back")
    assert back.disabled is True


def test_the_tour_is_reachable_from_the_navbar():
    assert getattr(tour_button(), "id", None) == "tour-open"
    shell = app_shell(1, "jash", "chat")
    flat = [i for i in ids(shell) if isinstance(i, str)]
    assert "tour-open" in flat and "tour-modal" in flat


def test_the_tour_explains_the_peer_minimum_where_a_user_would_meet_it():
    """The ≥5 rule is a surprise unless something says why it exists."""
    shown = " ".join(step.body for step in STEPS)
    assert "five" in shown.lower()
