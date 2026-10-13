"""Runtime files live out of OneDrive, and the shared warehouse is never written.

Why this exists: the project is shared through a synced OneDrive folder. Every file
the app wrote there (app_state.db, uploaded datasets, the seed, caches) and every
index it added to the shared warehouse turned into conflict copies — one per user.
These tests pin the two rules that stop it: runtime stores default to
``%LOCALAPPDATA%\\VA``, and a configured warehouse is opened read-only and indexed
only by ``studio.index_warehouse``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from core.local_paths import local_data_dir
from core.readonly_sqlite import readonly_sqlite_engine
from studio import index_warehouse
from studio.indexes import missing_index_names


@pytest.fixture
def warehouse(tmp_path):
    """A GPR-shaped warehouse file with no indexes."""
    path = tmp_path / "warehouse.db"
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE GPR (Country TEXT, Carrier_Group TEXT, Product_Line TEXT, "
            "Client_Segment TEXT, Year INTEGER, Premium REAL)"
        ))
        conn.execute(text(
            "INSERT INTO GPR VALUES ('Singapore', 'Zurich', 'Property', 'Corporate', 2024, 1.0)"
        ))
    eng.dispose()
    return path


# ── local folder ─────────────────────────────────────────────────────────────

def test_runtime_files_default_to_the_users_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert local_data_dir() == tmp_path / "VA"


def test_studio_stores_resolve_under_the_local_folder(monkeypatch, tmp_path):
    from studio import cube_store
    from studio.dataset import repository
    from studio.template_fill import commentary_cache

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for var in ("STUDIO_CACHE_DIR", "STUDIO_DATASET_DIR", "STUDIO_COMMENTARY_CACHE"):
        monkeypatch.delenv(var, raising=False)
    assert cube_store.cache_dir() == tmp_path / "VA" / "cache"
    assert repository._store_dir() == tmp_path / "VA" / "datasets"
    assert commentary_cache.cache_dir() == tmp_path / "VA" / "cache" / "commentary"


def test_env_overrides_still_win(monkeypatch, tmp_path):
    from studio import cube_store
    from studio.dataset import repository

    monkeypatch.setenv("STUDIO_CACHE_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("STUDIO_DATASET_DIR", str(tmp_path / "d"))
    assert cube_store.cache_dir() == tmp_path / "c"
    assert repository._store_dir() == tmp_path / "d"


# ── read-only warehouse ──────────────────────────────────────────────────────

def test_readonly_engine_reads_but_refuses_every_write(warehouse):
    before = warehouse.read_bytes()
    eng = readonly_sqlite_engine(warehouse)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM GPR")).scalar() == 1
    with pytest.raises(OperationalError, match="readonly"):
        with eng.begin() as conn:
            conn.execute(text('CREATE INDEX ix_probe ON GPR ("Year")'))
    eng.dispose()
    assert warehouse.read_bytes() == before


def test_studio_engine_opens_a_configured_warehouse_read_only(monkeypatch, warehouse):
    from studio import data

    monkeypatch.setenv("STUDIO_DB_PATH", str(warehouse))
    data.get_engine.cache_clear()
    try:
        eng = data.get_engine()
        # It used to index the file here; now it only reports what is missing.
        assert missing_index_names(("gpr",), eng)
        with pytest.raises(OperationalError, match="readonly"):
            with eng.begin() as conn:
                conn.execute(text('CREATE INDEX ix_probe ON GPR ("Year")'))
        eng.dispose()
    finally:
        data.get_engine.cache_clear()


# ── publishing: the one place that indexes ───────────────────────────────────

def test_index_warehouse_builds_every_index_then_has_nothing_to_do(warehouse, capsys):
    assert index_warehouse.main([str(warehouse)]) == 0
    assert "Safe to publish" in capsys.readouterr().out

    eng = readonly_sqlite_engine(warehouse)
    assert missing_index_names(("gpr", "survey"), eng) == []
    eng.dispose()

    assert index_warehouse.main([str(warehouse)]) == 0
    assert "none needed" in capsys.readouterr().out


def test_index_warehouse_skips_a_flow_whose_table_is_absent(warehouse):
    # The fixture has GPR but no survey table: survey is not "missing" indexes.
    eng = create_engine(f"sqlite:///{warehouse}")
    index_warehouse.build_indexes(eng, ("gpr", "survey"))
    assert missing_index_names(("gpr", "survey"), eng) == []
    eng.dispose()


def test_filter_indexes_are_opt_in_and_keep_their_old_names(warehouse):
    from studio.indexes import existing_indexes, filter_index_plan

    assert index_warehouse.main([str(warehouse)]) == 0
    eng = create_engine(f"sqlite:///{warehouse}")
    assert "ix_studio_GPR_Country" not in existing_indexes(eng, "GPR")

    assert index_warehouse.main([str(warehouse), "--filter-indexes"]) == 0
    present = existing_indexes(eng, "GPR")
    # Same names the old warm_cache --indexes built, so a file that has them is not re-indexed.
    assert {"ix_studio_GPR_Country", "ix_studio_GPR_Year"} <= present
    # The fixture has no Quarter column: skipped, not reported missing (exit 0 above).
    assert "ix_studio_GPR_Quarter" not in present
    planned = {spec.name for spec in filter_index_plan("gpr")}
    assert {"ix_studio_GPR_Country", "ix_studio_GPR_Year"} <= planned
    eng.dispose()


def test_warm_cache_indexes_flag_points_to_the_publishing_command(capsys):
    from studio import warm_cache

    with pytest.raises(SystemExit):
        warm_cache.main(["--indexes"])
    assert "studio.index_warehouse" in capsys.readouterr().out


def test_index_warehouse_refuses_a_missing_file(tmp_path):
    with pytest.raises(SystemExit):
        index_warehouse.main([str(tmp_path / "nope.db")])
