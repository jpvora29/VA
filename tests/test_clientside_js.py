"""Every clientside callback must be valid JavaScript once Dash has served it.

The bug this exists to prevent, in full, because it is not obvious:

`clientside_callback` takes the function as a Python string. Dash inlines that
string into the page, and the backslash of an escaped quote does NOT survive the
trip — a body containing

    document.querySelector('[id*=\\'"index":' + i + '\\']')

reaches the browser as

    document.querySelector('[id*='"index":' + i + '']')

which is a syntax error. And because Dash puts EVERY inline clientside function
in one `<script>`, one broken body stops the whole block from parsing: every
clientside callback on the page then fails with "Cannot read properties of
undefined (reading 'apply')", including the ones that were fine. A tour that
would not open, a chart toggle that stopped working, and a scroll that never
followed the stream were all the same single stray backslash.

Two checks, cheap enough to run every time:

* no body carries an escaped quote (the hazard itself); and
* every body parses as JavaScript — skipped when `node` is not installed, so the
  suite still runs on a machine without it.
"""
from __future__ import annotations

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

_CLIENTSIDE = re.compile(r'clientside_callback\(\s*"""(.*?)"""', re.S)


def bodies() -> list[tuple[str, int, str]]:
    """(file, ordinal, js) for every inline clientside function in the app."""
    found: list[tuple[str, int, str]] = []
    for path in SOURCES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for i, body in enumerate(_CLIENTSIDE.findall(text)):
            found.append((str(path), i, body))
    return found


def test_there_are_clientside_callbacks_to_check():
    """A guard on the guard: a changed decorator name would silently find none."""
    assert len(bodies()) >= 5


@pytest.mark.parametrize("source,index,js", bodies())
def test_no_clientside_body_escapes_a_quote(source: str, index: int, js: str):
    """Dash drops the backslash, so an escaped quote becomes a syntax error."""
    offenders = [
        line.strip()
        for line in js.splitlines()
        if "\\'" in line or '\\"' in line
    ]
    assert not offenders, (
        f"{source} clientside #{index} escapes a quote; Dash will drop the "
        f"backslash and break the page: {offenders[:2]}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("source,index,js", bodies())
def test_every_clientside_body_is_valid_javascript(
    source: str, index: int, js: str, tmp_path: Path
):
    script = tmp_path / f"cb{index}.js"
    script.write_text(f"const fn = {js.strip()};\n", encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(script)], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"{source} clientside #{index} is not valid JavaScript:\n{result.stderr}"
    )
