"""Setup-form regressions: the controls, the peer set, and the deck-sections panel.

All deterministic — they run against the seed DB (no DB_PATH, no LLM). The last
test walks the real business flow the form drives:

    Setup selection → structured load → evidence → binding map → filled template
    → assembled .pptx

so a change to the form is proved end to end, not just at the widget level.
"""
from __future__ import annotations

import json

import pytest

from studio.authoring.setup import carriers_in_scope
from studio.page.authoring.setup import (
    peer_set_body,
    scope_axes,
    setup_body,
    template_sections_panel,
)


def _rendered(component) -> str:
    """A Dash component tree flattened to JSON so tests can assert on its content."""
    return json.dumps(component, default=lambda o: getattr(o, "__dict__", str(o)))


@pytest.fixture(scope="module")
def seeded_survey():
    """The seed DB, which carries the survey book the panel reads."""
    from studio import seed as S

    S.ensure_seed_db()
    return True


def _form() -> str:
    return _rendered(setup_body([], filter_options={}, filter_values={}))


# ── report type: Full QBR is the only deliverable, so there is no chooser ─────


def test_setup_form_has_no_report_type_control():
    form = _form()
    assert "studio-report-type" not in form
    assert "Full QBR" not in form


def test_generate_pins_the_report_to_qbr():
    """The control is gone, so the callback must supply the value itself."""
    import inspect

    from studio.authoring import setup as S

    src = inspect.getsource(S.register_setup)
    assert '"report": "qbr"' in src
    assert 'State("studio-report-type"' not in src


# ── AI assist is on by default ───────────────────────────────────────────────


# ── data basis: premium only, or premium + survey ────────────────────────────


def test_the_form_offers_premium_only_or_premium_plus_survey():
    form = _form()
    assert "studio-data-basis" in form
    assert "Premium only" in form and "Premium + survey" in form
    # It sits with DATA SOURCE — both answer "what is this deck built from?".
    assert "studio-data-source" in form


def test_data_basis_defaults_to_premium_only():
    """Today's deck is premium-only, so the default must not imply otherwise."""
    from studio.page.authoring.setup import DATA_BASIS_DEFAULT, _data_basis_control

    radio = _data_basis_control().children[0].children[1]
    assert radio.id == "studio-data-basis"
    assert radio.value == DATA_BASIS_DEFAULT == "premium"
    assert [o["value"] for o in radio.options] == ["premium", "premium_survey"]


def test_the_choice_reaches_the_selection_generate_builds_from():
    """A deck must record what it was asked for, and every cached build has to re-key
    when the answer changes."""
    import inspect

    from studio.authoring import setup as S

    src = inspect.getsource(S.register_setup)
    assert 'State("studio-data-basis", "value")' in src
    assert '"data_basis": data_basis or A.DATA_BASIS_DEFAULT' in src
    # …and so do the survey identities chosen beside it.
    assert 'State("studio-survey-carrier", "value")' in src
    assert '"survey_carrier": survey_carrier or None' in src
    assert '"survey_peers":' in src


# ── the survey selections ────────────────────────────────────────────────────
#
# The survey book keeps its own carrier vocabulary. The deck resolves the premium subject
# into it, but the author is the one who can see both lists — so the match is SHOWN, and
# can be overridden, before a page of someone else's scores is built.


def test_the_survey_panel_is_in_the_form_but_hidden_by_default():
    form = _form()
    assert "studio-survey-carrier" in form and "studio-survey-peers" in form
    assert "studio-survey-section" in form


def test_the_panel_is_hidden_on_the_premium_basis():
    from studio.authoring.setup import survey_panel_state

    style, options, value, _note = survey_panel_state({"carrier": "Zurich"}, "premium", None, None)
    assert style == {"display": "none"}
    assert options == [] and value is None


def test_the_panel_offers_the_survey_book_s_own_carrier_names(seeded_survey):
    from studio.authoring.setup import survey_panel_state

    style, options, value, _note = survey_panel_state(
        {"carrier": "Zurich", "country": "Singapore"}, "premium_survey", None, None)
    assert style == {}
    names = [o["value"] for o in options]
    assert "Zurich" in names and len(names) > 1
    assert value == "Zurich"                       # the match it would make on its own


def test_the_panel_shows_how_the_carrier_was_matched(seeded_survey):
    from studio.authoring.setup import survey_panel_state

    _s, _o, _v, note = survey_panel_state(
        {"carrier": "Zurich", "country": "Singapore"}, "premium_survey", None, None)
    assert "Surveyed as Zurich" in _rendered(note)


def test_the_panel_warns_when_the_carrier_is_not_surveyed(seeded_survey):
    """The page will be skipped — better said on the form than discovered in the deck."""
    from studio.authoring.setup import survey_panel_state

    _s, _o, value, note = survey_panel_state(
        {"carrier": "Nobody At All", "country": "Singapore"}, "premium_survey", None, None)
    assert value is None
    assert "could not be matched" in _rendered(note)


def test_a_pinned_carrier_is_kept_over_the_match(seeded_survey):
    from studio.authoring.setup import survey_panel_state

    _s, _o, value, _n = survey_panel_state(
        {"carrier": "Zurich", "country": "Singapore"}, "premium_survey", "Chubb", None)
    assert value == "Chubb"


def test_an_uploaded_dataset_has_no_survey_book(seeded_survey):
    from studio.authoring.setup import survey_panel_state

    class _Record:
        dataset_id = "x"

    style, options, value, note = survey_panel_state(
        {"carrier": "Zurich"}, "premium_survey", None, _Record())
    assert style == {} and options == [] and value is None
    assert "governed data" in _rendered(note)


# ── the survey peer group ────────────────────────────────────────────────────
#
# The premium panel has always shown the peer group the deck WOULD use before it is built.
# The survey panel started empty, so the survey page's peer set was invisible until the
# deck existed — and it is keyed differently (``Carrier``, not ``Carrier_Group``), so it is
# not the group shown above it either.


def _peer_state(selected, basis="premium_survey", carrier="Zurich", chosen=None, record=None):
    from studio.authoring.setup import survey_peer_state

    return survey_peer_state(selected, basis, carrier, chosen, record)


def test_the_peer_panel_is_prefilled_from_the_peers_table(seeded_survey):
    from studio.data import peer_members

    options, value, note = _peer_state({"carrier": "Zurich", "country": "Singapore"})
    assert value, "the survey peer group must be shown before the deck is built"
    # Keyed on Carrier and scoped to the country — the survey flow's own peer columns.
    assert set(value) == set(peer_members("survey", "Zurich", country=("Singapore",)))
    assert "Peers table" in _rendered(note)
    assert "Zurich" not in [o["value"] for o in options], "a carrier is not its own peer"


def test_the_peer_panel_follows_the_survey_carrier_not_the_premium_one(seeded_survey):
    """Two carriers keep two different peer groups; the panel must track the survey one."""
    zurich = _peer_state({"country": "Singapore"}, carrier="Zurich")[1]
    aig = _peer_state({"country": "Singapore"}, carrier="AIG")[1]
    assert zurich and aig and set(zurich) != set(aig)
    assert "AIG" not in aig and "Zurich" not in zurich


def test_an_edited_peer_selection_survives_a_filter_change(seeded_survey):
    options, value, note = _peer_state({"carrier": "Zurich", "country": "Singapore"},
                                       chosen=["Chubb"])
    assert value == ["Chubb"]
    assert "your selection" in _rendered(note)


def test_a_stale_peer_selection_is_replaced_by_the_peers_table(seeded_survey):
    """A name this scope does not survey is not a selection worth keeping."""
    _o, value, _n = _peer_state({"carrier": "Zurich", "country": "Singapore"},
                                chosen=["Someone Not Surveyed"])
    assert value and "Someone Not Surveyed" not in value


def test_the_peer_panel_is_silent_off_the_survey_basis(seeded_survey):
    options, value, note = _peer_state({"carrier": "Zurich"}, basis="premium")
    assert options == [] and value == []
    assert "Peers table" not in _rendered(note)


def test_the_peer_panel_waits_for_a_survey_carrier(seeded_survey):
    options, value, _n = _peer_state({"country": "Singapore"}, carrier=None)
    assert options == [] and value == []


def test_the_peer_panel_says_so_when_the_peers_table_has_no_row(seeded_survey):
    """Silence would read as "no peers needed"; the page would then rank against the whole
    surveyed field, which is a different statement and worth saying out loud."""
    _o, value, note = _peer_state({"country": "Singapore"}, carrier="Nobody At All")
    assert value == []
    assert "No survey peer group" in _rendered(note)


def test_ai_assist_defaults_to_on():
    from studio.page.authoring.setup import _ai_control

    checkbox = _ai_control().children[0]
    assert checkbox.id == "studio-ai-toggle"
    assert checkbox.value is True


# ── peers: existing = names from the Peers table, custom = a scoped dropdown ──


def test_custom_peer_options_are_scoped_and_exclude_the_subject():
    scoped = carriers_in_scope({"carrier": "Zurich", "country": ["Singapore"]}, None)
    names = [o["value"] for o in scoped]
    assert names, "Singapore must offer peer candidates"
    assert "Zurich" not in names           # a carrier is never its own peer
    assert "AXA XL" in names


def test_peer_candidates_ignore_the_year_but_follow_the_scope():
    """Year must not drop a peer for a quiet year; other filters must narrow."""
    base = {"carrier": "Zurich", "country": ["Singapore"]}
    assert carriers_in_scope(base, None) == carriers_in_scope({**base, "year": 2025}, None)

    everywhere = {o["value"] for o in carriers_in_scope({"carrier": "Zurich"}, None)}
    in_country = {o["value"] for o in carriers_in_scope(base, None)}
    assert in_country <= everywhere


def test_existing_peers_come_from_the_peers_table_not_the_carrier_list():
    from studio.data import peer_members

    members = peer_members("gpr", "Zurich", country=["Singapore"])
    assert set(members) == {"AIG", "AXA XL", "Allianz", "Chubb"}  # the seed peer group
    everyone = {o["value"] for o in carriers_in_scope({"carrier": "Zurich"}, None)}
    assert set(members) < everyone  # a strict subset — never the whole list


# ── existing peers are scoped to the selected country ────────────────────────


def _peers_db(tmp_path, rows, *, with_country: bool = True):
    """A tiny GPR + Peers database, shaped like the live one."""
    from sqlalchemy import create_engine, text

    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{tmp_path / 'peers.db'}")
    columns = "Carrier_Group TEXT, Country TEXT, Overall_Peer_Group TEXT" if with_country \
        else "Carrier_Group TEXT, Overall_Peer_Group TEXT"
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE Peers ({columns})"))
        for carrier, country, peer in rows:
            if with_country:
                conn.execute(
                    text("INSERT INTO Peers VALUES (:c, :co, :p)"),
                    {"c": carrier, "co": country, "p": peer},
                )
            else:
                conn.execute(
                    text("INSERT INTO Peers (Carrier_Group, Overall_Peer_Group) VALUES (:c, :p)"),
                    {"c": carrier, "p": peer},
                )
    return engine


_PEER_ROWS = [
    ("Zurich", "Singapore", "AIG"),
    ("Zurich", "Singapore", "Chubb"),
    ("Zurich", "Japan", "Tokio Marine"),
    ("Zurich", "Japan", "Sompo"),
]


def test_existing_peers_are_scoped_to_the_selected_country(tmp_path, monkeypatch):
    """The Peers table carries a Country column, so a peer group is per-market —
    Setup must list Japan's peers when Japan is selected, not Singapore's."""
    from studio import data as D

    engine = _peers_db(tmp_path, _PEER_ROWS)
    monkeypatch.setattr(D, "get_engine", lambda: engine)

    assert D.peer_members("gpr", "Zurich", country=["Singapore"]) == ["AIG", "Chubb"]
    assert D.peer_members("gpr", "Zurich", country=["Japan"]) == ["Sompo", "Tokio Marine"]


def test_multiple_countries_union_the_peer_groups(tmp_path, monkeypatch):
    from studio import data as D

    engine = _peers_db(tmp_path, _PEER_ROWS)
    monkeypatch.setattr(D, "get_engine", lambda: engine)

    members = D.peer_members("gpr", "Zurich", country=["Singapore", "Japan"])
    assert members == ["AIG", "Chubb", "Sompo", "Tokio Marine"]


def test_no_country_selected_returns_every_market_s_peers(tmp_path, monkeypatch):
    from studio import data as D

    engine = _peers_db(tmp_path, _PEER_ROWS)
    monkeypatch.setattr(D, "get_engine", lambda: engine)

    assert D.peer_members("gpr", "Zurich") == ["AIG", "Chubb", "Sompo", "Tokio Marine"]
    assert D.peer_members("gpr", "Zurich", country=["All"]) == ["AIG", "Chubb", "Sompo", "Tokio Marine"]


def test_peers_table_without_a_country_column_still_resolves(tmp_path, monkeypatch):
    """The registry declares the column; a database that predates it must fall
    back to the unscoped group rather than silently finding nobody."""
    from studio import data as D

    engine = _peers_db(tmp_path, [("Zurich", None, "AIG"), ("Zurich", None, "Chubb")], with_country=False)
    monkeypatch.setattr(D, "get_engine", lambda: engine)

    assert D.peer_members("gpr", "Zurich", country=["Japan"]) == ["AIG", "Chubb"]


def test_peer_country_column_is_ignored_when_the_table_lacks_it(tmp_path):
    from core.analytics.sql import flow_spec, peer_country_column

    spec = flow_spec("gpr")
    assert spec.peer_columns["country"] == "Country"     # declared in flows.yaml
    with_col = _peers_db(tmp_path / "a", _PEER_ROWS)
    without = _peers_db(tmp_path / "b", [("Zurich", None, "AIG")], with_country=False)
    assert peer_country_column(spec, with_col) == "Country"
    assert peer_country_column(spec, without) is None


def test_peer_set_body_shows_names_only():
    body = _rendered(peer_set_body(["AIG", "Chubb"], "2 peers from the Peers table."))
    assert "AIG" in body and "Chubb" in body
    assert "qs-peer-chip" in body
    assert "Dropdown" not in body  # existing peers are read-only


def test_existing_mode_hides_the_custom_peer_dropdown_on_first_paint():
    from studio.page.authoring.setup import _peers_panel

    wrap = next(c for c in _peers_panel().children if getattr(c, "id", "") == "studio-peer-custom-wrap")
    assert wrap.style == {"display": "none"}


# ── deck sections track the assembly scope ───────────────────────────────────


def test_scope_axes_maps_all_to_every_registered_axis():
    assert scope_axes("all") == ("overall", "product", "country")
    assert scope_axes("product") == ("product",)
    assert scope_axes(None) == ("overall", "product", "country")


def test_deck_sections_round_trip_between_all_and_a_single_axis():
    """Regression: switching Scope to Product and back to All used to leave the
    panel showing the overall template alone, so 'All' looked like a dead click."""
    every = _rendered(template_sections_panel("all"))
    product = _rendered(template_sections_panel("product"))

    assert every != product
    assert _rendered(template_sections_panel("all")) == every  # returning restores it

    for axis in ("OVERALL", "PRODUCT", "COUNTRY"):
        assert axis.title() in every
    assert "Overall" not in product and "Country" not in product


def test_deck_sections_page_count_is_the_sum_of_the_axes_it_assembles():
    def pages(scope: str) -> int:
        panel = template_sections_panel(scope)
        summary = panel.children[0].children[0]  # "<b>N</b> base pages"
        return int(summary.children[0].children)

    assert pages("all") == pages("overall") + pages("product") + pages("country")


def test_country_scoped_peer_group_reaches_the_deck_benchmark(tmp_path):
    """End to end over a real seed-shaped database: the peer benchmark the deck
    computes must use the SAME per-country group Setup lists, not a global one."""
    from sqlalchemy import create_engine

    from studio import data as D
    from studio.compute import _resolve_filters, peer_gap
    from studio.seed import build_seed

    seed = build_seed(tmp_path / "seed.db")
    engine = create_engine(f"sqlite:///{seed}")

    def gap(country):
        return peer_gap("gpr", _resolve_filters({"carrier": "Zurich", "country": [country],
                                                 "year": 2025}), engine)

    singapore, japan = gap("Singapore"), gap("Japan")
    assert singapore["n_peers"] == 4 and japan["n_peers"] == 4
    # Different peer sets in the two markets → different benchmarks.
    assert singapore["peer_avg"] != japan["peer_avg"]

    # And the names Setup shows match the group the benchmark resolved.
    original = D.get_engine
    try:
        D.get_engine = lambda: engine
        assert D.peer_members("gpr", "Zurich", country=["Japan"]) == [
            "AIG", "MS&AD", "Sompo", "Tokio Marine",
        ]
        assert D.peer_members("gpr", "Zurich", country=["Singapore"]) == [
            "AIG", "AXA XL", "Allianz", "Chubb",
        ]
    finally:
        D.get_engine = original
    engine.dispose()


# ── end to end: the form's selection still produces a real deck ──────────────


def test_setup_selection_builds_the_assembled_deck(tmp_path):
    """selection → data load → evidence → template binding → merged .pptx."""
    from pptx import Presentation

    from studio.authoring.generate import _assembled_export, _generated_deck

    selection = {
        "report": "qbr",                       # pinned by generate, no longer a control
        "filters": {"carrier": "Zurich", "country": ["Singapore"], "year": 2025},
        "breakdowns": ["Product_Line", "SIC_Major_Class"],
        "cuts": [],
        "peers": None,                          # existing peers → the Peers table
        "audience": "executive",
        "meeting_length": "standard",
        "style": "balanced",
        "ai": False,                            # deterministic path for the test
        "template_scope": "overall",
        "template_path": "template/overall_template.pptx",
        "dataset_id": None,
    }

    deck = _generated_deck(selection)
    assert deck and deck.slides

    path = _assembled_export(selection)
    assert path, "the overall sub-deck must assemble"
    assert len(Presentation(path).slides) > 0


def test_pinned_custom_peers_reach_the_deck():
    """Custom mode writes carriers into the selection; the benchmark must use them."""
    from studio.compute import _resolve_filters, peer_gap
    from studio.data import get_engine

    filters = _resolve_filters({"carrier": "Zurich", "country": ["Singapore"], "year": 2025})
    pinned = peer_gap("gpr", filters, get_engine(), peers=["QBE", "Sompo"])
    assert pinned and pinned["n_peers"] == 2

    from_table = peer_gap("gpr", filters, get_engine())
    assert from_table["n_peers"] == 4
    assert pinned["peer_avg"] != from_table["peer_avg"]


# ── the busy overlay: every filter/selection change is acknowledged ───────────


def test_the_form_carries_the_busy_overlay_and_one_flag_per_callback():
    from studio.page.authoring import setup as P

    form = _form()
    for flag in (P.BUSY_FORM, P.BUSY_PREVIEW, P.BUSY_SECTIONS):
        assert flag in form, f"{flag} must exist for its callback's running= to target it"
    assert "qs-page-loader" in form and "qs-page-spinner" in form


def test_every_setup_callback_raises_a_flag_while_it_works():
    """A change answered by several callbacks must stay covered until the LAST finishes,
    so each one owns its own flag rather than sharing one that races."""
    import inspect

    from studio.authoring import export as E
    from studio.authoring import setup as S

    src = inspect.getsource(S.register_setup) + inspect.getsource(E.register_export)
    assert src.count("running=") >= 3, "the option cascade, scope preview and deck sections"
    for flag in ("BUSY_FORM", "BUSY_PREVIEW", "BUSY_SECTIONS"):
        assert flag in src, f"no callback raises {flag}"


def test_a_busy_flag_is_raised_for_the_call_and_dropped_after():
    from dash import Output

    from studio.authoring.setup import _busy
    from studio.page.authoring import setup as P

    [(target, during, after)] = _busy(P.BUSY_FORM)
    assert target == Output(P.BUSY_FORM, "className")
    assert "is-busy" in during and "is-busy" not in after
    assert after == P.BUSY_FLAG_CLASS      # back to the resting class, not blank


def test_the_overlay_never_swallows_a_click():
    """It is a progress cue, not a modal: a change made while it is up must still land."""
    from pathlib import Path

    css = Path("assets/studio_authoring.css").read_text(encoding="utf-8")
    block = css.split(".qs-page-loader {", 1)[1].split("}", 1)[0]
    assert "pointer-events: none" in block


def test_the_overlay_is_shown_by_display_not_by_a_fade():
    """Reduced motion and background tabs suppress transitions; the overlay must still
    appear the moment work starts."""
    from pathlib import Path

    css = Path("assets/studio_authoring.css").read_text(encoding="utf-8")
    assert ".qs-page-loader.is-on {" in css
    on_block = css.split(".qs-page-loader.is-on {", 1)[1].split("}", 1)[0]
    assert "display: flex" in on_block
