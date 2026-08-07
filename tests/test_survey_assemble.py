"""Where the Carrier Survey slide lands, and when it is generated at all.

Hermetic, like ``test_template_assemble.py``: tiny in-memory templates and stubbed
resolvers, so it proves the COMPOSITION without a warehouse.
"""
from __future__ import annotations

import pytest
from pptx import Presentation
from pptx.util import Inches

from studio import compute as C
from studio.template_fill import assemble as A
from studio.template_fill import binding_map as BM


@pytest.fixture(autouse=True)
def _force_opc_merge(monkeypatch):
    monkeypatch.setenv("STUDIO_PPT_MERGE_ENGINE", "opc")


def _tiny(path: str, n: int) -> str:
    prs = Presentation()
    for i in range(n):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text_frame.text = f"s{i}"
    prs.save(path)
    return path


@pytest.fixture
def axes(tmp_path, monkeypatch):
    BM._REGISTRY.clear()
    BM.get_binding_map.cache_clear()
    for name, n in (("overall", 2), ("country", 5), ("survey", 1), ("end", 1)):
        path = _tiny(str(tmp_path / f"{name}.pptx"), n)
        BM._REGISTRY[name] = (lambda name=name, path=path: BM.BindingMap(name, path, ()))
    monkeypatch.setattr(BM, "_discover_json_maps", lambda: None)
    monkeypatch.setattr(A, "resolve_roles", lambda r: {})
    monkeypatch.setattr(A, "resolve_roles_for_product", lambda r, p: {})
    monkeypatch.setattr(A, "resolve_roles_for_country", lambda r, c: {})
    monkeypatch.setattr(A.survey_facts, "has_survey_data", lambda r, c: c != "Atlantis")
    yield
    BM._REGISTRY.clear()
    BM.get_binding_map.cache_clear()


def _result(countries=("Singapore", "Japan")):
    return C.OverallResult(subject="Zurich", flow="gpr",
                           resolved_filters={"Country": tuple(countries)})


def test_premium_only_generates_no_survey_slide(axes):
    decks = A.plan_subdecks(_result(), data_basis="premium")
    assert "survey" not in [d.template for d in decks]


def test_omitting_data_basis_keeps_todays_deck(axes):
    assert "survey" not in [d.template for d in A.plan_subdecks(_result())]


def test_survey_follows_each_country_block(axes):
    decks = A.plan_subdecks(_result(), data_basis="premium_survey")
    assert [d.template for d in decks] == [
        "overall", "country", "survey", "country", "survey", "end"]


def test_the_survey_deck_is_labelled_and_scoped_to_its_country(axes):
    decks = A.plan_subdecks(_result(), data_basis="premium_survey")
    surveys = [d for d in decks if d.template == "survey"]
    assert [d.label for d in surveys] == ["Singapore survey", "Japan survey"]
    assert surveys[0].values["country_name[0]"] == "Singapore"


def test_a_country_with_no_survey_book_is_skipped(axes):
    decks = A.plan_subdecks(_result(("Singapore", "Atlantis")), data_basis="premium_survey")
    assert [d.template for d in decks] == ["overall", "country", "survey", "country", "end"]


def test_an_overall_only_scope_generates_no_survey_slide(axes):
    decks = A.plan_subdecks(_result(), scope="overall", data_basis="premium_survey")
    assert [d.template for d in decks] == ["overall", "end"]


def test_the_merged_deck_has_six_slides_per_country(axes, tmp_path):
    out = A.assemble_deck(_result(), out_path=str(tmp_path / "deck.pptx"),
                          work_dir=str(tmp_path / "work"), data_basis="premium_survey")
    # overall(2) + 2 x (country 5 + survey 1) + end(1)
    assert len(Presentation(out).slides._sldIdLst) == 15


def test_generate_passes_the_selection_s_data_basis_through():
    from pathlib import Path

    src = Path("studio/authoring/generate.py").read_text(encoding="utf-8")
    assert 'data_basis=selection.get("data_basis")' in src
