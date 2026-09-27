"""Direction on the page: ▲ green for a rise, ▼ red for a fall.

A movement written as "+14.2%" or "-$20" makes the reader parse a sign to learn
the one thing that matters about it. This marks every signed change — and every
▲/▼ the writer already used — as a coloured span, so direction is seen before it
is read. Pure text in, Markdown-with-spans out; nothing is reworded, a sign only
becomes its arrow.

The answer is rendered with raw HTML allowed so the spans survive, which is why
every `<` in the source is escaped first: the only HTML in the result is the
spans this module writes.
"""
from __future__ import annotations

import re

#: "▲ 14.2%", "▼$1.3M", "▲ 3.0pp", "▲ 2 places".
_ARROWED = re.compile(r"([▲▼])\s?(\$?\d[\d,]*(?:\.\d+)?\s?(?:%|pp|bps|[kKmMbB]n?\b|M\b)?)")

#: "+14.2%", "-$20", "−3.1pp" — a sign attached to a figure, not a range
#: ("2024-2025") or a list dash ("- Property"): the sign must not follow a word
#: character or a digit, and must be followed directly by the figure.
_SIGNED = re.compile(
    r"(?<![\w.$])([+\-−])(\$?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|pp|bps)|[kKmMbB]n?\b|M\b)?)"
)


def _span(direction: str, figure: str) -> str:
    arrow = "▲" if direction == "up" else "▼"
    return f'<span class="delta delta-{direction}">{arrow} {figure}</span>'


def mark_deltas(markdown: str) -> str:
    """Markdown with each signed change wrapped in a coloured, arrowed span."""
    if not markdown:
        return markdown or ""
    text = markdown.replace("<", "&lt;")
    lines = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        # A list marker ("- ", "* ") or a table separator ("|---:|") is
        # structure, not a fall; only the text after it is scanned.
        if re.match(r"^\|?\s*:?-{2,}", stripped):
            lines.append(line)
            continue
        prefix = ""
        match = re.match(r"^(\s*(?:[-*+]|\d+[.)])\s+)", line)
        if match:
            prefix, line = match.group(1), line[match.end():]
        line = _ARROWED.sub(lambda m: _span("up" if m.group(1) == "▲" else "down", m.group(2)), line)
        line = _SIGNED.sub(lambda m: _span("up" if m.group(1) == "+" else "down", m.group(2)), line)
        lines.append(prefix + line)
    return "\n".join(lines)
