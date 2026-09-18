"""Rendering structured log events for a human reading a terminal.

`core.observability.log_event` emits one event with a bag of typed fields. Until
now the console printed that bag as `json.dumps(..., sort_keys=True)` appended to
the message, which Rich then wrapped to the terminal width:

    [09/18/26 17:17:36] INFO  core.graph.analyst_subgraph: positioning_gathered
                              {"charts": ["Position", "Quarterly", "What moved",
                              "Premium"], "dimension": "Product_Line",
                              "missing": [], "node": "analyst_positioning", ...

Every complaint about following a run is visible in those four lines. The fields
are alphabetised, so `charts` leads and `slices` — the number you actually want —
is somewhere in the middle. The module path is repeated on every line and the
node is buried inside the payload. Turns run into each other with no boundary, so
a re-run's output is indistinguishable from the previous one's tail. And a field
holding rows has no shape at all.

So this module renders events instead of stringifying them:

  * **A rule per turn.** `trace_id` is bound for the life of one turn
    (`core.observability.turn_context`), so a change in it is a turn boundary and
    gets a titled rule. Two runs can never be read as one again.
  * **Aligned columns.** time | level | event | node | fields. The event and the
    node are the two things you scan for, so they get their own columns rather
    than being buried in a payload.
  * **Ordered fields.** The fields that say what happened come first
    (`_LEAD_FIELDS`); ids that are already in the rule are dropped entirely.
  * **Tables where there is a table.** A field holding a list of dicts is rows,
    and rows render as a table.

`LOG_STYLE=plain` restores the old single-line JSON, which is what you want when
piping to a file or grepping. `LOG_FORMAT=json` (handled in
`core.observability`) is unaffected — that path is for machines and this one is
not.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rich.console import Console, Group, RenderableType
from rich.highlighter import ReprHighlighter
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from rich.traceback import Traceback

#: Rich's own highlighter, so a URL, a number or a quoted string in a plain
#: message still reads as what it is — the Dash startup banner's address
#: included.
_HIGHLIGHTER = ReprHighlighter()

#: Fields that say WHAT HAPPENED, in the order a reader wants them. Anything not
#: named here keeps its emitted order after these — insertion order carries the
#: call site's own sense of importance, which alphabetising destroyed.
_LEAD_FIELDS: Tuple[str, ...] = (
    "reason", "route", "flow", "operation", "intent", "analysis_depth",
    "dimension", "subject", "slices", "count", "rows", "error",
)

#: Fields already shown in the turn rule, or too noisy to repeat per line.
_RULE_FIELDS: Tuple[str, ...] = ("trace_id", "thread_id", "request_id", "event")

#: Level -> (style, marker). The marker is one glyph so the level costs a column
#: of width rather than eight ("WARNING").
_LEVELS: Mapping[int, Tuple[str, str]] = {
    logging.DEBUG: ("dim", "·"),
    logging.INFO: ("cyan", "•"),
    logging.WARNING: ("yellow", "▲"),
    logging.ERROR: ("bold red", "✕"),
    logging.CRITICAL: ("bold white on red", "✕"),
}

#: The same markers for a console that cannot encode the first set. A Windows
#: terminal on cp1252 renders "•" as "?", which is worse than "-": the point of
#: the column is that the eye catches a level, and a question mark at every level
#: catches nothing. Chosen once at import from the stream's own encoding.
_ASCII_LEVELS: Mapping[int, Tuple[str, str]] = {
    logging.DEBUG: ("dim", "."),
    logging.INFO: ("cyan", "-"),
    logging.WARNING: ("yellow", "!"),
    logging.ERROR: ("bold red", "x"),
    logging.CRITICAL: ("bold white on red", "x"),
}


def _encodable(text: str, encoding: str) -> bool:
    try:
        text.encode(encoding or "ascii")
        return True
    except (LookupError, UnicodeEncodeError):
        return False


def supports_glyphs(console: Console) -> bool:
    """Whether this console can print the marker glyphs without mangling them."""
    encoding = getattr(getattr(console, "file", None), "encoding", "") or ""
    return _encodable("•▲✕·—", encoding)

#: Fixed widths for the leading columns, so they line up DOWN the page.
#:
#: Each record renders its own grid — a log has no idea what is coming next — so
#: alignment cannot be computed, it has to be declared. Without these the event
#: and node columns are as wide as whatever that one line happened to hold, and
#: the eye has nothing straight to run down.
TIME_WIDTH = 8       # "17:19:59"
MARKER_WIDTH = 1
EVENT_WIDTH = 27     # "positioning_scope_narrowed"
NODE_WIDTH = 20      # "analyst_positioning"

#: Where the fields column starts, and so how far a continuation or a nested
#: table is indented to sit under it. One space between each column.
GUTTER = TIME_WIDTH + MARKER_WIDTH + EVENT_WIDTH + NODE_WIDTH + 4

#: Longest a single inline value is printed before it is truncated. A field that
#: needs more than this is not being read on a log line anyway.
MAX_VALUE = 72

#: Most rows of a tabular field to print. A log line is a signal that something
#: happened, not the result set.
MAX_ROWS = 8


def style_for(level: int, *, glyphs: bool = True) -> Tuple[str, str]:
    """The style and marker for a level, falling back to INFO's."""
    levels = _LEVELS if glyphs else _ASCII_LEVELS
    for threshold in sorted(levels, reverse=True):
        if level >= threshold:
            return levels[threshold]
    return levels[logging.INFO]


def is_rows(value: Any) -> bool:
    """Whether a field holds tabular data — a non-empty list of mappings."""
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and all(isinstance(item, Mapping) for item in value)
    )


def order_fields(fields: Mapping[str, Any]) -> List[Tuple[str, Any]]:
    """The fields worth printing, most useful first, ids removed."""
    shown = {k: v for k, v in fields.items() if k not in _RULE_FIELDS}
    lead = [(k, shown.pop(k)) for k in _LEAD_FIELDS if k in shown]
    return lead + list(shown.items())


def render_value(value: Any, *, empty: str = "-") -> str:
    """One field value as a short string. Lists become comma lists, not JSON."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (list, tuple)):
        text = ", ".join(str(item) for item in value) if value else empty
    elif isinstance(value, Mapping):
        text = ", ".join(f"{k}={v}" for k, v in value.items()) if value else empty
    elif value is None:
        text = empty
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= MAX_VALUE else text[: MAX_VALUE - 3] + "..."


def field_text(fields: Sequence[Tuple[str, Any]], *, empty: str = "-") -> Text:
    """`key=value  key=value` with the keys dimmed, so the values read first."""
    out = Text()
    for index, (key, value) in enumerate(fields):
        if index:
            out.append("  ")
        out.append(f"{key}=", style="dim")
        out.append(render_value(value, empty=empty))
    return out


def rows_table(name: str, rows: Sequence[Mapping[str, Any]], *, empty: str = "-") -> Table:
    """A tabular field as an actual table, capped at `MAX_ROWS`."""
    columns: List[str] = []
    for row in rows:
        for key in row:
            if str(key) not in columns:
                columns.append(str(key))
    table = Table(
        title=name, title_justify="left", title_style="dim italic",
        box=None, pad_edge=False, show_edge=False, padding=(0, 2, 0, 0),
    )
    for column in columns:
        table.add_column(column, style="white", header_style="dim")
    for row in rows[:MAX_ROWS]:
        table.add_row(*(render_value(row.get(c), empty=empty) for c in columns))
    if len(rows) > MAX_ROWS:
        table.caption = f"... {len(rows) - MAX_ROWS} more"
        table.caption_style = "dim italic"
    return table


def event_line(record: logging.LogRecord, fields: Mapping[str, Any],
               *, glyphs: bool = True) -> RenderableType:
    """One structured event: time, level, event name, node, then its fields."""
    style, marker = style_for(record.levelno, glyphs=glyphs)
    empty = "—" if glyphs else "-"
    ordered = order_fields(fields)
    inline = [(k, v) for k, v in ordered if not is_rows(v)]
    tabular = [(k, v) for k, v in ordered if is_rows(v)]

    grid = Table.grid(padding=(0, 1))
    grid.add_column(style="dim", width=TIME_WIDTH, no_wrap=True)
    grid.add_column(style=style, width=MARKER_WIDTH, no_wrap=True)
    grid.add_column(style=f"bold {style}", width=EVENT_WIDTH,
                    no_wrap=True, overflow="ellipsis")
    grid.add_column(style="magenta", width=NODE_WIDTH,
                    no_wrap=True, overflow="ellipsis")
    grid.add_column(overflow="fold")
    grid.add_row(
        logging.Formatter("%(asctime)s", "%H:%M:%S").format(record),
        marker,
        str(fields.get("event") or record.getMessage()),
        str(fields.get("node") or ""),
        field_text([(k, v) for k, v in inline if k != "node"], empty=empty),
    )
    if not tabular:
        return grid
    # Nested tables sit under the fields column, not against the left margin, so
    # the eye reads them as belonging to the event above rather than as a new one.
    return Group(grid, *(
        Padding(rows_table(n, r, empty=empty), (0, 0, 0, GUTTER))
        for n, r in tabular
    ))


def short_name(name: str) -> str:
    """"core.graph.analyst_subgraph" -> "analyst_subgraph".

    The module a line came from, without the path that is the same on every line.
    """
    return str(name or "").rsplit(".", 1)[-1]


def message_line(record: logging.LogRecord, *, glyphs: bool = True) -> RenderableType:
    """A record with no structured fields — a plain `logger.info(...)`, or a
    third-party library's line — in the SAME columns as an event.

    It has to be the same columns. A log where half the lines are aligned and
    half are bare strings is harder to read than one where none of them are, and
    these lines were losing their timestamp and level entirely.

    The message keeps Rich's highlighter, which is what styles a URL as a URL —
    the Dash startup banner's address stopped looking like a link when this path
    printed a pre-styled `Text` instead, because a styled Text is not re-scanned.
    """
    style, marker = style_for(record.levelno, glyphs=glyphs)
    grid = Table.grid(padding=(0, 1))
    grid.add_column(style="dim", width=TIME_WIDTH, no_wrap=True)
    grid.add_column(style=style, width=MARKER_WIDTH, no_wrap=True)
    grid.add_column(width=EVENT_WIDTH, no_wrap=True, overflow="ellipsis")
    grid.add_column(style="magenta", width=NODE_WIDTH,
                    no_wrap=True, overflow="ellipsis")
    grid.add_column(overflow="fold")
    grid.add_row(
        logging.Formatter("%(asctime)s", "%H:%M:%S").format(record),
        marker,
        "",
        short_name(record.name),
        _HIGHLIGHTER(Text(record.getMessage())),
    )
    return grid


def plain_line(record: logging.LogRecord, fields: Mapping[str, Any]) -> str:
    """The previous one-line JSON rendering, for piping and grepping."""
    message = record.getMessage()
    extra = {k: v for k, v in fields.items() if k != "event"}
    if extra:
        message = f"{message} {json.dumps(extra, default=str, sort_keys=True)}"
    return f"{record.name}: {message}"


class EventConsoleHandler(logging.Handler):
    """Print log records as Rich renderables, one rule per turn.

    Holds the last `trace_id` it saw so a turn boundary can be drawn. That is the
    handler's only state, and it is per-process: two turns interleaved from two
    threads would draw two rules, which is the honest rendering of what happened.
    """

    def __init__(self, console: Console, *, plain: bool = False) -> None:
        super().__init__()
        self.console = console
        self.plain = plain
        self.glyphs = supports_glyphs(console)
        self._trace: str = ""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            fields: Dict[str, Any] = dict(getattr(record, "event_fields", {}) or {})
            if self.plain:
                self._emit_plain(record, fields)
            elif fields:
                self._rule_for(fields)
                self.console.print(event_line(record, fields, glyphs=self.glyphs))
            else:
                self.console.print(message_line(record, glyphs=self.glyphs))
            if record.exc_info:
                self.console.print(
                    Traceback.from_exception(*record.exc_info, show_locals=False)
                )
        except Exception:  # noqa: BLE001 - logging must never raise into the caller
            self.handleError(record)

    def _emit_plain(self, record: logging.LogRecord, fields: Mapping[str, Any]) -> None:
        """One greppable line: time, level, logger, message, JSON payload.

        Carries the timestamp and level that the rendered form puts in columns —
        a piped log that has neither is not much use as a log.
        """
        stamp = logging.Formatter("%(asctime)s", "%H:%M:%S").format(record)
        body = plain_line(record, fields) if fields else f"{record.name}: {record.getMessage()}"
        self.console.print(f"{stamp} {record.levelname:<8} {body}", highlight=False)

    def _rule_for(self, fields: Mapping[str, Any]) -> None:
        """Draw a rule when this event belongs to a different turn than the last."""
        trace = str(fields.get("trace_id") or "")
        if not trace or trace == self._trace:
            return
        self._trace = trace
        thread = str(fields.get("thread_id") or "")
        join = " - " if not self.glyphs else " · "
        title = f"turn {trace[:8]}" + (f"{join}{thread}" if thread else "")
        self.console.rule(Text(title, style="bold blue"), style="blue")


def plain_style() -> bool:
    """Whether the console should fall back to one-line JSON (`LOG_STYLE=plain`)."""
    return os.getenv("LOG_STYLE", "rich").strip().lower() == "plain"
