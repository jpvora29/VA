"""Setup over an uploaded dataset: a filter change reads cubes, never the whole frame.

On a million-row upload every filter change used to re-derive, from the full frame, facts that
do not depend on the selection — the quarter rows (one Python call per row), the latest billing
month (a date parse per row) — and copied the frame on every read. The dropdowns and the preview
also built two separate cubes, keyed on the dataset id alone, so a re-mapped dataset kept its
old options. These tests pin each of those contracts.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from studio import cube_store
from studio import filter_cube as FC
from studio import scope_cube as SC
from studio.cube_index import CubeEncoder
from studio.dataset import source as SRC
from studio.dataset.materialize import _ensure_empty_peers
from studio.dataset.repository import MAPPED_TABLE, DatasetRepository


def _book(carriers=("AIG", "Chubb", "Zurich")) -> pd.DataFrame:
    rows = []
    for i, carrier in enumerate(carriers):
        for country, region in (("Japan", "Asia"), ("Singapore", "Asia"), ("France", "Europe")):
            for year in (2024, 2025):
                for month in ("January", "July"):
                    rows.append({"Region": region, "Country": country, "Carrier_Group": carrier,
                                 "Year": year, "Month_Name": month,
                                 "Premium": 100.0 * (i + 1) + year % 10})
    return pd.DataFrame(rows)


def _write_gpr(repo: DatasetRepository, dataset_id: str, frame: pd.DataFrame) -> None:
    frame.to_sql(MAPPED_TABLE, repo.engine(dataset_id), if_exists="replace", index=False)
    _ensure_empty_peers(repo.engine(dataset_id))


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    """A submitted dataset in a private store, wired in as the process repository."""
    repo = DatasetRepository(tmp_path)
    record = repo.save(_book().head(2), name="book", filename="book.csv")
    _write_gpr(repo, record.dataset_id, _book())
    record = replace(record, status="submitted")
    repo.update_record(record)
    monkeypatch.setattr(SRC, "get_repository", lambda: repo)
    FC.clear()
    SC.clear()
    yield repo, record
    FC.clear()
    SC.clear()


# ── the vectorised build is the row encoder's answer ─────────────────────────


def _row_encoded(frame, columns, measure=None) -> cube_store.CubeData:
    """The cube the way it was built before: rolled-up rows folded one value at a time."""
    if measure:
        rolled = frame.groupby(list(columns), dropna=False)[measure].sum().reset_index()
    else:
        rolled = frame[list(columns)].drop_duplicates()
    encoder = CubeEncoder(columns, with_measure=bool(measure))
    encoder.add(list(rolled.itertuples(index=False, name=None)))
    index, measures = encoder.finish()
    return cube_store.CubeData(columns=tuple(columns), index=index, measures=measures)


def _mixed_frame(n=4000) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    country = rng.choice(["Japan", "Singapore", "France", None], n).astype(object)
    return pd.DataFrame({
        "Country": country,
        "Carrier_Group": rng.choice([f"Carrier {i}" for i in range(12)], n),
        "Year": rng.choice([2023, 2024, 2025], n),
        "Product_Line": rng.choice(["Cyber", "Marine", "Property"], n),
        "Premium": rng.gamma(2.0, 100.0, n),
    })


SELECTIONS = (
    {},
    {"Country": "Japan"},
    {"Carrier_Group": "Carrier 3", "Year": 2025},
    {"Country": ["France", "Singapore"], "Product_Line": "Cyber"},
    {"Year": "2024"},
)


def test_the_vectorised_frame_cube_cascades_like_the_row_encoder():
    frame = _mixed_frame()
    columns = ("Country", "Carrier_Group", "Year", "Product_Line")
    new = FC.FilterCube(cube_store.build_frame(frame, columns, measure="Premium"))
    old = FC.FilterCube(_row_encoded(frame, columns))
    for selected in SELECTIONS:
        assert new.cascade(selected) == old.cascade(selected), selected


def test_the_vectorised_rollup_totals_and_ranks_like_the_row_encoder():
    frame = _mixed_frame()
    columns = ("Country", "Carrier_Group", "Year", "Product_Line")
    new = SC.ScopeCube(cube_store.build_frame(frame, columns, measure="Premium"))
    old = SC.ScopeCube(_row_encoded(frame, columns, measure="Premium"))
    for selected in SELECTIONS:
        assert new.total(selected) == pytest.approx(old.total(selected)), selected
        assert new.rank("Carrier_Group", "Carrier 3", selected) == \
            old.rank("Carrier_Group", "Carrier 3", selected), selected


def test_a_year_keeps_its_type_through_the_vectorised_build():
    frame = _mixed_frame(200)
    cube = FC.FilterCube(cube_store.build_frame(frame, ("Year",)))
    assert all(isinstance(v, int) for v in cube.cascade({})["Year"])


# ── one cube, per version ────────────────────────────────────────────────────


def test_the_cascade_and_the_preview_share_one_cube_build(dataset, monkeypatch):
    from studio.scope import scope_figures

    repo, record = dataset
    builds = []
    real = cube_store.build_frame
    monkeypatch.setattr(cube_store, "build_frame",
                        lambda *a, **k: builds.append(1) or real(*a, **k))

    SRC.dataset_cascade_options(record.dataset_id, ("Carrier_Group",), {"Country": "Japan"})
    figures = scope_figures({"Carrier_Group": "AIG", "Country": "Japan"}, flow="gpr",
                            engine=repo.engine(record.dataset_id),
                            dataset_id=record.dataset_id)

    assert len(builds) == 1
    assert figures.total == pytest.approx(_book().query(
        "Carrier_Group == 'AIG' and Country == 'Japan'")["Premium"].sum())


def test_a_remapped_dataset_serves_its_new_options_not_the_old_cube(dataset):
    repo, record = dataset
    before = SRC.dataset_cascade_options(record.dataset_id, ("Carrier_Group",))
    assert [o["value"] for o in before["Carrier_Group"]] == ["AIG", "Chubb", "Zurich"]

    _write_gpr(repo, record.dataset_id, _book(carriers=("Allianz", "AXA")))   # re-materialized

    after = SRC.dataset_cascade_options(record.dataset_id, ("Carrier_Group",))
    assert [o["value"] for o in after["Carrier_Group"]] == ["AXA", "Allianz"]


# ── a filter change re-derives nothing from the frame ────────────────────────


def test_setup_reads_the_shared_frame_without_copying_it(dataset):
    _repo, record = dataset
    assert SRC.dataset_frame(record.dataset_id) is SRC.dataset_frame(record.dataset_id)


def test_after_the_warm_up_a_filter_change_touches_no_frame_wide_work(dataset, monkeypatch):
    from studio import book, quarter_scope
    from studio.authoring import setup as S

    _repo, record = dataset
    SRC.warm_dataset(record.dataset_id).join()

    def frame_wide(*_a, **_k):
        raise AssertionError("re-derived from the whole frame on a filter change")

    monkeypatch.setattr(cube_store, "build_frame", frame_wide)
    monkeypatch.setattr(quarter_scope, "frame_quarter_rows", frame_wide)
    monkeypatch.setattr(book, "_frame_latest", frame_wide)

    for selected in ({"region": "Asia"}, {"region": "Asia", "carrier": "AIG"},
                     {"country": ["Japan"], "carrier": "Chubb", "year": 2025}):
        options = S.cascade_filter_options(selected, record)
        assert options                                     # still answered, from the caches
    assert S.latest_month(record.dataset_id) == (2025, 7)


def test_the_quarter_list_still_follows_the_selection(dataset):
    _repo, record = dataset
    assert SRC.dataset_quarters_in_scope(record.dataset_id, {"Country": "Japan"}) == ["Q1", "Q3"]
    assert SRC.dataset_quarters_in_scope(record.dataset_id, {"Country": "Narnia"}) == []


def test_blank_cells_are_not_offered_as_options(dataset):
    repo, record = dataset
    frame = _book()
    frame.loc[0, "Country"] = None
    _write_gpr(repo, record.dataset_id, frame)

    first_render = SRC.dataset_filter_options(record.dataset_id, {"country": "Country"})
    after_change = SRC.dataset_cascade_options(record.dataset_id, ("Country",),
                                               {"Carrier_Group": "AIG"})
    assert [o["value"] for o in first_render["country"]] == ["France", "Japan", "Singapore"]
    assert [o["value"] for o in after_change["Country"]] == ["France", "Japan", "Singapore"]
