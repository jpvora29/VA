"""Per-market peer modes on the Setup page (user request, 2026-11-11).

With Custom peers chosen and several countries in scope, each market has its own
Existing | Custom switch: an author can re-pick peers for two of four countries and keep
the Peers-table group for the rest. These tests pin the pure pieces end to end — what the
form renders, what the summary strip says, and what Generate sends downstream.
"""
from __future__ import annotations

from studio.authoring import setup as S
from studio.page import authoring as A

IDS = [{"type": "studio-peer-custom", "country": c} for c in ("SG", "JP", "HK", "AU")]
MODE_IDS = [{"type": "studio-peer-market-mode", "country": c} for c in ("SG", "JP", "HK", "AU")]
FIVE = ["A", "B", "C", "D", "E"]


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    for child in children if isinstance(children, (list, tuple)) else [children]:
        if child is not None and not isinstance(child, str):
            yield from _walk(child)


def test_existing_mode_everywhere_ignores_market_switches():
    rows = S.peer_mode_rows("existing", ["SG", "JP"], {"SG": "custom"})
    assert rows == [("SG", "existing"), ("JP", "existing")]


def test_custom_mode_honours_each_market_switch():
    modes = S.market_modes(MODE_IDS, ["custom", "existing", "custom", "existing"])
    rows = S.peer_mode_rows("custom", ["SG", "JP", "HK", "AU"], modes)
    assert rows == [("SG", "custom"), ("JP", "existing"), ("HK", "custom"), ("AU", "existing")]


def test_generate_pins_only_custom_markets_and_checks_only_them():
    modes = S.market_modes(MODE_IDS, ["custom", "existing", "custom", "existing"])
    # JP and AU are Existing: their (thin) picker answers must neither pin nor block.
    vals = [FIVE, ["X"], FIVE, []]
    by_country, custom = S.custom_market_pins("custom", IDS, vals, modes)
    assert custom == ["SG", "HK"]
    assert by_country == {"SG": FIVE, "HK": FIVE}
    assert S.short_markets(by_country, countries=custom) == []


def test_a_short_custom_market_still_blocks_generate():
    modes = S.market_modes(MODE_IDS, ["custom", "existing", "custom", "existing"])
    by_country, custom = S.custom_market_pins("custom", IDS, [FIVE, [], ["A"], []], modes)
    assert S.short_markets(by_country, countries=custom) == ["HK"]


def test_all_markets_existing_sends_no_pins():
    modes = S.market_modes(MODE_IDS, ["existing"] * 4)
    by_country, custom = S.custom_market_pins("custom", IDS, [FIVE] * 4, modes)
    assert (by_country, custom) == ({}, [])
    assert S.overall_peers(by_country, {"carrier": "Focal"}, ["SG", "JP"], None) == []


def test_overall_benchmark_adds_existing_markets_groups(monkeypatch):
    monkeypatch.setattr(S, "peer_groups",
                        lambda flow, carrier, selected, record: [("SG", ["Q"]), ("JP", ["P", "Q"])])
    peers = S.overall_peers({"SG": ["A", "B"]}, {"carrier": "Focal"}, ["SG", "JP"], None)
    assert peers == ["A", "B", "P", "Q"]


def test_picker_renders_a_switch_per_market_with_the_right_area_shown():
    groups = [("SG", [{"label": "A", "value": "A"}], ["A"]), ("JP", [], [])]
    tree = A.custom_peer_picker(groups, existing={"SG": ["Q"], "JP": ["P"]},
                                modes={"JP": "existing"})
    by_id = {(n.id["type"], n.id["country"]): n for n in _walk(tree)
             if isinstance(getattr(n, "id", None), dict)}
    assert by_id[("studio-peer-market-mode", "SG")].value == "custom"
    assert by_id[("studio-peer-market-mode", "JP")].value == "existing"
    assert by_id[("studio-peer-market-custom", "JP")].style == {"display": "none"}
    assert by_id[("studio-peer-market-existing", "JP")].style == {}
    assert "is-existing" in by_id[("studio-peer-market", "JP")].className


def test_single_market_or_no_governed_group_has_no_switch():
    one = A.custom_peer_picker([("SG", [], [])], existing={"SG": ["Q"]})
    flat = A.custom_peer_picker([("SG", [], []), ("JP", [], [])])
    for tree in (one, flat):
        assert not any(isinstance(getattr(n, "id", None), dict)
                       and n.id.get("type") == "studio-peer-market-mode" for n in _walk(tree))


def test_summary_strip_names_each_market_and_counts_custom():
    strip = A.peer_mode_summary([("SG", "custom"), ("JP", "existing"),
                                 ("HK", "custom"), ("AU", "existing")])
    texts = [n for n in _walk(strip) if isinstance(n, str)] + [
        n.children for n in _walk(strip) if isinstance(getattr(n, "children", None), str)]
    assert "2 of 4 markets custom" in texts
    assert texts.count("Custom") == 2 and texts.count("Existing") == 2
    assert A.peer_mode_summary([]) is None
