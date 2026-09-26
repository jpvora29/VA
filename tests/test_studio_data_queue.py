"""The Data tab's review queue: which rows need a person, why, and how ready the deck is."""
from __future__ import annotations

from studio.dataset.model import ColumnMapping, ColumnProfile, DatasetProfile, DatasetRecord
from studio.page.authoring import data_queue as Q


def _record(mappings, columns):
    return DatasetRecord(dataset_id="d", name="book", filename="book.csv", created="2026-09-26",
                         n_rows=10, n_cols=len(columns), mappings=tuple(mappings),
                         profile=DatasetProfile(10, len(columns), tuple(columns)))


COLUMNS = (
    ColumnProfile("Written Premium", "number", 0.0, 900, ("12480320", "8930440")),
    ColumnProfile("Carrier Group", "text", 0.0, 8, ("Zurich", "AIG")),
    ColumnProfile("Invoice Date", "text", 0.0, 400, ("15 Jan 2026", "28 Feb 2026")),
    ColumnProfile("Insurer Ref", "text", 0.0, 50, ("A-1", "A-2")),
    ColumnProfile("Line", "text", 0.0, 5, ("Property", "Cyber")),
)
MAPPINGS = (
    ColumnMapping("Written Premium", "Premium", "", 0.95, "alias"),
    ColumnMapping("Carrier Group", "Carrier_Group", "", 1.0, "alias"),
    ColumnMapping("Line", "Product_Line", "", 0.7, "fuzzy"),
)


def _desc(profile, mapping):
    return (mapping.description if mapping else "") or ""


def test_letters_follow_the_spreadsheet():
    assert [Q.column_letter(i) for i in (0, 5, 25, 26)] == ["A", "F", "Z", "AA"]


def test_confidence_reads_as_high_medium_low():
    assert Q.confidence_tier(MAPPINGS[0]) == Q.HIGH
    assert Q.confidence_tier(MAPPINGS[2]) == Q.MEDIUM
    assert Q.confidence_tier(ColumnMapping("x", "Region", "", 0.4, "fuzzy")) == Q.LOW
    assert Q.confidence_tier(ColumnMapping("x", "Region", "", 0.4, "user")) == Q.HIGH
    assert Q.confidence_tier(None) == ""


def test_each_row_says_why_in_the_matchers_terms():
    premium, carrier, date, ref, line = COLUMNS
    assert Q.reason(premium, MAPPINGS[0]) == "Name matches Premium"
    assert Q.reason(line, MAPPINGS[2]) == "Name is close to Product Line"
    assert "describe it" in Q.reason(ref, None)
    assert "Year" in Q.reason(date, None)


def test_the_queue_puts_unsure_undescribed_and_date_rows_first():
    decide, suggested = Q.queue(_record(MAPPINGS, COLUMNS), _desc)
    assert [r.profile.name for r in decide] == ["Invoice Date", "Insurer Ref", "Line"]
    assert [r.profile.name for r in suggested] == ["Written Premium", "Carrier Group"]
    assert [r.can_derive_year for r in decide] == [True, False, False]


def test_a_described_unmapped_column_leaves_the_queue():
    described = MAPPINGS + (ColumnMapping("Insurer Ref", "", "Internal reference", 0, "user"),)
    decide, _ = Q.queue(_record(described, COLUMNS), _desc)
    assert "Insurer Ref" not in [r.profile.name for r in decide]


def test_text_dates_are_recognised_but_numbers_are_not():
    assert Q.is_date_like(COLUMNS[2])
    assert not Q.is_date_like(ColumnProfile("Yr", "text", 0, 2, ("2024", "2025")))
    assert not Q.is_date_like(COLUMNS[1])


def test_readiness_names_the_source_and_offers_year_from_a_date():
    items = {i.target: i for i in Q.readiness(_record(MAPPINGS, COLUMNS))}
    assert items["Premium"].ready and items["Premium"].detail == "Mapped from Written Premium"
    assert items["Carrier_Group"].ready
    assert not items["Year"].ready and items["Year"].derive_from == "Invoice Date"
