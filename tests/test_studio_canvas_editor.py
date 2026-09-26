"""The focus canvas's editor: the edit bar, the Fields drawer, and committing a box at once."""
from __future__ import annotations

import json
from types import SimpleNamespace

from studio.page import template_editor as TED
from studio.template_fill import text_edits as TE


def _rendered(component) -> str:
    return json.dumps(component, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False)


def _shape(shape_id, name, paragraphs, *, x=0, y=0, kind="text", table=None):
    return SimpleNamespace(shape_id=shape_id, name=name, kind=kind, paragraphs=paragraphs,
                           table=table, x=x, y=y)


def _slide(*shapes, title="Overall Summary"):
    return SimpleNamespace(shapes=list(shapes), title=lambda: title)


ORIGINAL = ("Premium grew 12%.", "Property drove half the gain.")


# ── committing the lines on screen ───────────────────────────────────────────


def test_apply_commits_every_line_of_the_box_at_once():
    doc = TE.commit_lines({}, "2:7", ["Premium grew 14%.", "  Casualty   led it. "],
                          original=ORIGINAL)
    assert TE.text_edits(doc) == {"2:7": ["Premium grew 14%.", "Casualty led it."]}


def test_enter_inside_a_line_makes_two_paragraphs():
    doc = TE.commit_lines({}, "2:7", ["First.\nSecond."], original=ORIGINAL)
    assert TE.text_edits(doc)["2:7"] == ["First.", "Second."]


def test_applying_the_decks_own_words_is_not_an_edit():
    assert TE.text_edits(TE.commit_lines({}, "2:7", list(ORIGINAL), original=ORIGINAL)) == {}


def test_add_and_delete_keep_what_was_typed_but_not_applied():
    typed = ["Premium grew 14%.", "Property drove half the gain."]
    added = TE.commit_lines({}, "2:7", typed, original=ORIGINAL, add_blank=True)
    assert TE.text_edits(added)["2:7"] == ["Premium grew 14%.", "Property drove half the gain.", ""]
    dropped = TE.commit_lines({}, "2:7", typed, original=ORIGINAL, drop=1)
    assert TE.text_edits(dropped)["2:7"] == ["Premium grew 14%."]


# ── naming what is being edited ──────────────────────────────────────────────


def test_the_title_box_is_the_slide_headline():
    title = _shape(3, "Title 1", ["Overall Summary"])
    block = TE.editable_text(title, 0, {})
    assert TED.block_label(title, _slide(title), block) == "Slide headline"


def test_a_generic_shape_name_is_replaced_by_what_the_box_says():
    bullets = _shape(8, "TextBox 12", list(ORIGINAL))
    single = _shape(9, "Rectangle 3", ["Casualty was the biggest drag on growth this year."])
    slide = _slide(bullets, single)
    assert TED.block_label(bullets, slide, TE.editable_text(bullets, 0, {})) == "Commentary · 2 points"
    assert TED.block_label(single, slide, TE.editable_text(single, 0, {})).startswith("“Casualty was the")


def test_a_table_cell_is_named_by_its_column_header():
    table = _shape(4, "Table 2", [], kind="table",
                   table=[["Key Highlights", "Figure"], ["Premium up", "12%"]])
    cell = TE.editable_cells(table, 0, {})[2]          # row 1, column 0
    assert TED.block_label(table, _slide(table), cell) == "Key Highlights · row 1"


# ── the bar and the drawer ───────────────────────────────────────────────────


def test_with_nothing_selected_the_panel_has_nothing_to_show():
    bar = TED.edit_bar(None)
    assert "is-empty" in bar.className                   # CSS keeps the panel folded away


def test_a_selected_box_opens_its_editor_with_apply_and_close():
    block = TE.editable_text(_shape(8, "TextBox", list(ORIGINAL)), 2, {})
    bar = _rendered(TED.edit_bar(block, "Commentary · 2 points"))
    assert bar.count('"qs-tf-line"') == 2
    assert '"qs-tf-apply"' in bar and '"qs7-close"' in bar and '"data-at": "2:8"' in bar
    assert "Commentary · 2 points" in bar


def test_the_panel_lists_nothing_but_the_selected_box():
    block = TE.editable_text(_shape(8, "TextBox", list(ORIGINAL)), 2, {})
    panel = _rendered(TED.edit_panel(TED.edit_bar(block, "x")))
    assert '"qs-tf-pickl"' not in panel and panel.count('"qs-tf-apply"') == 1


def test_text_blocks_are_in_reading_order_for_their_labels():
    low = _shape(9, "TextBox 9", ["Lower box on the page."], y=5_000_000)
    high = _shape(8, "TextBox 8", ["Upper box on the page."], y=1_000_000)
    blocks = TED.text_blocks(_slide(low, high), 0, {})
    assert [b.address.key for b, _ in blocks] == ["0:8", "0:9"]
