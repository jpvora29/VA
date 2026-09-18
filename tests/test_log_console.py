"""The console rendering of structured log events.

The complaint these lock in: a run was hard to follow. Events arrived as one
alphabetised JSON blob per line, wrapped ragged by the terminal, with the node
buried in the payload, no boundary between turns, and a field holding rows shown
as a bracketed string.

Each test here pins one of the things that fixes. They assert what a reader SEES
— the handler is rendered to a fixed-width console and the text is checked — not
how the renderer is put together.

Run:  pytest tests/test_log_console.py -q -o pythonpath=.
"""
from __future__ import annotations

import io
import logging

import pytest
from rich.console import Console

import log_console
from log_console import EventConsoleHandler


class _Buffer(io.StringIO):
    """A buffer that reports an encoding, which `supports_glyphs` reads off the
    stream (`io.StringIO.encoding` is not writable)."""

    encoding = "utf-8"


def _console() -> tuple[Console, _Buffer]:
    """A console writing to a buffer, wide enough that nothing wraps."""
    buffer = _Buffer()
    return Console(file=buffer, width=160, no_color=True, legacy_windows=False), buffer


def _record(event: str, level: int = logging.INFO, **fields) -> logging.LogRecord:
    record = logging.LogRecord("core.graph.analyst_subgraph", level, __file__, 1,
                               event, (), None)
    record.event_fields = {"event": event, **fields}
    return record


def _emit(*records: logging.LogRecord, plain: bool = False) -> str:
    console, buffer = _console()
    handler = EventConsoleHandler(console, plain=plain)
    for record in records:
        handler.emit(record)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Separation between turns
# --------------------------------------------------------------------------- #


def test_a_new_turn_draws_a_rule():
    """Two runs must never read as one. `trace_id` changing IS the boundary."""
    out = _emit(
        _record("route_selected", node="router", trace_id="aaaaaaaabbbb"),
        _record("route_selected", node="router", trace_id="ccccccccdddd"),
    )
    assert out.count("turn ") == 2
    assert "turn aaaaaaaa" in out and "turn cccccccc" in out


def test_events_inside_one_turn_share_a_single_rule():
    out = _emit(
        _record("route_selected", node="router", trace_id="aaaaaaaabbbb"),
        _record("depth_floored", node="intent_classifier", trace_id="aaaaaaaabbbb"),
        _record("analysis_planned", node="analyst_planner", trace_id="aaaaaaaabbbb"),
    )
    assert out.count("turn aaaaaaaa") == 1


def test_the_rule_names_the_conversation_too():
    out = _emit(_record("x", node="n", trace_id="aaaaaaaabbbb", thread_id="chat-7f2a91"))
    assert "chat-7f2a91" in out


def test_an_event_with_no_trace_draws_no_rule():
    """A module logging outside a turn has no turn to separate."""
    assert "turn " not in _emit(_record("skill_load", node="gpr_chart"))


# --------------------------------------------------------------------------- #
# The line itself
# --------------------------------------------------------------------------- #


def test_the_node_gets_a_column_instead_of_being_buried_in_the_payload():
    out = _emit(_record("positioning_gathered", node="analyst_positioning",
                        route="premium"))
    line = next(l for l in out.splitlines() if "positioning_gathered" in l)
    # event, then node, then the fields — in that order, on one line.
    assert line.index("positioning_gathered") < line.index("analyst_positioning")
    assert line.index("analyst_positioning") < line.index("route=")


def test_the_ids_already_in_the_rule_are_not_repeated_on_every_line():
    out = _emit(_record("x", node="n", trace_id="aaaaaaaabbbb", route="premium"))
    body = "\n".join(l for l in out.splitlines() if "turn " not in l)
    assert "trace_id" not in body


def test_the_fields_that_say_what_happened_come_first():
    """Alphabetised, `charts` led and `slices` — the number you want — was buried."""
    out = _emit(_record("positioning_gathered", node="analyst_positioning",
                        charts=["Position", "Quarterly"], slices=4, route="premium"))
    body = out[out.index("route="):]
    assert body.index("route=") < body.index("slices=") < body.index("charts=")


def test_a_list_reads_as_a_list_not_as_json():
    out = _emit(_record("charts_from_plan", node="p", charts=["Position", "Quarterly"]))
    assert "Position, Quarterly" in out
    assert '["Position"' not in out


def test_columns_line_up_between_two_events_of_different_name_lengths():
    """Alignment cannot be computed across records, so it is declared."""
    out = _emit(
        _record("positioning_scope_narrowed", node="analyst_positioning", route="both"),
        _record("depth_floored", node="intent_classifier", route="both"),
    )
    starts = [line.index("route=") for line in out.splitlines() if "route=" in line]
    assert len(starts) == 2 and starts[0] == starts[1]


@pytest.mark.parametrize("level, marker", [
    (logging.INFO, "-"), (logging.WARNING, "!"), (logging.ERROR, "x"),
])
def test_the_level_is_one_glyph_not_eight_characters(level, marker):
    """A column the eye catches, rather than the word "WARNING" on every line."""
    console, buffer = _console()
    handler = EventConsoleHandler(console)
    handler.glyphs = False  # the ASCII set, as on a cp1252 terminal
    handler.emit(_record("an_event", level, node="n"))
    assert f" {marker} an_event" in buffer.getvalue()


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #


def test_a_field_holding_rows_renders_as_a_table():
    out = _emit(_record(
        "positioning_gathered", node="analyst_positioning",
        position=[{"slice": "Property", "sow": 50.8}, {"slice": "Cyber", "sow": 100.0}],
    ))
    assert "slice" in out and "sow" in out
    assert "Property" in out and "50.8" in out
    assert "{'slice'" not in out, "rows must not fall back to a dict repr"


def test_a_long_table_is_capped_and_says_so():
    rows = [{"slice": f"S{i}", "value": i} for i in range(20)]
    out = _emit(_record("breakdown", node="n", rows=rows))
    assert "S0" in out and "S19" not in out
    assert f"{20 - log_console.MAX_ROWS} more" in out


def test_a_list_of_scalars_is_not_mistaken_for_a_table():
    assert log_console.is_rows(["Position", "Quarterly"]) is False
    assert log_console.is_rows([]) is False
    assert log_console.is_rows([{"a": 1}]) is True


# --------------------------------------------------------------------------- #
# Escape hatches
# --------------------------------------------------------------------------- #


def test_plain_style_restores_the_one_line_json():
    """What you want when the log is piped, grepped or diffed."""
    out = _emit(_record("positioning_gathered", node="n", slices=4), plain=True)
    assert '"slices": 4' in out
    assert "core.graph.analyst_subgraph: positioning_gathered" in out


def test_plain_style_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("LOG_STYLE", raising=False)
    assert log_console.plain_style() is False
    monkeypatch.setenv("LOG_STYLE", "plain")
    assert log_console.plain_style() is True


def test_a_record_with_no_structured_fields_still_prints():
    """Third-party and plain `logger.info(...)` calls must not vanish."""
    record = logging.LogRecord("werkzeug", logging.INFO, __file__, 1,
                               "GET /_dash-update-component", (), None)
    console, buffer = _console()
    EventConsoleHandler(console).emit(record)
    assert "GET /_dash-update-component" in buffer.getvalue()


def test_a_plain_message_keeps_its_time_level_and_logger():
    """It lost all three when this path printed a bare string — worse than before."""
    record = logging.LogRecord("core.graph.gpr_subgraph", logging.WARNING, __file__, 1,
                               "GPR chart input rows: 42", (), None)
    console, buffer = _console()
    handler = EventConsoleHandler(console)
    handler.glyphs = False
    handler.emit(record)
    line = buffer.getvalue().splitlines()[0]
    assert ":" in line[:8], "the timestamp column is missing"
    assert " ! " in line, "the level marker is missing"
    assert "gpr_subgraph" in line, "the logger should name the module, not the full path"
    assert "core.graph" not in line, "the shared path prefix is noise on every line"


def test_a_plain_message_lines_up_with_a_structured_event():
    """Half-aligned output is harder to read than none. Same columns for both."""
    console, buffer = _console()
    handler = EventConsoleHandler(console)
    handler.emit(_record("route_selected", node="router", table_family="both"))
    handler.emit(logging.LogRecord("werkzeug", logging.INFO, __file__, 1,
                                   "serving", (), None))
    lines = buffer.getvalue().splitlines()
    assert lines[0].index("router") == lines[1].index("werkzeug")


def test_a_url_in_a_plain_message_is_styled_as_a_url():
    """The reported regression: the startup address stopped looking like a link.

    A pre-styled `Text` is not re-scanned by Rich, so the highlighter never saw
    the URL. The message is handed over unstyled instead.
    """
    buffer = _Buffer()
    console = Console(file=buffer, width=200, height=25, force_terminal=True,
                      no_color=False, color_system="standard", legacy_windows=False)
    record = logging.LogRecord("dash", logging.INFO, __file__, 1,
                               "Dash is running on http://127.0.0.1:8050/", (), None)
    EventConsoleHandler(console).emit(record)
    out = buffer.getvalue()
    # Rich's `repr.url` style — underline + bright blue — wraps the address.
    assert "\x1b[4;94mhttp://127.0.0.1:8050/" in out


def test_plain_style_still_carries_the_time_and_level():
    """A piped log with neither is not much use as a log."""
    out = _emit(_record("positioning_gathered", node="n", slices=4), plain=True)
    assert "INFO" in out
    assert out.strip()[0].isdigit(), "the line should start with a timestamp"


def test_logging_never_raises_into_the_caller():
    """A renderer bug must not take down the turn it was reporting on."""
    class Exploding:
        def __repr__(self):  # noqa: D105 - the point is that it raises
            raise RuntimeError("boom")

    console, _buffer = _console()
    handler = EventConsoleHandler(console)
    handler.handleError = lambda record: None  # swallow, as logging does
    handler.emit(_record("an_event", node="n", bad=Exploding()))


def test_an_exception_still_prints_its_traceback():
    try:
        raise ValueError("unknown column 'SurveyCountry' for flow gpr")
    except ValueError:
        import sys
        record = _record("positioning_failed", logging.ERROR, node="n")
        record.exc_info = sys.exc_info()
    out = _emit(record)
    assert "ValueError" in out and "SurveyCountry" in out
