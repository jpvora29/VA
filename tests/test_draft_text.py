"""The live draft reads as prose while it is still being written.

The streamed draft is plain text (markdown mid-sentence is not markdown — see
`ui.draft_text`), so the leftover syntax gets one cosmetic pass. The contract these
pin: markup characters may go, WORDS may never go, and nothing is reordered — the
reader must always be looking at a faithful prefix of the answer they will get.

Run:  pytest tests/test_draft_text.py -q
"""
from __future__ import annotations

import re

import pytest

from ui.draft_text import draft_text


def _words(text: str) -> list[str]:
    """The alphanumeric runs in a string — what must survive the softening.

    Punctuation is excluded deliberately: removing a backtick legitimately joins
    ``Cyber`` to the full stop after it, and that is markup going, not a word.
    """
    return re.findall(r"[A-Za-z0-9]+", text)


# ── emphasis, including the half-written kind ────────────────────────────────


def test_closed_emphasis_is_unwrapped():
    assert draft_text("premium grew **12.4%** on the year") == \
        "premium grew 12.4% on the year"


def test_an_unclosed_marker_does_not_leave_asterisks_hanging():
    """The whole point: mid-token, the closing marker has not arrived yet."""
    assert draft_text("growth was led by **Cyber") == "growth was led by Cyber"


@pytest.mark.parametrize("marker", ["**", "__", "*", "`"])
def test_every_inline_marker_is_softened(marker):
    assert draft_text(f"the {marker}Marine{marker} book") == "the Marine book"


# ── block markers ────────────────────────────────────────────────────────────


def test_heading_hashes_are_dropped_but_the_heading_text_stays():
    assert draft_text("## Recommendations") == "Recommendations"


def test_a_quote_marker_is_dropped():
    assert draft_text("> the latest year runs to Q2") == "the latest year runs to Q2"


def test_a_bullet_still_reads_as_a_bullet():
    assert draft_text("- Review pricing\n- Defend the book") == \
        "• Review pricing\n• Defend the book"


def test_bullet_indentation_is_preserved():
    assert draft_text("  - nested point") == "  • nested point"


# ── tables ───────────────────────────────────────────────────────────────────


def test_a_table_row_becomes_spaced_cells():
    assert draft_text("| Cyber | $1.8m | +21.4% |") == "Cyber   $1.8m   +21.4%"


def test_the_separator_row_is_dropped_entirely():
    table = "| Product | Premium |\n| --- | --- |\n| Cyber | $1.8m |"
    assert draft_text(table) == "Product   Premium\nCyber   $1.8m"


def test_a_half_written_table_row_keeps_what_has_arrived():
    assert draft_text("| Cyber | $1.8m | +21.") == "Cyber   $1.8m   +21."


def test_a_sentence_containing_a_pipe_is_left_alone():
    """Only a line that STARTS a table row is scaffolding; prose is not."""
    line = "throughput | latency was the trade-off"
    assert draft_text(line) == line


# ── the invariant that matters ───────────────────────────────────────────────


def test_no_word_is_ever_lost():
    streamed = (
        "## Premium\n\n"
        "Zurich grew **12.4%** to $4.2m, led by `Cyber`.\n\n"
        "| Product | Premium |\n| --- | --- |\n| Cyber | $1.8m |\n\n"
        "- Defend the **renewal** book\n"
        "> data runs to Q2 only"
    )
    assert _words(draft_text(streamed)) == _words(streamed)


def test_softening_is_stable_as_more_tokens_arrive():
    """Each prefix must soften to a prefix of the softened whole — otherwise the
    bubble would rewrite text the reader has already read."""
    full = "Zurich grew **12.4%** to $4.2m in Canada."
    softened = draft_text(full)
    for cut in range(1, len(full) + 1):
        partial = draft_text(full[:cut])
        assert softened.startswith(partial), (full[:cut], partial)


def test_a_table_stays_stable_as_it_streams_in():
    """The hard case for stability: the separator row is dropped, so a naive
    implementation makes the bubble shrink halfway through building a table."""
    full = "Premium by product:\n\n| Product | Premium |\n| --- | --- |\n| Cyber | $1.8m |"
    softened = draft_text(full)
    for cut in range(1, len(full) + 1):
        assert softened.startswith(draft_text(full[:cut])), full[:cut]


def test_empty_input_is_empty_output():
    assert draft_text("") == ""
    assert draft_text(None) == ""
