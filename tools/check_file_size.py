"""Soft file-size guardrail (non-blocking).

Decisions doc #11: warn at ~400 lines so new code is born small and
single-responsibility, WITHOUT blocking the build (the UI/legacy giants are
tracked separately as explicit refactor tickets, not gated here).

Always exits 0 — it only prints offenders. Wire it as a CI *warning* step or a
pre-commit informational hook.

Usage:
    python tools/check_file_size.py            # scan core/ + ui/ + config/
    python tools/check_file_size.py path ...   # scan specific paths
    python tools/check_file_size.py --limit 500
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_LIMIT = 400
DEFAULT_ROOTS = ("core", "ui", "config", "tools")

# Known giants tracked as explicit refactor tickets (decisions #11). Listed so a
# reader knows they're acknowledged, not unnoticed — still printed, never fatal.
KNOWN_TICKETS = {
    "config/valid_values_config.py": "deleted by dynamic registry (step 3)",
    "ui/callbacks.py": "UI-1 refactor ticket (step 7)",
    "ui/components/chatbot.py": "UI-2 refactor ticket (step 7)",
    "ui/boardroom/editor.py": "UI-3 refactor ticket (step 7)",
}


def _count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _iter_py_files(roots: list[str]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        p = Path(root)
        if p.is_file() and p.suffix == ".py":
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_ROOTS))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)

    roots = args.paths or list(DEFAULT_ROOTS)
    offenders = [
        (str(f).replace("\\", "/"), n)
        for f in _iter_py_files(roots)
        if (n := _count_lines(f)) > args.limit and "__pycache__" not in str(f)
    ]
    offenders.sort(key=lambda item: item[1], reverse=True)

    if not offenders:
        print(f"[size] OK — no files over {args.limit} lines.")
        return 0

    print(f"[size] WARNING — {len(offenders)} file(s) over {args.limit} lines:")
    for name, lines in offenders:
        note = KNOWN_TICKETS.get(name)
        suffix = f"  ({note})" if note else ""
        print(f"  {lines:>6}  {name}{suffix}")
    print("[size] non-blocking — new code should be born under the limit.")
    return 0  # never fail the build


if __name__ == "__main__":
    sys.exit(main())
