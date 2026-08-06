"""Auto-mapping: the proposal a fresh upload opens with, and how the tab shows it.

Three layers:
  * unit — the matchers and the conflict rule, on in-memory profiles, so the proposal
    logic is pinned without a repository or a Dash app;
  * integration — upload → save → seed → reload through a real on-disk repository,
    proving the proposals survive the disk trip and that the user's own submit
    overwrites them;
  * page — the Data tab renders the proposals, keeps every callback id the mapping
    submit depends on, and still lets the user change any target from its select box.

Deterministic: no LLM, no engine — the flow registry's own aliases are the vocabulary.
"""
from __future__ import annotations

import io
import json

import pandas as pd
import pytest

from studio.dataset.automap import (
    Target,
    canonical_targets,
    is_proposed,
    propose_mappings,
)
from studio.dataset.model import ColumnProfile, DatasetProfile
from studio.dataset.repository import DatasetRepository


def _profile(**columns) -> DatasetProfile:
    """A profile from ``name=(kind, sample…)`` pairs — no frame needed."""
    cols = tuple(
        ColumnProfile(name=name, kind=kind, null_pct=0.0,
                      n_distinct=len(sample) or 1, sample=tuple(str(s) for s in sample))
        for name, (kind, *sample) in columns.items()
    )
    return DatasetProfile(n_rows=10, n_cols=len(cols), columns=cols)


def _by_column(profile) -> dict:
    return {m.uploaded: m for m in propose_mappings(profile)}


# ── the matchers ─────────────────────────────────────────────────────────────


def test_an_exact_name_is_certain():
    mapping = _by_column(_profile(Country=("text", "UK")))["Country"]
    assert (mapping.target, mapping.source, mapping.confidence) == ("Country", "alias", 1.0)


def test_a_registry_alias_maps_without_sharing_the_column_name():
    """"Insurer" and "GWP" are what spreadsheets call them; the registry knows both."""
    found = _by_column(_profile(Insurer=("text", "Zurich"), GWP=("number", 10.0)))
    assert found["Insurer"].target == "Carrier_Group"
    assert found["GWP"].target == "Premium"
    assert all(m.source == "alias" for m in found.values())


def test_a_qualified_name_still_carries_the_canonical_word():
    found = _by_column(_profile(**{"Premium Amount": ("number", 1.0),
                                   "Country Name": ("text", "UK")}))
    assert found["Premium Amount"].target == "Premium"
    assert found["Country Name"].target == "Country"
    assert all(m.source == "fuzzy" for m in found.values())


def test_a_year_is_recognised_from_its_values_when_the_name_says_nothing():
    """"Yr" shares almost no characters with "Year"; 2019…2026 can only be one thing."""
    mapping = _by_column(_profile(Yr=("number", 2024, 2025, 2026)))["Yr"]
    assert (mapping.target, mapping.source) == ("Year", "values")


def test_a_money_column_is_not_read_as_a_year():
    """The year matcher must not swallow every numeric column in range."""
    assert _by_column(_profile(Amount=("number", 1_250_000.0, 990.5)))["Amount"].target == ""


def test_a_column_nothing_matches_comes_back_unmapped():
    mapping = _by_column(_profile(Notes=("text", "see file")))["Notes"]
    assert (mapping.target, mapping.source, mapping.confidence) == ("", "unmapped", 0.0)


def test_a_measure_target_refuses_a_text_column():
    """Premium drives every figure in the deck — a text column cannot be it."""
    assert _by_column(_profile(Premium=("text", "n/a")))["Premium"].target == ""


def test_a_near_miss_that_means_something_else_is_left_alone():
    assert _by_column(_profile(**{"Client Reference": ("text", "A-1")}))["Client Reference"].target == ""


# ── the conflict rule ────────────────────────────────────────────────────────


def test_one_target_is_claimed_by_the_most_confident_column_only():
    """With both "Carrier_Group" and "Insurer" present the exact name wins, and the
    alias falls through to nothing rather than the first row winning by position."""
    found = _by_column(_profile(Insurer=("text", "Zurich"), Carrier_Group=("text", "Zurich")))
    assert found["Carrier_Group"].target == "Carrier_Group"
    assert found["Insurer"].target == ""


def test_every_uploaded_column_gets_a_row_in_upload_order():
    profile = _profile(Insurer=("text", "Zurich"), Notes=("text", "x"), GWP=("number", 1.0))
    assert [m.uploaded for m in propose_mappings(profile)] == ["Insurer", "Notes", "GWP"]


def test_proposals_are_deterministic():
    profile = _profile(Insurer=("text", "Zurich"), Yr=("number", 2025), GWP=("number", 1.0))
    assert propose_mappings(profile) == propose_mappings(profile)


def test_an_empty_upload_proposes_nothing():
    assert propose_mappings(DatasetProfile(0, 0)) == ()


def test_the_vocabulary_comes_from_the_flow_registry():
    """The targets track the schema — nothing is maintained as a list in automap."""
    names = {t.name for t in canonical_targets()}
    assert {"Premium", "Carrier_Group", "Year", "Country", "Product_Line"} <= names


def test_a_caller_may_supply_its_own_targets():
    targets = (Target(name="Widgets", role="measure", vocabulary=("widgets", "units")),)
    found = propose_mappings(_profile(Units=("number", 3.0)), targets=targets)
    assert found[0].target == "Widgets"


def test_is_proposed_separates_a_guess_from_a_confirmation():
    proposed = _by_column(_profile(Insurer=("text", "Zurich")))["Insurer"]
    from dataclasses import replace

    assert is_proposed(proposed)
    assert not is_proposed(replace(proposed, source="user"))
    assert not is_proposed(replace(proposed, target=""))


# ── integration: upload → seed → disk → submit ───────────────────────────────


def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Insurer": ["Zurich", "AXA", "Zurich"],
        "GWP": [100.0, 250.5, 75.0],
        "Yr": [2024, 2024, 2025],
        "Notes": ["a", "b", "c"],
    })


def test_seeded_proposals_survive_the_disk_trip(tmp_path):
    from studio.authoring.data import seed_mappings

    repo = DatasetRepository(tmp_path)
    record = seed_mappings(repo, repo.save(_frame(), name="book", filename="book.csv"))

    reloaded = repo.get(record.dataset_id)
    by_col = {m.uploaded: m for m in reloaded.mappings}
    assert by_col["Insurer"].target == "Carrier_Group"
    assert by_col["GWP"].target == "Premium"
    assert by_col["Yr"].target == "Year"
    assert by_col["Notes"].target == ""


def test_proposals_never_promote_a_record_on_their_own(tmp_path):
    """A machine guess is not a confirmation: the required trio may all be proposed and
    the record still waits for the user's submit before it can govern a deck."""
    from studio.authoring.data import seed_mappings

    repo = DatasetRepository(tmp_path)
    record = seed_mappings(repo, repo.save(_frame(), name="book", filename="book.csv"))
    assert record.status == "uploaded"
    assert all(m.target for m in record.mappings if m.uploaded != "Notes")


def test_reopening_a_dataset_does_not_overwrite_the_users_work(tmp_path):
    from dataclasses import replace

    from studio.authoring.data import seed_mappings, submit_mappings

    repo = DatasetRepository(tmp_path)
    record = seed_mappings(repo, repo.save(_frame(), name="book", filename="book.csv"))
    # The user disagrees: GWP is not the money measure here.
    assert submit_mappings(
        repo, record.dataset_id,
        ["Insurer", "GWP", "Yr", "Notes"],
        ["Carrier_Group", "", "Year", ""],
        ["who", "a rate, not premium", "year", "free text"],
    ) is None

    reopened = seed_mappings(repo, repo.get(record.dataset_id))
    by_col = {m.uploaded: m for m in reopened.mappings}
    assert by_col["GWP"].target == "" and by_col["GWP"].source == "user"


def test_upload_reports_how_much_was_mapped_for_you(tmp_path):
    """The whole point is visible progress — the upload message must say so."""
    from studio.authoring.data import seed_mappings, upload_summary
    from studio.dataset.ingest import read_upload

    buf = io.BytesIO()
    _frame().to_csv(buf, index=False)
    frame, truncated = read_upload("book.csv", buf.getvalue())

    repo = DatasetRepository(tmp_path)
    record = seed_mappings(repo, repo.save(frame, name="book", filename="book.csv"))
    message = upload_summary(record, truncated=truncated)
    assert "3 rows × 4 columns" in message
    assert "3 of 4 columns mapped automatically" in message


# ── the page: proposals are shown, and remain the user's to change ───────────


@pytest.fixture()
def seeded_page(tmp_path, monkeypatch):
    from studio.authoring.data import seed_mappings
    from studio.dataset import repository as R
    from studio.page.authoring.data import data_body

    monkeypatch.setenv("STUDIO_DATASET_DIR", str(tmp_path))
    R.get_repository.cache_clear()
    try:
        repo = R.get_repository()
        record = seed_mappings(repo, repo.save(_frame(), name="book", filename="book.csv"))
        body = data_body({"active": record.dataset_id})
        yield json.dumps(body, default=lambda o: getattr(o, "__dict__", str(o)))
    finally:
        R.get_repository.cache_clear()


def test_the_tab_shows_which_rows_were_proposed(seeded_page):
    assert "qs-map-badge auto" in seeded_page
    assert "Auto" in seeded_page


def test_every_column_still_has_its_own_select_box(seeded_page):
    """The proposal is a starting point: each row keeps the target dropdown the
    submit callback reads, so the user can override any of it."""
    for column in ("Insurer", "GWP", "Yr", "Notes"):
        assert f"'col': '{column}'" in seeded_page or f'"col": "{column}"' in seeded_page
    assert seeded_page.count("qs-map-target") == 4


def test_the_tab_states_where_the_user_is_and_what_is_missing(seeded_page):
    assert "qs-pipeline" in seeded_page and "Map columns" in seeded_page
    # The three columns a deck cannot be built without are ticked off on screen.
    assert "qs-req-chip" in seeded_page
    assert "qs-meter-fill" in seeded_page
