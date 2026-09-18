"""The startup banner and the end-of-turn token summary.

Two bookends for a run, kept apart from `log_console` because neither is a log
RECORD — they are written once, directly, at moments the application chooses,
and mixing them into the handler would make the handler responsible for knowing
when a run starts and a turn ends.

The banner answers the question you actually have when a server comes up: *which
model is this going to use?* That was previously answerable only by reading
`.env` and then reading `core/llm/clients.py` to learn which variable wins.

The summary answers the one you have when it finishes: *what did that cost?* The
numbers were already accumulated per turn (`core.observability`); they just
arrived squashed into a log line as `token_total=input_tokens=6100, ...`.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text

#: A 5-row block font, in the letters "VIRTUAL ANALYST" needs. Hand-cut rather
#: than pulled from a dependency: it is fifteen letters once, and a figlet
#: package would be a runtime dependency for a decoration.
_FONT: Mapping[str, Sequence[str]] = {
    "V": ("#   #", "#   #", "#   #", " # # ", "  #  "),
    "I": ("#####", "  #  ", "  #  ", "  #  ", "#####"),
    "R": ("#### ", "#   #", "#### ", "#  # ", "#   #"),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  "),
    "U": ("#   #", "#   #", "#   #", "#   #", " ### "),
    "A": (" ### ", "#   #", "#####", "#   #", "#   #"),
    "L": ("#    ", "#    ", "#    ", "#    ", "#####"),
    "N": ("#   #", "##  #", "# # #", "#  ##", "#   #"),
    "Y": ("#   #", " # # ", "  #  ", "  #  ", "  #  "),
    "S": (" ####", "#    ", " ### ", "    #", "#### "),
    " ": ("  ", "  ", "  ", "  ", "  "),
}

_ROWS = 5

#: What the font is drawn with. The shapes are identical either way, so a console
#: that cannot encode a block character still gets a readable banner rather than
#: a screen of "?" — the same rule the level markers follow.
BLOCK = "█"
ASCII_INK = "#"


#: Columns between letters, and the left margin. Two, because at one the stems of
#: adjacent letters touch and "AL" reads as a single glyph.
_KERN = "  "
_MARGIN = " "


def render_word(word: str, *, ink: str = ASCII_INK) -> list[str]:
    """One word as `_ROWS` lines of block letters. Unknown letters are skipped."""
    letters = [_FONT[ch] for ch in word.upper() if ch in _FONT]
    if not letters:
        return []
    return [
        (_MARGIN + _KERN.join(letter[row] for letter in letters)).replace("#", ink)
        for row in range(_ROWS)
    ]


def banner(
    *,
    title: str = "VIRTUAL",
    subtitle: str = "ANALYST",
    ink: str = ASCII_INK,
    tagline: str = "",
) -> RenderableType:
    """The wordmark, stacked so it fits a normal terminal.

    Two stacked words rather than one long one: "VIRTUAL ANALYST" on a single
    line is ninety columns of block letters, which wraps on exactly the terminals
    people actually use.
    """
    lines = [*render_word(title, ink=ink), *render_word(subtitle, ink=ink)]
    art = Text("\n".join(lines), style="bold cyan")
    if not tagline:
        return art
    return Group(art, Text(tagline, style="dim"))


def model_table(tiers: Iterable[Mapping[str, str]]) -> Table:
    """Which model each tier of work will use, and how it is configured."""
    table = Table(
        box=None, pad_edge=False, show_edge=False, padding=(0, 3, 0, 0),
        title="models", title_justify="left", title_style="dim italic",
    )
    table.add_column("tier", style="magenta")
    table.add_column("model", style="bold")
    table.add_column("effort", style="cyan")
    table.add_column("temp", style="dim")
    for row in tiers:
        table.add_row(
            str(row.get("tier", "")),
            str(row.get("model", "")),
            str(row.get("effort", "") or "-"),
            str(row.get("temperature", "") or "-"),
        )
    return table


def _thousands(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value or "-")


def token_table(total: Mapping[str, Any], by_agent: Mapping[str, Mapping[str, Any]] | None = None) -> Table:
    """Input, output and total tokens for a turn, with the per-agent split.

    Input and output are shown separately because they do not cost the same and
    do not move for the same reasons: output grows with how much the answer says,
    input with how much context every node was handed.
    """
    table = Table(
        box=None, pad_edge=False, show_edge=False, padding=(0, 3, 0, 0),
        title="tokens", title_justify="left", title_style="dim italic",
    )
    table.add_column("", style="magenta")
    table.add_column("input", justify="right")
    table.add_column("output", justify="right")
    table.add_column("total", justify="right", style="bold")
    table.add_column("cached", justify="right", style="dim")

    for name, bucket in sorted((by_agent or {}).items()):
        table.add_row(
            name,
            _thousands(bucket.get("input_tokens")),
            _thousands(bucket.get("output_tokens")),
            _thousands(bucket.get("total_tokens")),
            _thousands(bucket.get("cached_tokens")),
        )
    table.add_section()
    table.add_row(
        "TURN TOTAL",
        _thousands(total.get("input_tokens")),
        _thousands(total.get("output_tokens")),
        _thousands(total.get("total_tokens")),
        _thousands(total.get("cached_tokens")),
        style="bold",
    )
    return table


def print_banner(
    console: Console,
    *,
    tiers: Optional[Iterable[Mapping[str, str]]] = None,
    ink: str = ASCII_INK,
    tagline: str = "",
) -> None:
    """Write the wordmark and the model table to `console`. Never raises."""
    try:
        console.print()
        console.print(banner(ink=ink, tagline=tagline))
        console.print()
        if tiers is not None:
            console.print(model_table(tiers))
            console.print()
    except Exception:  # noqa: BLE001 - a decoration must never stop a boot
        pass
