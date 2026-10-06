"""Answer prose as ONE HTML block, so its coloured ▲/▼ survive the renderer.

`ui.components.deltas` wraps every change in ``<span class="delta delta-up">``.
Inside `dcc.Markdown` those spans never reached the page: Dash's Markdown is an
old react-markdown that renders INLINE HTML tag by tag, so an opening ``<span>``
and its closing ``</span>`` became two separate fragments, the browser dropped
both, and the arrow showed in the text's own colour. Block-level HTML is the one
form it injects whole. So the Markdown is rendered to HTML here, on the server,
and handed over as a single ``<div>`` block.

Safe by construction: `mark_deltas` escapes every ``<`` in the writer's text
before rendering, so the only tags on the page are the ones markdown-it and the
delta marker produce; markdown-it also refuses ``javascript:`` links.
"""
from __future__ import annotations

from typing import Any

from dash import dcc
from markdown_it import MarkdownIt

from ui.components.deltas import mark_deltas, mark_line

#: CommonMark plus the GFM tables and strikethrough the writer uses. Raw HTML is
#: allowed only so the delta spans pass through — the writer's own `<` is
#: already escaped by `mark_deltas`.
_RENDERER = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])


def to_html_block(markdown: str, *, inline: bool = False) -> str:
    """Markdown (deltas marked) as one HTML block react-markdown injects whole.

    The block opens and closes on lines of its own with no blank line inside —
    a CommonMark HTML block ends at the first blank line, and a block spanning
    several lines is drawn as a ``div`` rather than a ``span``.
    """
    marked = mark_line(markdown.replace("<", "&lt;")) if inline else mark_deltas(markdown)
    html = _RENDERER.render(marked or "").strip()
    body = " ".join(part.strip() for part in html.splitlines() if part.strip())
    return f'<div class="md-block">\n{body}\n</div>'


def answer_markdown(text: str, class_name: str = "", *, inline: bool = False) -> Any:
    """A `dcc.Markdown` showing ``text`` with its changes coloured."""
    return dcc.Markdown(to_html_block(text or "", inline=inline),
                        className=class_name or None, dangerously_allow_html=True)
