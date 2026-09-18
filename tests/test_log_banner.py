"""The startup banner, the model table and the turn's token summary.

Three things a run should tell you without being asked: what this process is,
which model it will use, and what the turn cost. The first two were answerable
only by reading `.env` and then `core/llm/clients.py` to learn which variable
wins; the third was accumulated correctly and then printed as
`token_total=input_tokens=6100, output_tokens=...` inside a log line.

Run:  pytest tests/test_log_banner.py -q -o pythonpath=.
"""
from __future__ import annotations

import io
import logging

import pytest
from rich.console import Console

import log_banner
from log_console import EventConsoleHandler, token_summary


class _Buffer(io.StringIO):
    encoding = "utf-8"


def _console(width: int = 120) -> tuple[Console, _Buffer]:
    buffer = _Buffer()
    return Console(file=buffer, width=width, no_color=True, legacy_windows=False), buffer


# --------------------------------------------------------------------------- #
# The wordmark
# --------------------------------------------------------------------------- #


def test_the_wordmark_is_five_rows_per_word():
    assert len(log_banner.render_word("VIRTUAL")) == 5
    assert len(log_banner.render_word("ANALYST")) == 5


def test_every_letter_the_wordmark_needs_is_in_the_font():
    for letter in "VIRTUALANALYST":
        assert letter in log_banner._FONT, letter


def test_the_word_is_drawn_with_the_ink_it_is_given():
    """One font, two inks: a console that cannot encode a block still gets shapes."""
    blocks = log_banner.render_word("VI", ink=log_banner.BLOCK)
    ascii_ = log_banner.render_word("VI", ink=log_banner.ASCII_INK)
    assert log_banner.BLOCK in "".join(blocks)
    assert "#" in "".join(ascii_)
    # Identical shapes — only the ink differs.
    assert [row.replace(log_banner.BLOCK, "#") for row in blocks] == ascii_


def test_the_banner_fits_a_normal_terminal():
    """Stacked, because "VIRTUAL ANALYST" on one line is ninety columns."""
    widest = max(len(row) for row in log_banner.render_word("VIRTUAL"))
    assert widest <= 60


def test_an_unknown_letter_is_skipped_not_crashed_on():
    assert log_banner.render_word("V!") == log_banner.render_word("V")
    assert log_banner.render_word("") == []


def test_printing_the_banner_never_raises(monkeypatch):
    """A decoration must not be able to stop a boot."""
    console, _buffer = _console()
    monkeypatch.setattr(log_banner, "banner", lambda **_k: (_ for _ in ()).throw(RuntimeError))
    log_banner.print_banner(console, tiers=[])  # must not raise


# --------------------------------------------------------------------------- #
# Which model
# --------------------------------------------------------------------------- #


def test_the_model_table_names_every_tier():
    console, buffer = _console()
    console.print(log_banner.model_table([
        {"tier": "reason", "model": "gpt-5", "effort": "high", "temperature": ""},
        {"tier": "fast", "model": "gpt-5-mini", "effort": "", "temperature": "0.0"},
    ]))
    out = buffer.getvalue()
    assert "reason" in out and "gpt-5" in out and "high" in out
    assert "fast" in out and "gpt-5-mini" in out


def test_the_tier_table_reports_what_the_next_call_will_use(monkeypatch):
    from core.llm import clients

    monkeypatch.setenv("DEPLOYMENT", "gpt-5")
    monkeypatch.setenv("FAST_DEPLOYMENT", "gpt-5-mini")
    monkeypatch.setenv("REASON_EFFORT", "high")
    rows = {row["tier"]: row for row in clients.describe_tiers()}

    assert rows["reason"]["model"] == "gpt-5"
    assert rows["reason"]["effort"] == "high"
    assert rows["fast"]["model"] == "gpt-5-mini"


def test_an_unconfigured_tier_says_so_rather_than_vanishing(monkeypatch):
    """A silently absent tier is how a turn fails later for a reason nobody saw."""
    from core.llm import clients

    for name in ("DEPLOYMENT", "ENDPOINT", "REASON_DEPLOYMENT", "FAST_DEPLOYMENT",
                 "BALANCED_DEPLOYMENT", "CREATIVE_DEPLOYMENT", "SUMMARY_DEPLOYMENT"):
        monkeypatch.delenv(name, raising=False)
    rows = clients.describe_tiers()
    assert rows and all(row["model"] == "(not configured)" for row in rows)
    assert clients.primary_model() == ""


def test_the_primary_model_is_the_tier_that_writes_the_answer(monkeypatch):
    from core.llm import clients

    monkeypatch.setenv("DEPLOYMENT", "gpt-5")
    monkeypatch.setenv("REASON_DEPLOYMENT", "gpt-5-pro")
    assert clients.primary_model() == "gpt-5-pro"


def test_the_navbar_hides_the_chip_when_no_model_is_configured(monkeypatch):
    from core.llm import clients
    from ui.shell import navbar

    for name in ("DEPLOYMENT", "ENDPOINT", "REASON_DEPLOYMENT", "BALANCED_DEPLOYMENT"):
        monkeypatch.delenv(name, raising=False)
    assert navbar._model_chip().hidden is True

    monkeypatch.setenv("DEPLOYMENT", "gpt-5")
    chip = navbar._model_chip()
    assert getattr(chip, "hidden", False) is False
    assert "gpt-5" in chip.title


# --------------------------------------------------------------------------- #
# What the turn cost
# --------------------------------------------------------------------------- #


def _token_record(**fields) -> logging.LogRecord:
    record = logging.LogRecord("core.observability", logging.INFO, __file__, 1,
                               "turn_token_total", (), None)
    record.event_fields = {"event": "turn_token_total", **fields}
    return record


TOTAL = {"input_tokens": 38300, "output_tokens": 9910,
         "total_tokens": 48210, "cached_tokens": 12766}
BY_AGENT = {"writer": {"input_tokens": 9100, "output_tokens": 3210,
                       "total_tokens": 12310, "cached_tokens": 3033}}


def test_the_turn_total_renders_as_a_table_with_input_output_and_total():
    console, buffer = _console(160)
    EventConsoleHandler(console).emit(
        _token_record(llm_calls=3, token_total=TOTAL, by_agent=BY_AGENT)
    )
    out = buffer.getvalue()
    for header in ("input", "output", "total", "cached"):
        assert header in out
    assert "38,300" in out and "9,910" in out and "48,210" in out
    assert "TURN TOTAL" in out


def test_the_per_agent_split_is_shown_above_the_total():
    console, buffer = _console(160)
    EventConsoleHandler(console).emit(
        _token_record(token_total=TOTAL, by_agent=BY_AGENT)
    )
    out = buffer.getvalue()
    assert "writer" in out and "12,310" in out
    assert out.index("writer") < out.index("TURN TOTAL")


def test_the_call_count_stays_on_the_event_line():
    """The two fields the table is built from move into it; the rest do not."""
    console, buffer = _console(160)
    EventConsoleHandler(console).emit(
        _token_record(llm_calls=3, token_total=TOTAL, by_agent=BY_AGENT)
    )
    out = buffer.getvalue()
    assert "llm_calls=3" in out
    assert "token_total=" not in out, "the dict must not also print inline"


def test_any_other_event_is_not_treated_as_a_token_summary():
    assert token_summary({"event": "route_selected", "token_total": TOTAL}) is None
    assert token_summary({"event": "turn_token_total"}) is None


def test_a_turn_with_no_usage_still_renders():
    """`turn_token_total` only fires when there were calls, but a zeroed total
    must not be a crash either."""
    console, buffer = _console(160)
    EventConsoleHandler(console).emit(_token_record(token_total={}, by_agent={}))
    assert "TURN TOTAL" in buffer.getvalue()
