"""Stage-1 tests for the Studio Data tab: ingest, repository, rail restructure.

Unit tests cover the pure ingest/profile functions; integration tests cover the
upload → save → reload round-trip through a real on-disk repository; regression
tests pin the new rail (Data present, Export folded into Review).
"""
from __future__ import annotations

import io

import pandas as pd
import pytest

from studio.dataset.ingest import profile_frame, read_upload
from studio.dataset.model import ColumnMapping, record_from_json, replace_mappings
from studio.dataset.repository import DatasetRepository


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Insurer": ["Zurich", "AXA", "Zurich", None],
            "GWP": [100.0, 250.5, 75.0, 10.0],
            "Yr": [2024, 2024, 2025, 2025],
        }
    )


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    frame.to_csv(buf, index=False)
    return buf.getvalue()


# ── ingest (pure) ────────────────────────────────────────────────────────────


def test_read_upload_csv_roundtrip():
    frame, truncated = read_upload("book.csv", _csv_bytes(_frame()))
    assert list(frame.columns) == ["Insurer", "GWP", "Yr"]
    assert len(frame) == 4
    assert truncated is False


def test_read_upload_xlsx_roundtrip():
    buf = io.BytesIO()
    _frame().to_excel(buf, index=False)
    frame, _ = read_upload("book.xlsx", buf.getvalue())
    assert list(frame.columns) == ["Insurer", "GWP", "Yr"]
    assert len(frame) == 4


def test_read_upload_rejects_unknown_extension():
    with pytest.raises(ValueError, match="Unsupported file type"):
        read_upload("notes.txt", b"hello")


def test_read_upload_strips_header_whitespace():
    frame, _ = read_upload("x.csv", b" Carrier , Premium \nZurich,10\n")
    assert list(frame.columns) == ["Carrier", "Premium"]


def test_profile_frame_kinds_nulls_distinct():
    profile = profile_frame(_frame())
    assert (profile.n_rows, profile.n_cols) == (4, 3)
    by_name = {c.name: c for c in profile.columns}
    assert by_name["GWP"].kind == "number"
    assert by_name["Insurer"].kind == "text"
    assert by_name["Insurer"].null_pct == 25.0
    assert by_name["Insurer"].n_distinct == 2
    assert "Zurich" in by_name["Insurer"].sample


def test_profile_frame_is_deterministic():
    assert profile_frame(_frame()) == profile_frame(_frame())


# ── repository (integration: real disk round-trip) ───────────────────────────


def test_repository_save_load_roundtrip(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = repo.save(_frame(), name="My book", filename="book.csv")

    assert record.n_rows == 4
    listed = repo.list()
    assert [r.dataset_id for r in listed] == [record.dataset_id]

    reloaded = repo.get(record.dataset_id)
    assert reloaded == record  # profile, name, status all survive the disk trip

    frame = repo.load_frame(record.dataset_id)
    assert list(frame.columns) == ["Insurer", "GWP", "Yr"]
    assert len(frame) == 4


def test_repository_mapping_update_persists(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = repo.save(_frame(), name="book", filename="book.csv")
    mappings = (
        ColumnMapping(uploaded="Insurer", target="Carrier_Group", source="user"),
        ColumnMapping(uploaded="GWP", target="Premium", description="Gross premium", source="user"),
        ColumnMapping(uploaded="Yr", target="Year", source="user"),
    )
    repo.update_record(replace_mappings(record, mappings, status="mapped"))

    reloaded = repo.get(record.dataset_id)
    assert reloaded.status == "mapped"
    assert reloaded.mappings == mappings


def test_repository_delete_removes_both_files(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = repo.save(_frame(), name="book", filename="book.csv")
    repo.delete(record.dataset_id)
    assert repo.list() == []
    assert repo.get(record.dataset_id) is None
    assert repo.load_frame(record.dataset_id) is None


def test_repository_tolerates_bad_ids(tmp_path):
    repo = DatasetRepository(tmp_path)
    assert repo.get("../../etc/passwd") is None
    assert repo.load_frame("nope") is None
    repo.delete("../oops")  # must not raise


def test_record_json_roundtrip(tmp_path):
    repo = DatasetRepository(tmp_path)
    record = repo.save(_frame(), name="book", filename="book.csv")
    assert record_from_json(record.to_json()) == record


# ── mapping-submit glue (the callback body, repository injected) ─────────────


def test_submit_mappings_persists_user_choices(tmp_path):
    from studio.authoring.data import submit_mappings

    repo = DatasetRepository(tmp_path)
    record = repo.save(_frame(), name="book", filename="book.csv")

    error = submit_mappings(
        repo,
        record.dataset_id,
        ["Insurer", "GWP", "Yr"],
        ["Carrier_Group", "Premium", "Year"],
        ["Who wrote the business", "Gross written premium", "Billing year"],
    )
    assert error is None

    reloaded = repo.get(record.dataset_id)
    assert reloaded.status == "mapped"
    by_col = {m.uploaded: m for m in reloaded.mappings}
    assert by_col["Insurer"].target == "Carrier_Group"
    assert by_col["GWP"].description == "Gross written premium"
    assert all(m.source == "user" for m in reloaded.mappings)


def test_submit_mappings_rejects_missing_dataset(tmp_path):
    from studio.authoring.data import submit_mappings

    repo = DatasetRepository(tmp_path)
    assert submit_mappings(repo, "0123456789ab", ["A"], ["Premium"], [""])
    assert submit_mappings(repo, None, [], [], [])


def test_submit_mappings_requires_description_when_unmapped(tmp_path):
    """An unmapped column has nothing but its description to explain it."""
    from studio.authoring.data import submit_mappings

    repo = DatasetRepository(tmp_path)
    record = repo.save(_frame(), name="book", filename="book.csv")

    error = submit_mappings(
        repo, record.dataset_id,
        ["Insurer", "GWP", "Yr"],
        ["Carrier_Group", "Premium", ""],   # Yr left unmapped…
        ["who", "gross", "   "],            # …and only whitespace to explain it
    )
    assert error and "Yr" in error
    assert repo.get(record.dataset_id).mappings == ()  # nothing persisted

    # A description on the unmapped column clears the block.
    assert submit_mappings(
        repo, record.dataset_id,
        ["Insurer", "GWP", "Yr"],
        ["Carrier_Group", "Premium", ""],
        ["who", "gross", "Reporting year, free text"],
    ) is None
    assert len(repo.get(record.dataset_id).mappings) == 3


def test_submit_mappings_incomplete_saves_but_stays_unmapped(tmp_path):
    """Partial HITL work is saved, but without the required trio the record
    must NOT reach ``mapped`` — the deck templates can't fill without it."""
    from studio.authoring.data import submit_mappings

    repo = DatasetRepository(tmp_path)
    record = repo.save(_frame(), name="book", filename="book.csv")

    assert submit_mappings(repo, record.dataset_id, ["GWP"], ["Premium"], ["gross"]) is None

    reloaded = repo.get(record.dataset_id)
    assert reloaded.status == "uploaded"  # saved, but not complete
    assert reloaded.mappings[0].target == "Premium"


# ── rail restructure (regression) ────────────────────────────────────────────


def test_rail_setup_first_data_second_no_export():
    from studio.page.authoring.constants import MODES

    ids = [m["id"] for m in MODES]
    assert ids == ["setup", "data", "canvas", "review"]


def test_data_mode_renders_without_a_deck(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_DATASET_DIR", str(tmp_path))
    from studio.dataset import repository as R

    R.get_repository.cache_clear()
    try:
        from studio.page.authoring.shell import body_for

        body = body_for("data", None, {"idx": 0}, None, cut_groups=[])
        assert body is not None
    finally:
        R.get_repository.cache_clear()


def test_review_body_carries_export_download():
    """Export folded into Review: the download button must live in review_body."""
    import json

    from studio.deck.model import DeckSpec, SlideSpec
    from studio.page.authoring.review import review_body

    deck = DeckSpec(slides=[SlideSpec(layout="cover", title="T")])
    rendered = json.dumps(review_body(deck, None), default=lambda o: getattr(o, "__dict__", str(o)))
    assert "qs-export" in rendered
    assert "Download .pptx" in rendered
