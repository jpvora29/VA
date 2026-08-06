"""Stage-2 tests: transforms, pivots, KPI capture, materialization, precedence.

The integration tests prove the agreed workflow end-to-end at the Python level:
upload → HITL map (incl. designated primary measure + custom KPIs) → shape →
pivot → materialize → the SAME analytics primitives that power the deck compute
their facts from the UPLOADED data, not the governed DB.
"""
from __future__ import annotations

import pandas as pd
import pytest

from studio.authoring.data import (
    _primary_from_fields,
    add_column,
    delete_column,
    submit_mappings,
    use_for_deck,
)
from studio.dataset.materialize import materialize, materialized_frame, pivot_frame
from studio.dataset.model import (
    ColumnMapping,
    CustomMeasure,
    PivotSpec,
    TransformOp,
    record_complete,
    record_from_json,
)
from studio.dataset.pivot import build_pivot, slice_frame
from studio.dataset.repository import MAPPED_TABLE, DatasetRepository
from studio.dataset.transform import apply_transforms, safe_eval


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Insurer": ["Zurich", "AXA", "Zurich", "Allianz"],
            "Written": [100.0, 250.0, 75.0, 300.0],
            "Fees": [10.0, 25.0, 5.0, 30.0],
            "Commission": [12.0, 30.0, 9.0, 36.0],
            "Yr": [2024, 2024, 2025, 2025],
            "Market": ["Singapore", "Singapore", "Japan", "Japan"],
        }
    )


def _mapped_record(repo: DatasetRepository, *, with_premium: bool = True):
    """Save the frame and submit a mapping (Insurer/Yr/Market + Written→Premium).

    Unmapped columns carry descriptions because the submit rule requires them."""
    record = repo.save(_frame(), name="book", filename="book.csv")
    targets = {
        "Insurer": "Carrier_Group",
        "Yr": "Year",
        "Market": "Country",
        "Written": "Premium" if with_premium else "",
    }
    columns = ["Insurer", "Written", "Fees", "Commission", "Yr", "Market"]
    error = submit_mappings(
        repo, record.dataset_id, columns,
        [targets.get(c, "") for c in columns],
        [f"{c} column" for c in columns],
    )
    assert error is None, error
    return repo.get(record.dataset_id)


# ── transforms (pure) ────────────────────────────────────────────────────────


def test_safe_eval_arithmetic():
    result = safe_eval(_frame(), "Written + Fees")
    assert list(result) == [110.0, 275.0, 80.0, 330.0]


def test_safe_eval_rejects_calls_and_symbols():
    with pytest.raises(ValueError):
        safe_eval(_frame(), "__import__('os')")
    with pytest.raises(ValueError):
        safe_eval(_frame(), "Written.sum()")
    with pytest.raises(ValueError):
        safe_eval(_frame(), "@x + 1")


def test_apply_transforms_add_then_drop():
    ops = [TransformOp(kind="add", name="Net", formula="Written - Fees"),
           TransformOp(kind="drop", name="Fees")]
    out = apply_transforms(_frame(), ops)
    assert "Net" in out.columns and "Fees" not in out.columns
    assert out["Net"].iloc[0] == 90.0


# ── pivots (pure) ────────────────────────────────────────────────────────────


def test_build_pivot_sum_by_rows_and_cols():
    spec = PivotSpec(rows=("Insurer",), cols="Yr", values="Written")
    flat = build_pivot(_frame(), spec)
    zurich = flat[flat["Insurer"] == "Zurich"].iloc[0]
    assert zurich["2024"] == 100.0 and zurich["2025"] == 75.0


def test_pivot_filters_slice_rows():
    spec = PivotSpec(rows=("Insurer",), values="Written",
                     filters=(("Market", ("Singapore",)),))
    sliced = slice_frame(_frame(), spec)
    assert set(sliced["Market"]) == {"Singapore"}
    flat = build_pivot(_frame(), spec)
    assert "Allianz" not in set(flat["Insurer"])


def test_build_pivot_missing_column_is_friendly():
    with pytest.raises(ValueError, match="not in the dataset"):
        build_pivot(_frame(), PivotSpec(rows=("Nope",), values="Written"))


# ── materialization ──────────────────────────────────────────────────────────


def test_materialize_writes_canonical_gpr_table(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo)
    assert record.status == "mapped"

    n = materialize(repo, record)
    assert n == 4
    gpr = repo.load_frame(record.dataset_id, table=MAPPED_TABLE)
    assert {"Carrier_Group", "Premium", "Year", "Country"} <= set(gpr.columns)
    assert gpr["Premium"].sum() == 725.0

    # Peer queries must return empty, not error: the Peers table exists.
    with repo.engine(record.dataset_id).connect() as conn:
        from sqlalchemy import text
        assert conn.execute(text('SELECT COUNT(*) FROM "Peers"')).scalar() == 0


def test_primary_measure_formula_becomes_premium(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo, with_premium=False)
    assert record.status == "uploaded"  # Premium missing → not mapped yet

    from dataclasses import replace
    primary = _primary_from_fields("Gross Revenue", "", "Written + Fees")
    record = replace(record, primary=primary)
    repo.update_record(record)
    assert record_complete(record)

    materialize(repo, record)
    gpr = repo.load_frame(record.dataset_id, table=MAPPED_TABLE)
    assert gpr["Premium"].iloc[0] == 110.0  # Written + Fees


def test_materialize_rejects_incomplete_mapping(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo, with_premium=False)
    with pytest.raises(ValueError, match="Mapping incomplete"):
        materialize(repo, record)


def test_custom_kpis_materialize_and_enrich_pivots(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo)
    from dataclasses import replace
    kpi = CustomMeasure(name="Commission Rate", formula="Commission / Written",
                        aggregation="avg", format="percent", column="")
    record = replace(record, custom_measures=(kpi,))
    repo.update_record(record)

    materialize(repo, record)
    gpr = repo.load_frame(record.dataset_id, table=MAPPED_TABLE)
    assert "Commission Rate" in gpr.columns
    assert gpr["Commission Rate"].iloc[0] == pytest.approx(0.12)

    enriched = pivot_frame(record, _frame())
    assert "Commission Rate" in enriched.columns


def test_pivot_slice_scopes_materialized_rows(tmp_path):
    """Row-level slice: the pivot's filters select which rows feed the deck."""
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo)
    from dataclasses import replace
    record = replace(record, pivot=PivotSpec(
        rows=("Insurer",), values="Written", filters=(("Market", ("Japan",)),),
    ))
    repo.update_record(record)

    materialize(repo, record)
    gpr = repo.load_frame(record.dataset_id, table=MAPPED_TABLE)
    assert len(gpr) == 2
    assert set(gpr["Country"]) == {"Japan"}


def test_record_json_roundtrip_with_stage2_fields(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo)
    from dataclasses import replace
    record = replace(
        record,
        primary=CustomMeasure(name="GR", formula="Written + Fees"),
        custom_measures=(CustomMeasure(name="Comm", column="Commission"),),
        transforms=(TransformOp(kind="add", name="Net", formula="Written - Fees"),),
        pivot=PivotSpec(rows=("Insurer",), values="Written",
                        filters=(("Market", ("Japan",)),)),
    )
    repo.update_record(record)
    assert record_from_json(repo.get(record.dataset_id).to_json()) == repo.get(record.dataset_id)


# ── column ops through the callback helpers ──────────────────────────────────


def test_add_and_delete_column_helpers(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo)

    assert add_column(repo, record.dataset_id, "Net", "", "", "Written - Fees") is None
    assert add_column(repo, record.dataset_id, "", "", "", "1") is not None       # needs a name
    assert add_column(repo, record.dataset_id, "Bad", "", "", "Nope + 1") is not None  # bad formula
    assert add_column(repo, record.dataset_id, "Net", "", "", "1") is not None    # already exists

    assert delete_column(repo, record.dataset_id, "Commission") is True

    from studio.dataset.materialize import working_frame
    frame = working_frame(repo, repo.get(record.dataset_id))
    assert "Net" in frame.columns and "Commission" not in frame.columns


def test_any_column_can_be_deleted_and_takes_its_mapping_with_it(tmp_path):
    """Mapped columns used to be protected, which left no way to correct a bad upload.
    Deleting one is allowed; the mapping cannot outlive the data it points at."""
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo)
    assert "Insurer" in {m.uploaded for m in record.mappings}

    assert delete_column(repo, record.dataset_id, "Insurer") is True
    after = repo.get(record.dataset_id)
    assert "Insurer" not in {m.uploaded for m in after.mappings}
    assert "Insurer" not in {c.name for c in after.profile.columns}


def test_undo_puts_a_deleted_column_back(tmp_path):
    from studio.authoring.data import undo_shape
    from studio.dataset.materialize import working_frame

    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo)
    delete_column(repo, record.dataset_id, "Insurer")
    assert undo_shape(repo, record.dataset_id) is True

    frame = working_frame(repo, repo.get(record.dataset_id))
    assert "Insurer" in frame.columns
    assert undo_shape(repo, record.dataset_id) is False   # nothing left to undo


# ── precedence: the deck pipeline computes from the uploaded data ────────────


def test_compute_overall_runs_on_submitted_dataset(tmp_path, monkeypatch):
    """The agreed end-state: the SAME primitives that power the deck return
    facts from the uploaded csv, not the governed DB."""
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo)
    assert use_for_deck(repo, record.dataset_id) is None
    assert repo.get(record.dataset_id).status == "submitted"

    from studio.compute import compute_overall

    result = compute_overall(
        filters={"carrier": "Zurich", "year": 2024},
        breakdowns=["Country"],
        engine=repo.engine(record.dataset_id),
    )
    total = next(k for k in result.kpis if k["label"] == "Total GWP")
    assert "100" in total["value"]  # Zurich 2024 Written = 100.0 — from the upload
    assert result.subject == "Zurich"


def test_use_for_deck_rejects_incomplete(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo, with_premium=False)
    error = use_for_deck(repo, record.dataset_id)
    assert error and "incomplete" in error.lower()
    assert repo.get(record.dataset_id).status != "submitted"


def test_generation_blocked_without_a_money_measure(tmp_path, monkeypatch):
    """No Premium (and no primary measure) → Generate is refused, with a reason."""
    monkeypatch.setenv("STUDIO_DATASET_DIR", str(tmp_path))
    from studio.dataset import repository as R

    R.get_repository.cache_clear()
    try:
        repo = R.get_repository()
        from studio.authoring.setup import generation_block_reason
        from studio.dataset.source import dataset_in_use

        no_premium = _mapped_record(repo, with_premium=False)
        store = {"source": "custom", "active": no_premium.dataset_id}
        reason = generation_block_reason(store, dataset_in_use(store))
        assert "no Premium column" in reason

        # Governed source is never blocked by dataset state.
        assert generation_block_reason({"source": "governed"}, None) == ""

        # Custom source with nothing uploaded must not silently use the DB.
        assert "Upload a dataset" in generation_block_reason(
            {"source": "custom", "active": None}, None)

        # Mapped but not handed over yet.
        good = _mapped_record(repo)
        pending = {"source": "custom", "active": good.dataset_id}
        assert "isn't in use yet" in generation_block_reason(pending, dataset_in_use(pending))

        # Submitted with Premium → allowed.
        assert use_for_deck(repo, good.dataset_id) is None
        live = {"source": "custom", "active": good.dataset_id}
        assert generation_block_reason(live, dataset_in_use(live)) == ""
    finally:
        R.get_repository.cache_clear()


def test_premium_mapped_accepts_primary_measure(tmp_path):
    from dataclasses import replace

    from studio.dataset.model import premium_mapped

    repo = DatasetRepository(tmp_path)
    record = _mapped_record(repo, with_premium=False)
    assert premium_mapped(record) is False

    with_primary = replace(record, primary=_primary_from_fields("GR", "", "Written + Fees"))
    assert premium_mapped(with_primary) is True


def test_dataset_in_use_and_filter_options(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_DATASET_DIR", str(tmp_path))
    from studio.dataset import repository as R

    R.get_repository.cache_clear()
    try:
        repo = R.get_repository()
        record = _mapped_record(repo)
        use_for_deck(repo, record.dataset_id)

        from studio.compute import FILTER_COLUMN
        from studio.dataset.source import (
            dataset_dependent_options,
            dataset_filter_options,
            dataset_in_use,
        )

        assert dataset_in_use({"source": "governed", "active": record.dataset_id}) is None
        assert dataset_in_use({"source": "custom", "active": record.dataset_id}) is not None

        opts = dataset_filter_options(record.dataset_id, FILTER_COLUMN)
        carriers = [o["value"] for o in opts["carrier"]]
        assert carriers == ["AXA", "Allianz", "Zurich"]
        assert opts["region"] == []  # unmapped column → empty, not an error

        japan_carriers = [
            o["value"] for o in dataset_dependent_options(
                record.dataset_id, "Carrier_Group", {"Country": "Japan"})
        ]
        assert japan_carriers == ["Allianz", "Zurich"]
    finally:
        R.get_repository.cache_clear()
