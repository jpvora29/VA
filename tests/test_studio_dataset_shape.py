"""Column tools: create a column from another, delete any column, and stay consistent.

The case that drove this: a spreadsheet carries a billing DATE and no Year column, so
nothing can map to Year and every period comparison in the deck goes quiet. Reading a
Year out of the date is the whole fix — and once it exists it must behave like any
other column: profiled, proposed, mappable.

Three layers:
  * unit — the recipes and the mapping reconciliation, on plain frames;
  * integration — add/derive/delete/undo through a real on-disk repository, proving the
    profile, the mappings and the working frame never drift apart;
  * end to end — date-only upload → derive Year → map → submit → the real deck plan
    fills from the uploaded data.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from studio.authoring.data import add_column, delete_column, seed_mappings, submit_mappings, use_for_deck, undo_shape
from studio.dataset import shape as S
from studio.dataset.ingest import profile_frame
from studio.dataset.model import ColumnMapping, TransformOp
from studio.dataset.repository import DatasetRepository
from studio.dataset.transform import apply_transforms, derive_column


def _dated_book() -> pd.DataFrame:
    """A book with a billing date and NO year column — the shape that broke."""
    rows = []
    for year in (2024, 2025):
        for month in (2, 8):
            for carrier in ("Zurich", "AIG", "Chubb"):
                for line in ("Cyber", "Marine"):
                    rows.append({
                        "Insurer": carrier, "Market": "Singapore", "LOB": line,
                        "Billing Date": f"{year}-{month:02d}-15",
                        "Written Premium": 1000 * (year - 2000) * (1 if line == "Cyber" else 2),
                    })
    return pd.DataFrame(rows)


# ── the recipes (pure) ───────────────────────────────────────────────────────


def test_a_year_is_read_out_of_a_date():
    frame = pd.DataFrame({"When": ["2024-03-01", "2025-11-30"]})
    assert list(derive_column(frame, "When", "year")) == [2024, 2025]


def test_the_calendar_recipes_read_what_they_say():
    frame = pd.DataFrame({"When": ["2025-02-14"]})
    assert derive_column(frame, "When", "quarter")[0] == "2025-Q1"
    assert derive_column(frame, "When", "month")[0] == "2025-02"
    assert derive_column(frame, "When", "month_name")[0] == "February"
    assert derive_column(frame, "When", "date")[0] == "2025-02-14"


def test_the_text_recipes_tidy_a_label():
    frame = pd.DataFrame({"Name": ["  zurich  "]})
    assert derive_column(frame, "Name", "upper")[0] == "ZURICH"
    assert derive_column(frame, "Name", "trim")[0] == "zurich"


def test_a_column_that_is_not_dates_says_so():
    frame = pd.DataFrame({"Name": ["alpha", "beta"]})
    with pytest.raises(ValueError, match="does not read as dates"):
        derive_column(frame, "Name", "year")


def test_an_unknown_column_or_recipe_says_so():
    frame = pd.DataFrame({"When": ["2025-01-01"]})
    with pytest.raises(ValueError, match="no column called"):
        derive_column(frame, "Missing", "year")
    with pytest.raises(ValueError, match="Unknown recipe"):
        derive_column(frame, "When", "astrology")


def test_the_recipe_is_replayable_in_order():
    frame = pd.DataFrame({"When": ["2025-01-01"], "Premium": [10.0]})
    out = apply_transforms(frame, [
        TransformOp(kind="derive", name="Year", source="When", recipe="year"),
        TransformOp(kind="add", name="Double", formula="Premium * 2"),
        TransformOp(kind="drop", name="When"),
    ])
    assert list(out.columns) == ["Premium", "Year", "Double"]
    assert out["Year"][0] == 2025 and out["Double"][0] == 20.0


# ── mapping reconciliation (pure) ────────────────────────────────────────────


def test_reconciliation_keeps_decisions_drops_the_departed_proposes_the_new():
    frame = pd.DataFrame({"Insurer": ["Z"], "Premium": [1.0], "Year": [2025]})
    existing = (
        ColumnMapping(uploaded="Insurer", target="Carrier_Group", source="user"),
        ColumnMapping(uploaded="Gone", target="Country", source="user"),
    )
    out = S.reconcile_mappings(profile_frame(frame), existing)
    by_col = {m.uploaded: m for m in out}
    assert set(by_col) == {"Insurer", "Premium", "Year"}          # "Gone" left with its column
    assert by_col["Insurer"].source == "user"                     # the user's decision stands
    assert by_col["Year"].target == "Year"                        # the new column got a proposal


def test_a_proposal_cannot_claim_a_target_the_user_already_holds():
    frame = pd.DataFrame({"Insurer": ["Z"], "Carrier": ["Z"]})
    existing = (ColumnMapping(uploaded="Insurer", target="Carrier_Group", source="user"),)
    by_col = {m.uploaded: m for m in S.reconcile_mappings(profile_frame(frame), existing)}
    assert by_col["Carrier"].target == ""


# ── integration: the repository stays consistent ─────────────────────────────


@pytest.fixture()
def dataset(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = seed_mappings(repo, repo.save(_dated_book(), name="book", filename="b.csv"))
    return repo, record


def test_deriving_a_year_makes_it_mappable(dataset):
    """The fix, in one test: no Year column → derive one → it proposes onto Year."""
    repo, record = dataset
    assert "Year" not in {m.target for m in record.mappings}

    assert add_column(repo, record.dataset_id, "", "Billing Date", "year", "") is None

    after = repo.get(record.dataset_id)
    assert "Year" in {c.name for c in after.profile.columns}      # profiled like any column
    by_col = {m.uploaded: m for m in after.mappings}
    assert by_col["Year"].target == "Year"                        # and proposed onto Year
    assert after.profile.n_cols == record.profile.n_cols + 1


def test_a_derived_column_defaults_to_the_name_of_its_reading(dataset):
    repo, record = dataset
    add_column(repo, record.dataset_id, "", "Billing Date", "quarter", "")
    assert "Quarter" in {c.name for c in repo.get(record.dataset_id).profile.columns}


def test_a_named_derived_column_keeps_the_name(dataset):
    repo, record = dataset
    add_column(repo, record.dataset_id, "Policy Year", "Billing Date", "year", "")
    assert "Policy Year" in {c.name for c in repo.get(record.dataset_id).profile.columns}


def test_a_bad_recipe_changes_nothing(dataset):
    repo, record = dataset
    error = add_column(repo, record.dataset_id, "Nope", "Insurer", "year", "")
    assert error and "dates" in error
    after = repo.get(record.dataset_id)
    assert after.transforms == () and "Nope" not in {c.name for c in after.profile.columns}


def test_a_duplicate_name_is_refused(dataset):
    repo, record = dataset
    assert "already a column" in add_column(repo, record.dataset_id, "LOB", "", "", "1")


def test_deleting_a_mapped_column_takes_its_mapping_with_it(dataset):
    repo, record = dataset
    assert {m.uploaded: m.target for m in record.mappings}["LOB"] == "Product_Line"

    assert delete_column(repo, record.dataset_id, "LOB") is True

    after = repo.get(record.dataset_id)
    assert "LOB" not in {c.name for c in after.profile.columns}
    assert "LOB" not in {m.uploaded for m in after.mappings}
    assert "Product_Line" not in {m.target for m in after.mappings}


def test_undo_walks_the_recipe_back(dataset):
    repo, record = dataset
    add_column(repo, record.dataset_id, "", "Billing Date", "year", "")
    delete_column(repo, record.dataset_id, "Billing Date")
    assert len(repo.get(record.dataset_id).transforms) == 2

    assert undo_shape(repo, record.dataset_id) is True
    assert "Billing Date" in {c.name for c in repo.get(record.dataset_id).profile.columns}
    assert undo_shape(repo, record.dataset_id) is True
    assert repo.get(record.dataset_id).transforms == ()
    assert undo_shape(repo, record.dataset_id) is False


def test_the_shape_history_reads_like_what_was_done(dataset):
    repo, record = dataset
    add_column(repo, record.dataset_id, "", "Billing Date", "year", "")
    delete_column(repo, record.dataset_id, "Market")
    history = S.shape_history(repo.get(record.dataset_id))
    assert history == ["Year = Year from a date of Billing Date", "Deleted Market"]
    assert S.derived_columns(repo.get(record.dataset_id)) == {"Year"}


def test_resync_is_idempotent(dataset):
    repo, record = dataset
    once = S.resync(repo, record)
    assert S.resync(repo, once) is once or S.resync(repo, once) == once


# ── the page shows the tools ─────────────────────────────────────────────────


def test_the_data_tab_offers_the_column_tools(tmp_path, monkeypatch):
    from studio.dataset import repository as R
    from studio.page.authoring.data import data_body

    monkeypatch.setenv("STUDIO_DATASET_DIR", str(tmp_path))
    R.get_repository.cache_clear()
    try:
        repo = R.get_repository()
        record = seed_mappings(repo, repo.save(_dated_book(), name="book", filename="b.csv"))
        page = json.dumps(data_body({"active": record.dataset_id}),
                          default=lambda o: getattr(o, "__dict__", str(o)))
        for control in ("qs-col-source", "qs-col-recipe", "qs-col-name",
                        "qs-col-formula", "qs-col-add", "qs-col-undo", "qs-col-msg"):
            assert control in page, control
        # Every column is deletable — mapped ones included.
        assert page.count("qs-col-del") == len(record.profile.columns)
        assert "Year from a date" in page
    finally:
        R.get_repository.cache_clear()


# ── end to end: the workflow that used to produce an empty deck ──────────────


def test_a_date_only_upload_builds_a_populated_deck(tmp_path, monkeypatch):
    """upload -> derive Year -> map -> submit -> plan the real sub-decks.

    Every number below came out empty before: the SQL executor raised "no such column"
    for every cut the upload lacked, and there was no way to create the Year column the
    period comparisons need.
    """
    from studio.authoring.generate import _engine_for
    from studio.compute import compute_overall
    from studio.dataset import repository as R
    from studio.dataset.source import dataset_source
    from studio.template_fill.assemble import plan_subdecks

    monkeypatch.setenv("STUDIO_DATASET_DIR", str(tmp_path))
    R.get_repository.cache_clear()
    dataset_source.cache_clear()
    try:
        repo = R.get_repository()
        record = seed_mappings(repo, repo.save(_dated_book(), name="book", filename="b.csv"))
        assert add_column(repo, record.dataset_id, "", "Billing Date", "year", "") is None

        record = repo.get(record.dataset_id)
        columns = [m.uploaded for m in record.mappings]
        targets = [m.target for m in record.mappings]
        targets[columns.index("Market")] = "Country"        # the user names what we could not
        assert submit_mappings(repo, record.dataset_id, columns, targets,
                               ["x"] * len(columns)) is None
        assert use_for_deck(repo, record.dataset_id) is None

        source = _engine_for({"dataset_id": record.dataset_id})
        assert source.__class__.__name__ == "FrameSource"    # the pandas executor drives it

        result = compute_overall(
            filters={"carrier": "Zurich", "country": ["Singapore"], "year": 2025},
            breakdowns=["Product_Line", "SIC_Major_Class"], engine=source,
        )
        assert len(result.kpis) == 3                          # total, rank, share of wallet
        by_column = {b.column: b for b in result.breakdowns}
        assert len(by_column["Product_Line"].rows) == 2        # Cyber + Marine, from the upload
        assert by_column["SIC_Major_Class"].rows == []         # honestly absent, not an error

        decks = plan_subdecks(result)
        overall = decks[0].values
        assert overall["carrier_gwp"] > 0 and overall["marsh_gwp"] > overall["carrier_gwp"]
        assert overall["sow_pct"] > 0 and overall["rank"] >= 1
        assert overall["carrier_gwp_yoy"] is not None          # the derived Year did this
        assert [d.label for d in decks if d.template == "product"] == ["Marine", "Cyber"]
    finally:
        dataset_source.cache_clear()
        R.get_repository.cache_clear()
