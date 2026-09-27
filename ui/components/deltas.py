"""Direction on the page: ▲ green for a rise, ▼ red for a fall.

A movement written as "+14.2%" or "-$20" makes the reader parse a sign to learn
the one thing that matters about it. This marks every signed change — and EVERY
▲/▼ the writer used, whatever follows it — as a coloured span, so direction is
seen before it is read. Pure text in, Markdown-with-spans out; nothing is
reworded, a sign only becomes its arrow.

The answer is rendered with raw HTML allowed so the spans survive, which is why
every `<` in the source is escaped first: the only HTML in the result is the
spans this module writes.
"""
from __future__ import annotations

import re

_FIGURE = r"\$?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|pp|bps|points?\b|places?\b)|[kKmMbB]n?\b|M\b)?"

#: An arrow, an optional sign the writer doubled it with, and — optionally — the
#: figure it belongs to. "▲ 14.2%", "▼$1.3M", "▲ +3.0pp", or a bare "▲".
_ARROWED = re.compile(r"([▲▼△▽↑↓])(?:\s?[+\-−]?\s?(" + _FIGURE + r"))?")

#: "+14.2%", "-$20", "−3.1pp" — a sign attached to a figure, not a range
#: ("2024-2025") or a list dash ("- Property"): the sign must not follow a word
#: character or a digit, and must be followed directly by the figure.
_SIGNED = re.compile(r"(?<![\w.$])([+\-−])(" + _FIGURE + r")")

_UP = {"▲", "△", "↑", "+"}


def delta_span(direction: str, figure: str = "") -> str:
    """One coloured change: "▲ 14.2%" in green, "▼ $20" in red."""
    arrow = "▲" if direction == "up" else "▼"
    body = f"{arrow} {figure}".strip()
    return f'<span class="delta delta-{direction}">{body}</span>'


def _arrowed(match: "re.Match[str]") -> str:
    return delta_span("up" if match.group(1) in _UP else "down", match.group(2) or "")


def _signed(match: "re.Match[str]") -> str:
    return delta_span("up" if match.group(1) in _UP else "down", match.group(2))


def mark_line(line: str) -> str:
    """One line of prose with its changes marked (no Markdown structure handling)."""
    line = _ARROWED.sub(_arrowed, line)
    return _SIGNED.sub(_signed, line)


def mark_deltas(markdown: str) -> str:
    """Markdown with each change wrapped in a coloured, arrowed span."""
    if not markdown:
        return markdown or ""
    text = markdown.replace("<", "&lt;")
    lines = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        # A table separator ("|---:|") is structure, not a fall.
        if re.match(r"^\|?\s*:?-{2,}", stripped):
            lines.append(line)
            continue
        # A list marker ("- ", "* ", "1. ") is structure too; only the text
        # after it is scanned.
        prefix = ""
        match = re.match(r"^(\s*(?:[-*+]|\d+[.)])\s+)", line)
        if match:
            prefix, line = match.group(1), line[match.end():]
        lines.append(prefix + mark_line(line))
    return "\n".join(lines)
