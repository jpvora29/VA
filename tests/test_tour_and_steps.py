"""Onboarding, and the calculation panel a business reader can actually use.

Two reports drove the first version of both:

  * there was no way in for a new user — the app opened on a prompt box and left
    them to guess what it could do;
  * "How this was calculated" showed the raw SQL, which is the wrong artefact for
    the person asking whether they can trust a number.

Two more drove this one, and they are what most of the assertions below are
about:

  * the panel was still technical and still a wall — eight one-clause steps per
    query, a table name leaking as "gpr fact data", the same measure listed three
    times because of a window function, and a last line reading "12 rows came
    back" that meant nothing to the reader;
  * the tour was "very basic" — eight screens that said what existed without
    teaching anyone to use it.

Run:  pytest tests/test_tour_and_steps.py -q -o pythonpath=.
"""
from __future__ import annotations

import re

from dash.development.base_component import Component

from core.answers.steps import (
    Calculation,
    describe,
    describe_all,
    field_name,
    humanise,
    title_of,
)
from ui.components.tour import tour_button, tour_dialog
from ui.shell.layout import app_shell
from ui.shell.tour import STEPS, chapters, try_it_questions

QUERY = (
    "SELECT Product_Line, SUM(Premium) AS Premium FROM gpr_fact "
    "WHERE Country = 'Singapore' AND Year IN ('2024','2025') "
    "GROUP BY Product_Line ORDER BY Premium DESC LIMIT 10"
)

# A window function nests one aggregate inside another, which is how the panel
# came to say "Added up sum(premium".
WINDOWED = (
    "SELECT Product_Line, SUM(Premium) AS Premium, "
    "SUM(Premium)/SUM(SUM(Premium)) OVER () AS Share_of_Wallet "
    "FROM gpr_fact WHERE Country = 'Canada' GROUP BY Product_Line"
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
    calculation = describe(QUERY, row_count=12, lens="premium")
    assert calculation.steps == (
        "Started with the Marsh-placed premium records",
        "Narrowed it to country Singapore and year 2024, 2025",
        "Added up premium for each product line",
        "Ranked them by premium, highest first",
        "Kept the top 10",
    )


def test_the_filters_are_one_sentence_not_one_line_each():
    """Three filters as three steps is how a five-step explanation became a wall."""
    steps = describe(QUERY, row_count=12, lens="premium").steps
    narrowing = [s for s in steps if s.startswith("Narrowed")]
    assert len(narrowing) == 1
    assert "Singapore" in narrowing[0] and "2024" in narrowing[0]


def test_the_measure_and_the_cut_are_one_thought():
    steps = describe(QUERY, row_count=12).steps
    assert "Added up premium for each product line" in steps
    assert "Split it by product line" not in steps


def test_a_window_function_does_not_invent_a_third_measure():
    """`SUM(SUM(Premium))` read as a measure and printed "Added up sum(premium"."""
    steps = describe(WINDOWED, row_count=3, lens="premium").steps
    measures = [s for s in steps if s.startswith("Added up")]
    assert measures == ["Added up premium for each product line"]
    assert not any("sum(" in s.lower() for s in steps)


def test_the_last_step_says_what_came_out_in_the_units_of_the_question():
    """"12 rows came back" is the machine's unit and was the panel's worst line."""
    calculation = describe(QUERY, row_count=12, lens="premium")
    assert calculation.outcome == "That left 12 product lines to report on"
    assert calculation.all_steps[-1] == calculation.outcome


def test_an_ungrouped_total_is_not_described_as_rows():
    assert describe("SELECT SUM(Premium) FROM gpr", row_count=1).outcome == (
        "That gave us a single total"
    )


def test_the_source_is_named_in_business_words_not_as_a_table():
    """"Read the gpr fact data" is a schema object with a space in it."""
    steps = describe(QUERY, row_count=12, lens="premium").steps
    assert steps[0] == "Started with the Marsh-placed premium records"
    assert "gpr" not in " ".join(steps).lower()


def test_an_unmapped_source_still_reads_as_english():
    steps = describe("SELECT * FROM broker_appetite", row_count=2, lens="").steps
    assert steps[0] == "Started with the broker appetite data"


def test_no_step_leaks_sql_vocabulary():
    joined = " ".join(describe(QUERY, row_count=12).all_steps).lower()
    # Word-boundary matched: "Limited to country Singapore" is English that
    # happens to contain "limit", and banning the substring would ban the phrase.
    for token in ("select", "group by", "where", "sum", "order by", "desc", "row"):
        assert not re.search(rf"\b{token}\b", joined), token
    assert "limit 10" not in joined


def test_a_signed_off_metric_says_so_instead_of_showing_a_query():
    calculation = describe("-- computed: share_of_wallet", row_count=3)
    assert calculation.steps[0] == "Used the approved share of wallet calculation"
    assert calculation.sql == ""


def test_an_unreadable_query_degrades_to_what_is_still_true():
    """Never guess: the source and the outcome are always honest."""
    calculation = describe("something that is not sql", row_count=5, lens="survey")
    assert calculation.steps == ("Started with the broker survey responses",)
    assert calculation.outcome == "That gave us 5 results"


def test_a_column_name_is_said_the_way_a_person_says_it():
    assert humanise("Product_Line") == "product line"
    assert humanise("dim_Carrier_Group") == "carrier group"
    assert humanise('"gpr"."Billing_Date"') == "billing date"
    assert humanise("gpr_fact") == "gpr"


def test_a_field_is_referred_to_without_its_schema_suffix():
    """A reader already knows Zurich is a name."""
    assert field_name("Carrier_Name") == "carrier"
    assert field_name("Country") == "country"


def test_a_lone_product_line_is_not_pluralised_into_nonsense():
    assert describe(QUERY, row_count=1).outcome == "That left 1 product line to report on"


def test_every_query_is_described_in_order():
    described = describe_all(
        [
            {"lens": "premium", "sql": QUERY, "row_count": 12},
            {"lens": "survey", "sql": "SELECT AVG(Score) FROM survey", "row_count": 4},
        ]
    )
    assert [d.title for d in described] == ["Premium data", "Broker survey data"]
    assert isinstance(described[0], Calculation)
    assert "Averaged score" in described[1].steps


# ── the tour ────────────────────────────────────────────────────────────────


def test_the_tour_covers_the_whole_loop():
    titles = [step.title for step in STEPS]
    assert len(titles) >= 10
    joined = " ".join(t.lower() for t in titles)
    for topic in ("ask", "answer", "check", "drove", "board", "deck"):
        assert topic in joined, topic


def test_every_step_has_a_drawing_of_its_own():
    """A tour that only tells is a help page; the pictures are the point."""
    for step in STEPS:
        art = step.art()
        assert art is not None
        assert any("tour-shape" in c or "tour-label" in c for c in classes(art)), step.title


def test_every_step_says_how_and_not_only_what():
    """The report on the first tour: it listed features without teaching them."""
    for step in STEPS:
        assert len(step.points) >= 2, step.title
        assert all(len(p) > 30 for p in step.points), step.title


def test_the_steps_fall_into_named_chapters_that_cover_every_step():
    marks = chapters()
    assert len(marks) == 4
    assert sum(c.size for c in marks) == len(STEPS)
    assert [c.start for c in marks] == sorted(c.start for c in marks)
    assert marks[0].start == 0


def test_a_new_user_can_ask_a_real_question_from_the_tour():
    """Onboarding that ends in a working answer is onboarding people finish."""
    questions = try_it_questions()
    assert len(questions) >= 4
    assert all("?" in q or q.startswith("Brief") or q.startswith("Give") for q in questions.values())


def test_the_dialog_shows_one_step_at_a_time():
    dialog = tour_dialog()
    panels = [n for n in walk(dialog) if (getattr(n, "className", "") or "") == "tour-step"]
    assert len(panels) == len(STEPS)
    assert panels[0].style == {}
    assert all(p.style == {"display": "none"} for p in panels[1:])


def test_the_dialog_has_a_dot_per_step_and_a_way_forward():
    dialog = tour_dialog()
    flat = [i for i in ids(dialog) if isinstance(i, str)]
    assert {"tour-next", "tour-back", "tour-close", "tour-progress"} <= set(flat)
    dots = [i for i in ids(dialog) if isinstance(i, dict) and i.get("type") == "tour-dot"]
    assert len(dots) == len(STEPS)


def test_the_rail_can_jump_to_any_chapter():
    dialog = tour_dialog()
    rail = [i for i in ids(dialog) if isinstance(i, dict) and i.get("type") == "tour-chapter"]
    assert [r["index"] for r in rail] == [c.start for c in chapters()]


def test_a_try_it_button_exists_for_every_step_that_offers_one():
    dialog = tour_dialog()
    tries = [i for i in ids(dialog) if isinstance(i, dict) and i.get("type") == "tour-try"]
    assert sorted(t["index"] for t in tries) == sorted(try_it_questions())


def test_a_try_it_button_carries_its_question_where_the_callback_reads_it():
    """The clientside handler looks the question up by `title`."""
    dialog = tour_dialog()
    buttons = {
        n.id["index"]: n
        for n in walk(dialog)
        if isinstance(getattr(n, "id", None), dict) and n.id.get("type") == "tour-try"
    }
    for index, question in try_it_questions().items():
        assert buttons[index].title == question


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


def test_the_tour_names_every_workspace():
    """"Understand the application in and out" starts with knowing it has four."""
    shown = " ".join([s.body for s in STEPS] + [p for s in STEPS for p in s.points])
    for workspace in ("Chat", "Studio", "Recap", "MoM"):
        assert workspace in shown, workspace


def test_a_lens_has_ONE_name_across_the_card():
    """The evidence tab and the calculation heading name the same source.

    A tab reading "Premium" over steps reading "the gpr fact data" is what two
    copies of this vocabulary produce.
    """
    from ui.evidence import LENS_LABELS

    from core.answers import lenses

    assert LENS_LABELS is lenses.LABELS
    for lens in ("premium", "gpr", "survey"):
        assert title_of(lens) == f"{lenses.label_of(lens)} data"
