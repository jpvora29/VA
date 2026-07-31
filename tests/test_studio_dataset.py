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


# ── the upload error message must name the real cause, not guess "wrong type" ──


def _ooxml_bytes() -> bytes:
    buf = io.BytesIO()
    _frame().to_excel(buf, index=False)
    return buf.getvalue()


def test_macro_enabled_workbook_is_accepted():
    """A .xlsm is the same OOXML zip as a .xlsx; rejecting it read as 'wrong type'."""
    frame, _ = read_upload("book.xlsm", _ooxml_bytes())
    assert list(frame.columns) == ["Insurer", "GWP", "Yr"]


def test_extension_match_is_case_insensitive():
    frame, _ = read_upload("BOOK.XLSX", _ooxml_bytes())
    assert len(frame) == 4


def test_legacy_xls_engine_is_installed():
    """`.xls` is advertised as supported, so pandas' xlrd engine must be present —
    without it a perfectly good workbook failed with 'is it a valid spreadsheet?'."""
    import xlrd  # noqa: F401 — a declared dependency; the assert is the import

    from studio.dataset.ingest import _READERS

    assert _READERS[".xls"].__name__ == "_read_xlrd"


def test_no_advertised_extension_fails_vaguely():
    """SUPPORTED_EXTENSIONS drives the picker's `accept`, so every listed type must
    either parse or explain exactly what is missing — never 'wrong file type'."""
    from studio.dataset.ingest import SUPPORTED_EXTENSIONS

    for ext in SUPPORTED_EXTENSIONS:
        try:
            read_upload(f"book{ext}", _ooxml_bytes())
        except ValueError as exc:
            message = str(exc)
            assert "Unsupported file type" not in message, ext
            # Either an engine is missing, or the bytes genuinely aren't that format.
            assert "package" in message or "named" in message or "could not be" in message, (ext, message)


def test_empty_upload_blames_the_cloud_placeholder_not_the_file_type():
    with pytest.raises(ValueError, match="empty"):
        read_upload("book.xlsx", b"")


def test_mislabelled_workbook_says_what_it_actually_is():
    """A legacy/encrypted workbook renamed .xlsx: the type IS wrong, so say so
    precisely instead of 'is it a valid spreadsheet?'."""
    with pytest.raises(ValueError, match="legacy .xls workbook, or a password-protected"):
        read_upload("book.xlsx", b"\xd0\xcf\x11\xe0" + b"\x00" * 32)


def test_html_saved_as_xlsx_is_named_as_such():
    with pytest.raises(ValueError, match="HTML or XML"):
        read_upload("book.xlsx", b"<html><table><tr><td>1</td></tr></table>")


def test_missing_engine_names_the_package(monkeypatch):
    """When an optional engine is absent the file is fine — we are not. Say which
    package to install rather than implying the upload was the wrong type."""
    from studio.dataset import ingest

    def _no_engine(_data):
        raise ImportError("Missing optional dependency 'pyxlsb'")

    monkeypatch.setitem(ingest._READERS, ".xlsb", _no_engine)
    with pytest.raises(ValueError, match="pyxlsb"):
        read_upload("book.xlsb", b"PK\x03\x04")


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


# ── callbacks must never point at a component the page can hide ──────────────


def _component_ids(node) -> set:
    """Every plain-string component id in a rendered Dash tree."""
    found, stack = set(), [node]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        if isinstance(item, str) or item is None:
            continue
        cid = getattr(item, "id", None)
        if isinstance(cid, str):
            found.add(cid)
        children = getattr(item, "children", None)
        if children is not None:
            stack.append(children)
    return found


def _output_ids(callback) -> list:
    outputs = callback["output"]
    outputs = outputs if isinstance(outputs, (list, tuple)) else [outputs]
    return [o.component_id for o in outputs if isinstance(getattr(o, "component_id", None), str)]


def _fixed(dependencies) -> list:
    """Plain-string ids only — a pattern-matching id reads back as '{"…":["ALL"]}'."""
    return [d["id"] for d in dependencies if not d["id"].startswith("{")]


def test_data_callbacks_never_reference_a_component_the_page_hides(tmp_path, monkeypatch):
    """Regression: the primary-measure card disappears once a column maps to
    Premium, and Submit still declared ``State("qs-primary-name")`` — so Dash
    refused the callback with "a nonexistent object was used in a State".

    The invariant, for every Data callback and every page state: if the callback
    CAN fire (its fixed Inputs are on the page) then its fixed States and Outputs
    must be on that page too.
    """
    from dataclasses import replace

    from studio.authoring.data import register_data
    from studio.authoring.layout import build_layout, create_app
    from studio.dataset import repository as R
    from studio.page.authoring.data import data_body

    monkeypatch.setenv("STUDIO_DATASET_DIR", str(tmp_path))
    R.get_repository.cache_clear()
    try:
        repo = R.get_repository()
        # (a) a column mapped to Premium → the primary-measure card is hidden
        mapped = repo.save(_frame(), name="mapped", filename="a.csv")
        repo.update_record(replace(mapped, mappings=(
            ColumnMapping(uploaded="GWP", target="Premium", description="premium", source="user"),
        )))
        # (b) nothing maps to Premium → the card is shown
        unmapped = repo.save(_frame(), name="unmapped", filename="b.csv")

        app = create_app()
        register_data(app)
        layout_ids = _component_ids(build_layout())

        states = [
            {"active": mapped.dataset_id},
            {"active": unmapped.dataset_id},
            None,                                    # no dataset selected
        ]
        for state in states:
            page_ids = layout_ids | _component_ids(data_body(state))
            for callback in app.callback_map.values():
                if not set(_fixed(callback["inputs"])) <= page_ids:
                    continue                          # can't fire on this page
                missing = [
                    dep for dep in _fixed(callback["state"]) + _output_ids(callback)
                    if dep not in page_ids
                ]
                assert not missing, (state, missing)
    finally:
        R.get_repository.cache_clear()


def test_primary_measure_fields_survive_the_card_being_hidden():
    """The three fields carry pattern-matching ids so an absent card reads back
    as an empty list instead of breaking the Submit callback."""
    import json

    from studio.dataset.model import DatasetRecord
    from studio.page.authoring.data import _primary_measure_card

    record = DatasetRecord(
        dataset_id="d", name="n", filename="f.csv", created="2026-07-30", n_rows=1, n_cols=1,
    )
    rendered = json.dumps(_primary_measure_card(record), default=lambda o: getattr(o, "__dict__", str(o)))
    for field in ("name", "column", "formula"):
        assert f"'field': '{field}'" in rendered or f'"field": "{field}"' in rendered
    assert "qs-primary-name" not in rendered


def test_review_body_carries_export_download():
    """Export folded into Review: the download button must live in review_body."""
    import json

    from studio.deck.model import DeckSpec, SlideSpec
    from studio.page.authoring.review import review_body

    deck = DeckSpec(slides=[SlideSpec(layout="cover", title="T")])
    rendered = json.dumps(review_body(deck, None), default=lambda o: getattr(o, "__dict__", str(o)))
    assert "qs-export" in rendered
    assert "Download .pptx" in rendered
