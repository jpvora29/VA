"""QBR deck self-check — run on the machine that serves app.py, against its real data.

    python tools/qbr_selfcheck.py "Carrier Name" "Country" [2025] [path\\to\\deck.pptx]

Part 1 says whether this machine has the 2026-11-26 deck fixes loaded at all (code synced
by OneDrive/git but an app.py started before the sync still runs the old code). Part 2
runs each fix on the real data for one carrier and market. Part 3 (optional) audits a
deck the app generated. Read-only: it writes nothing.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check_code() -> bool:
    """Part 1: are the fixes in the code this Python would load?"""
    from studio import compute as C
    from studio.template_fill import bindings, fill, kpi_band, lc_page

    markers = {
        "LC page keeps every top-5 line (lc_page.select_lines)": hasattr(
            lc_page, "select_lines"
        ),
        "Rank axis never widened (RankPoint.row)": hasattr(lc_page.RankPoint, "row"),
        "LC labels placed as boxes (fill._place_rank_labels)": hasattr(
            fill, "_place_rank_labels"
        ),
        "Peer GWP = peer set (compute.peer_set_totals)": hasattr(C, "peer_set_totals"),
        "Template product word rewritten (bindings.product_label_vocab)": hasattr(
            bindings, "product_label_vocab"
        ),
        "KPI bands to 1 decimal (kpi_band.premium_decimals)": hasattr(
            kpi_band, "premium_decimals"
        ),
    }
    try:
        head = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "log",
                "-1",
                "--format=%h %ad %s",
                "--date=format:%m-%d %H:%M",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — git is optional here
        head = "(git not available)"
    print(f"\n== 1. Code on this machine  (git HEAD: {head})")
    for name, ok in markers.items():
        print(f"   [{'OK' if ok else 'MISSING'}] {name}")
    print(
        "   Restart app.py after these all read OK — a running app keeps the code it started with."
    )
    return all(markers.values())


def check_data(carrier: str, country: str, year: int) -> None:
    """Part 2: each fix, on this machine's real data."""
    from dataclasses import replace

    from studio import compute as C
    from studio.compute import compute_overall
    from studio.template_fill import lc_page as L
    from studio.template_fill.bindings import (
        peer_pin,
        product_label_vocab,
        product_vocab,
        scope_to_country,
    )

    print(f"\n== 2. Real data: {carrier} / {country} / {year}")
    run = compute_overall(
        filters={"carrier": carrier, "country": [country], "year": year}
    )
    run = replace(run, scope_countries=(country,))
    scoped = scope_to_country(run, country)
    filters = {**L._reporting_filters(scoped), "Country": country}

    rows = C.product_breakdown_rows(
        run.flow, filters, run.engine, run.subject, top=None
    )
    top5 = sorted(r["name"] for r in rows if r.get("rank") and r["rank"] <= 5)
    points = L.rank_points(scoped, filters)
    shown = {p.name for p in points}
    print(f"   LC page lines ranked top 5 : {top5}")
    print(f"   LC page points             : {[(p.label, p.rank) for p in points]}")
    missing = [n for n in top5 if n not in shown]
    print(
        f"   [{'OK' if not missing else 'PROBLEM'}] top-5 lines missing from LC page: {missing}"
    )

    peers = C.peer_set_totals(
        run.flow, filters, run.engine, run.subject, peer_pin(scoped)
    )
    print(
        f"   Peer set benchmark         : {None if peers is None else round(peers['current'])}"
        f"  ({'blank in the deck' if peers is None else str(peers['n_peers']) + ' peers'})"
    )

    vocab = product_label_vocab(run)
    print(f"   Carrier's own lines        : {list(product_vocab(run))}")
    print(
        f"   [{'OK' if 'Marine' in vocab else 'PROBLEM'}] 'Marine' (template title word) "
        f"in rewrite vocabulary"
    )


_DUMMY = re.compile(
    r"\$x|x\.x|\bx{2,3}[MBmb]?\b|\bxyz\b|Country\s*\(\d\)|Marine Feedback"
)


def check_deck(path: str) -> None:
    """Part 3: a deck the app generated — template leftovers, Peer cells, LC axis."""
    from pptx import Presentation

    print(f"\n== 3. Deck: {path}")
    prs = Presentation(path)
    for n, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            texts = [shape.text_frame.text] if shape.has_text_frame else []
            if getattr(shape, "has_table", False) and shape.has_table:
                texts += [" | ".join(c.text for c in r.cells) for r in shape.table.rows]
            for t in texts:
                if _DUMMY.search(t):
                    print(f"   [PROBLEM] slide {n}: template leftover: {t[:90]!r}")
                if re.match(r"\s*Peer", t) and "|" in t:
                    print(f"   [info]    slide {n}: {t[:90]!r}")
            if getattr(shape, "has_chart", False) and "SCATTER" in str(
                shape.chart.chart_type
            ):
                ch = shape.chart
                try:
                    labels = [
                        p.data_label.text_frame.text
                        for p in ch.plots[0].series[0].points
                    ]
                    print(
                        f"   [info]    slide {n}: LC panel axis max={ch.value_axis.maximum_scale} "
                        f"labels={labels}"
                    )
                except Exception:  # noqa: BLE001 — the growth chart is a scatter too
                    pass


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        print(__doc__)
        sys.exit(2)
    carrier, country = argv[1], argv[2]
    year = int(argv[3]) if len(argv) > 3 and argv[3].isdigit() else 2025
    deck = next((a for a in argv[3:] if a.lower().endswith(".pptx")), None)
    if check_code():
        check_data(carrier, country, year)
    else:
        print(
            "\n   The fixes are not in this machine's code yet — sync/pull first, then re-run."
        )
    if deck:
        check_deck(deck)


if __name__ == "__main__":
    main(sys.argv)
