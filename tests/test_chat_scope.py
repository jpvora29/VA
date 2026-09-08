"""The analytical scope shown as context pills.

Three surfaces state the scope of an answer — the pills at the head of the
answer itself, the Boardroom header, and every exported slide — and all three
read `core.scope`. These tests pin what a chip is allowed to claim: the resolved
filter wins over the raw mention, an inherited filter says so, and nothing shows
a scope the turn never resolved.

Run:  pytest tests/test_chat_scope.py -q -o pythonpath=.
"""
from __future__ import annotations

from dash.development.base_component import Component

from core.scope import (
    ASKED,
    CUSTOM,
    INHERITED,
    chips_from_dicts,
    chips_from_state,
    chips_to_dicts,
    scope_line,
)
from ui.components.scope_bar import scope_bar


def state(**context) -> dict:
    return {"routing_context": context}


def by_key(chips) -> dict:
    return {chip.key: chip for chip in chips}


# ── derivation ───────────────────────────────────────────────────────────────


def test_the_resolved_filters_become_the_pills():
    chips = chips_from_state(
        state(
            resolved_filters={
                "Country": ["Canada"],
                "Product_Line": ["Property"],
                "Carrier_Group": ["ZURICH GROUP"],
            },
            timeframe_hint="2026 YTD",
        )
    )
    values = {chip.key: chip.value for chip in chips}
    assert values == {
        "country": "Canada",
        "product": "Property",
        "period": "2026 YTD",
        "carrier": "ZURICH GROUP",
    }


def test_pills_keep_the_roadmaps_order():
    chips = chips_from_state(
        state(resolved_filters={"Carrier_Group": ["Zurich"], "Country": ["Canada"],
                                "Product_Line": ["Property"], "Survey_Year": ["2026"]})
    )
    assert [chip.key for chip in chips] == ["country", "product", "period", "carrier"]


def test_a_stored_value_beats_the_users_wording():
    """"Zurich" and "ZURICH GROUP" are one filter; the canonical value is shown."""
    chips = chips_from_state(
        state(
            resolved_filters={"Carrier_Group": ["ZURICH GROUP"]},
            entities={"carriers": ["Zurich"]},
        )
    )
    assert by_key(chips)["carrier"].value == "ZURICH GROUP"


def test_a_mention_fills_a_chip_no_filter_resolved():
    chips = chips_from_state(state(entities={"products": ["cyber"]}))
    assert by_key(chips)["product"].value == "cyber"


def test_an_inherited_filter_says_it_was_carried_over():
    chips = chips_from_state(state(inherited_carrier="Chubb", inherited_country="United Kingdom"))
    assert by_key(chips)["carrier"].source == INHERITED
    assert by_key(chips)["country"].source == INHERITED


def test_a_filter_asked_for_this_turn_says_so():
    chips = chips_from_state(state(resolved_filters={"Country": ["Canada"]}))
    assert by_key(chips)["country"].source == ASKED


def test_several_values_collapse_to_a_countable_summary():
    chips = chips_from_state(
        state(resolved_filters={"Product_Line": ["Property", "Cyber", "Casualty", "Marine"]})
    )
    assert by_key(chips)["product"].value == "Property, Cyber +2 more"


def test_a_turn_that_resolved_nothing_shows_no_scope():
    assert chips_from_state({}) == []
    assert chips_from_state(state()) == []


def test_a_long_machine_timeframe_is_not_shown_as_a_period():
    """`MAX(Survey_Year) - 1` is SQL, not something a board reads."""
    chips = chips_from_state(state(timeframe_hint="MAX(Survey_Year) - 1"))
    assert "period" not in by_key(chips)


# ── peers ────────────────────────────────────────────────────────────────────


def test_a_pinned_peer_set_becomes_its_own_chip():
    chips = chips_from_state(
        state(resolved_filters={"Country": ["Canada"]}),
        {"carrier": "Zurich", "peers": ["A", "B", "C"], "flow": "gpr"},
    )
    peers = by_key(chips)["peers"]
    assert peers.value == "Custom peers (3)"
    assert peers.source == CUSTOM


def test_an_incomplete_peer_set_is_not_claimed_as_scope():
    assert "peers" not in by_key(chips_from_state(state(), {"peers": ["A"]}))
    assert "peers" not in by_key(chips_from_state(state(), {"carrier": "Zurich", "peers": []}))


# ── round trip + the exported line ───────────────────────────────────────────


def test_chips_survive_the_trip_through_a_store():
    chips = chips_from_state(state(resolved_filters={"Country": ["Canada"]}))
    assert chips_from_dicts(chips_to_dicts(chips)) == chips


def test_the_slide_line_states_the_same_scope_as_the_pills():
    chips = chips_from_state(
        state(resolved_filters={"Country": ["Canada"], "Product_Line": ["Property"]},
              timeframe_hint="2026 YTD")
    )
    assert scope_line(chips) == "Country: Canada | Product: Property | Period: 2026 YTD"


# ── rendering ────────────────────────────────────────────────────────────────


def test_the_bar_renders_one_pill_per_chip():
    bar = scope_bar(chips_to_dicts(chips_from_state(
        state(resolved_filters={"Country": ["Canada"], "Product_Line": ["Property"]})
    )))
    pills = [
        n
        for n in _walk(bar)
        if (getattr(n, "className", "") or "").split(" ")[0] == "scope-pill"
    ]
    assert len(pills) == 2


def test_the_bar_disappears_when_there_is_no_scope():
    assert scope_bar([]) is None
    assert scope_bar(None) is None


def test_the_bar_can_show_an_empty_state_when_asked():
    bar = scope_bar([], show_empty=True)
    assert isinstance(bar, Component)


def test_a_pill_says_where_its_value_came_from():
    bar = scope_bar(chips_to_dicts(chips_from_state(state(inherited_country="Canada"))))
    titles = [getattr(n, "title", "") or "" for n in _walk(bar)]
    assert any(INHERITED in t for t in titles)


def _walk(node):
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk(item)
