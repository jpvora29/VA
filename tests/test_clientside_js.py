"""Every clientside callback must be valid JavaScript once Dash has served it.

The bug this exists to prevent, in full, because it is not obvious:

`clientside_callback` takes the function as a Python string, and **Python gets
first go at the escapes**. A body containing

    document.querySelector('[id*=\\'"index":' + i + '\\']')

loses the backslashes on the way through the literal and reaches the browser as

    document.querySelector('[id*='"index":' + i + '']')

which is a syntax error. And because Dash puts EVERY inline clientside function
in one `<script>`, one broken body stops the whole block from parsing: every
clientside callback on the page then fails with "Cannot read properties of
undefined (reading 'apply')", including the ones that were fine. A tour that
would not open, a chart toggle that stopped working, and a scroll that never
followed the stream were all the same single stray backslash.

**The hole this test used to have**, found when a second body hit the same trap
from a different direction: it read the JS as WRITTEN IN THE FILE, where the
escapes are still intact and everything parses. Python's mangling happens after
that, and the check never saw it. So when the HTML-to-Markdown serialiser behind
in-place answer editing wrote

    lines.join('\\n').replace(/\\n{3,}/g, '\\n\\n')

the file looked fine, `node --check` passed, and the page shipped with a string
literal split across two real lines — every clientside callback on the chat page
dead, and a green suite. The bodies below are therefore `ast.literal_eval`'d
first: this checks what Dash is HANDED, not what the author typed.

Three checks, cheap enough to run every time:

* no body carries an escaped quote (the original hazard);
* a body that needs a backslash is written as a raw string, which is the fix;
* every body parses as JavaScript AFTER Python has evaluated the literal —
  skipped when `node` is not installed, so the suite still runs without it.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# The modules that register clientside callbacks. A new one belongs on this list.
SOURCES = (
    Path("ui/callbacks.py"),
    Path("ui/boardroom/callbacks.py"),
    Path("ui/decisions/callbacks.py"),
)

# The WHOLE string literal, prefix included, so it can be evaluated the way
# Python will. `r"""` has to be part of the match or a raw body is invisible.
_CLIENTSIDE = re.compile(r'clientside_callback\(\s*((?:[rR]?)"{3}.*?"{3})', re.S)


def bodies() -> list[tuple[str, int, str, str]]:
    """(file, ordinal, source-as-written, js-as-Python-evaluates-it)."""
    found: list[tuple[str, int, str, str]] = []
    for path in SOURCES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for i, literal in enumerate(_CLIENTSIDE.findall(text)):
            found.append((str(path), i, literal, ast.literal_eval(literal)))
    return found


# Whole function bodies as pytest ids run to thousands of characters and bury the
# assertion message; the file and ordinal are what identifies the offender.
CASES = bodies()
IDS = [f"{Path(source).name}#{index}" for source, index, _, _ in CASES]


def test_there_are_clientside_callbacks_to_check():
    """A guard on the guard: a changed decorator name would silently find none."""
    assert len(CASES) >= 5


@pytest.mark.parametrize("source,index,literal,js", CASES, ids=IDS)
def test_no_clientside_body_escapes_a_quote(source: str, index: int, literal: str, js: str):
    """An escaped quote does not survive the trip into the page."""
    offenders = [
        line.strip()
        for line in literal.splitlines()
        if "\\'" in line or '\\"' in line
    ]
    assert not offenders, (
        f"{source} clientside #{index} escapes a quote; the backslash will be "
        f"dropped and break the page: {offenders[:2]}"
    )


@pytest.mark.parametrize("source,index,literal,js", CASES, ids=IDS)
def test_a_body_that_needs_a_backslash_is_written_raw(
    source: str, index: int, literal: str, js: str
):
    """A raw string is what keeps Python's hands off a JS escape.

    Without it, `'\\n'` in the JS is a real line break by the time Dash sees it,
    which splits the string literal across two lines and kills the page.
    """
    needs_raw = "\\" in literal and not literal.lstrip().lower().startswith("r")
    assert not needs_raw, (
        f"{source} clientside #{index} contains a backslash but is not a raw "
        "string; prefix the triple-quoted body with r so the escape survives Python"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("source,index,literal,js", CASES, ids=IDS)
def test_every_clientside_body_is_valid_javascript(
    source: str, index: int, literal: str, js: str, tmp_path: Path
):
    """Checked on the EVALUATED string — what Dash is handed, not what was typed."""
    script = tmp_path / f"cb{index}.js"
    script.write_text(f"const fn = {js.strip()};\n", encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(script)], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"{source} clientside #{index} is not valid JavaScript:\n{result.stderr}"
    )
