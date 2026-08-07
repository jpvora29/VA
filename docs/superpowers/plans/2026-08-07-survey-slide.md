# Carrier Survey Slide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append `template/survey_template.pptx` to each country's block of the QBR deck when Setup's DATA BASIS is "Premium + survey", filled with real survey scores, cells coloured by change vs the prior year, and a section-axis ribbon chart of the carrier against its peers.

**Architecture:** A new `studio/template_fill/survey/` subpackage follows the existing `gwp_page` / `lc_page` pattern — `page.augment` re-binds slots by header/geometry detection, `page.values` computes the payload, and `assemble.py` plans one extra sub-deck per country. Two new generic capabilities go into `fill.py`: table-cell background painting and picture-blob replacement. The ribbon is rendered to PNG by plotly + kaleido and swapped into the authored picture shape.

**Tech Stack:** Python 3.12, python-pptx, plotly 6.8 + kaleido ≥1.0, SQLAlchemy/SQLite, pandas, pytest.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-08-07-survey-slide-design.md`. Read it before starting.
- Run everything with the repo venv: `.venv/Scripts/python.exe -m pytest ...` (do not use `uv run` — the lockfile lives on OneDrive and is flaky).
- Follow `CLAUDE.md`: one function does one job; dataclasses for internal contracts; pure functions for transformation/formatting; dict-dispatch over branching; no new abstract base classes.
- Every provider called from `assemble.py` must be failure-tolerant — a broken survey page must never break the rest of the deck.
- Confidentiality: no carrier name other than the deck's subject may reach the rendered output. `flows.yaml` sets `peer_names_allowed: false` for the `survey` flow.
- Colour constants are exact and non-negotiable (sampled from the template's own art):
  - bands: `CF3638`, `FFBF35`, `FFF3DC`, none, `ABDC97`, `5BBF41`, `008542`
  - ribbon: subject box `#7BBCFC`, subject band `#BBDDFE`, peer box `#BCB9B4`, peer band `#DDDBD9`
- Survey column names (from `core/registry/flows.yaml`): table `Carriers`; `SurveyCountry`, `Carrier`, `SurveyPractice`, `Sections`, `Attributes`, `SurveySegment`, `Survey_Year`, `Score`, `NPS Score`. The section column MUST be resolved at runtime (`Sections` preferred, `Section` fallback) — `flows.yaml` is internally inconsistent about it and the live DB has not been inspected.
- The two Claims section labels use an EN DASH (U+2013): `Claims – Claims Professionals`, `Claims – Non-Claims Professionals`. Header matching must normalise dashes.
- `data_basis == "premium"` must produce today's deck unchanged. That is a regression gate, not a nice-to-have.

---

## File Structure

**Create:**

| file | responsibility |
|---|---|
| `studio/template_fill/survey/__init__.py` | package marker, re-exports `augment` / `values` |
| `studio/template_fill/survey/bands.py` | pure: Δ → band hex |
| `studio/template_fill/survey/ribbon.py` | pure: `RibbonSpec` → PNG bytes |
| `studio/template_fill/survey/facts.py` | deterministic survey queries → `ScoreGrid` + `RibbonSpec` |
| `studio/template_fill/survey/page.py` | page detection, slot binding, value payload |
| `studio/template_fill/maps/survey.json` | registers the `survey` axis → its `.pptx` |
| `tests/test_survey_bands.py` | band boundaries |
| `tests/test_survey_ribbon.py` | spec geometry + render |
| `tests/test_survey_facts.py` | grid + ribbon spec against the seed DB |
| `tests/test_survey_page.py` | detection + payload against the real template |
| `tests/test_fill_cell_and_picture.py` | the two new `fill.py` capabilities |
| `tests/test_survey_assemble.py` | sub-deck planning + gating |
| `tests/test_survey_end_to_end.py` | full pipeline over the real templates |

**Modify:**

| file | change |
|---|---|
| `studio/seed.py` | add the `Carriers` survey table + survey peer columns |
| `studio/template_fill/sections.py` | add `Section.SURVEY` + its title rule |
| `studio/template_fill/fill.py` | add `_fill_cell_backgrounds`, `_replace_pictures`, wire into `fill_template` |
| `studio/template_fill/assemble.py` | `SURVEY` axis, per-axis providers, `data_basis` gate |
| `studio/authoring/generate.py:219` | pass `data_basis` through |
| `studio/page/authoring/setup.py:257-260` | drop the "not generated yet" note |
| `pyproject.toml` | add `kaleido>=1.0.0` |

---

### Task 1: Survey seed data

Nothing downstream can be tested without survey rows in the dev DB. `studio/_seed/studio_seed.db` currently holds only `GPR` and `Peers`.

**Files:**
- Modify: `studio/seed.py`
- Test: `tests/test_survey_facts.py` (created here, extended in Task 4)

**Interfaces:**
- Produces: a `Carriers` table matching `flows.yaml`'s survey spec; a `Peers` table that additionally carries `Carrier` and `Peers` columns so survey peer resolution works; module constants `SURVEY_SECTIONS`, `SURVEY_PRACTICES`, `SURVEY_YEARS`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_survey_facts.py`:

```python
"""Survey seed data + the deterministic survey queries behind the Carrier Survey page."""
from __future__ import annotations

import pytest

from core.analytics.library import compute_breakdown
from core.analytics.types import PrimitiveArgs
from studio import seed as S


@pytest.fixture(scope="module")
def seeded():
    return S.ensure_seed_db()


def test_seed_has_survey_rows(seeded):
    facts = compute_breakdown(
        PrimitiveArgs(flow="survey", metric="score", group_by=("Sections",),
                      filters={"Carrier": S.SUBJECT, "SurveyCountry": "Singapore",
                               "Survey_Year": 2025}),
    )
    sections = {f.dims["Sections"] for f in facts}
    assert sections == set(S.SURVEY_SECTIONS)
    assert all(5.0 <= f.value <= 8.0 for f in facts)


def test_seed_survey_scores_move_year_on_year(seeded):
    def score(year):
        facts = compute_breakdown(
            PrimitiveArgs(flow="survey", metric="score", group_by=("Sections", "SurveyPractice"),
                          filters={"Carrier": S.SUBJECT, "SurveyCountry": "Singapore",
                                   "Survey_Year": year}),
        )
        return {(f.dims["Sections"], f.dims["SurveyPractice"]): f.value for f in facts}

    now, prior = score(2025), score(2024)
    deltas = [now[k] - prior[k] for k in now if k in prior]
    assert deltas, "no comparable cells between 2025 and 2024"
    # The drift table must exercise the whole band range, not just the neutral one.
    assert max(deltas) >= 1.0
    assert min(deltas) <= -1.0


def test_seed_peers_table_serves_both_flows(seeded):
    from studio.data import peer_members

    assert peer_members("gpr", S.SUBJECT, country="Singapore")
    assert peer_members("survey", S.SUBJECT, country="Singapore")
```

- [ ] **Step 2: Run it to verify it fails**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_facts.py -v
```
Expected: FAIL — `AttributeError: module 'studio.seed' has no attribute 'SURVEY_SECTIONS'`.

- [ ] **Step 3: Add the survey constants to `studio/seed.py`**

Insert after the `YEARS = [2023, 2024, 2025]` line (around line 68):

```python
# ── survey book (the `Carriers` table behind the Carrier Survey page) ────────
# Section and practice labels are the ones AUTHORED INTO template/survey_template.pptx —
# the page fills by header match, so these must stay byte-identical to the table's own
# row/column headers (note the EN DASH in the two Claims sections).
SURVEY_SECTIONS = [
    "Underwriting",
    "Client Focus",
    "Policy Administration",
    "Claims – Claims Professionals",
    "Claims – Non-Claims Professionals",
    "Loss Control",
]
SURVEY_PRACTICES = [
    "CE/CM", "Claims", "Cyber", "Energy", "FINPRO", "Property", "Marsh Multinational",
]
SURVEY_ATTRIBUTES = ["Responsiveness", "Expertise", "Accuracy"]
SURVEY_YEARS = [2023, 2024, 2025]

# Per-(section, practice) year-on-year drift, cycled deterministically so the seeded book
# exercises EVERY band in the template's legend — including both extremes. Without this the
# cell colours would all land in the neutral band and the page would look unfilled.
_SURVEY_DRIFTS = (-1.4, -0.8, -0.35, 0.0, 0.35, 0.8, 1.4)
```

- [ ] **Step 4: Add the row builder**

Insert after `_peer_rows` (around line 118):

```python
def _survey_score(rng, *, carrier: str, section: str, practice: str, year: int) -> float:
    """One survey response score on the 1–10 scale, deterministic and band-spanning.

    Built from a carrier's own standing plus a stable per-(section, practice) drift, so
    the year-on-year change a cell shows is a real, reproducible signal rather than noise.
    """
    base = 5.9 + 1.4 * _CARRIER_STRENGTH[carrier] / 1.15
    slot = (SURVEY_SECTIONS.index(section) * len(SURVEY_PRACTICES)
            + SURVEY_PRACTICES.index(practice))
    drift = _SURVEY_DRIFTS[slot % len(_SURVEY_DRIFTS)]
    elapsed = year - SURVEY_YEARS[0]
    return round(min(10.0, max(1.0, base + drift * elapsed / 2.0 + rng.uniform(-0.15, 0.15))), 2)


def _survey_rows(rng: random.Random) -> List[dict]:
    """The `Carriers` table — one row per carrier · country · practice · section ·
    attribute · year. Schema matches ``core/registry/flows.yaml``'s ``survey`` flow."""
    rows: List[dict] = []
    for carrier in CARRIERS:
        for country in COUNTRIES:
            for practice in SURVEY_PRACTICES:
                for section in SURVEY_SECTIONS:
                    for year in SURVEY_YEARS:
                        score = _survey_score(rng, carrier=carrier, section=section,
                                              practice=practice, year=year)
                        for attribute in SURVEY_ATTRIBUTES:
                            rows.append({
                                "Region": REGION_OF[country],
                                "SurveyCountry": country,
                                "Carrier": carrier,
                                "SurveyPractice": practice,
                                "Sections": section,
                                "Attributes": attribute,
                                "SurveySegment": rng.choice(SEGMENTS),
                                "Survey_Year": year,
                                "Score": score,
                                "NPS Score": round(min(10.0, max(0.0, score - 0.4)), 2),
                            })
    return rows
```

- [ ] **Step 5: Give `Peers` the survey column names too**

The survey flow's `peer_columns` are `key: Carrier`, `members: Peers` — different names from GPR's `Carrier_Group` / `Overall_Peer_Group` on the SAME table. Mirror them so one Peers table serves both flows.

In `_peer_rows`, replace both `rows.append(...)` calls so every row carries all four columns:

```python
def _peer_row(carrier: str, country: str, peer: str) -> dict:
    """One Peers row, named for BOTH flows — GPR reads Carrier_Group/Overall_Peer_Group,
    survey reads Carrier/Peers (see ``peer_columns`` in flows.yaml)."""
    return {"Carrier_Group": carrier, "Carrier": carrier, "Country": country,
            "Overall_Peer_Group": peer, "Peers": peer}


def _peer_rows(rng: random.Random) -> List[dict]:
    """The Peers table: one row per (carrier, country, peer).

    Mirrors the production shape — ``Country`` scopes a carrier's peer group, so
    ``peer_columns.country`` in ``flows.yaml`` resolves against real data here too.
    """
    rows: List[dict] = []
    for country in COUNTRIES:
        for peer in _SUBJECT_PEERS[country]:
            rows.append(_peer_row(SUBJECT, country, peer))
        for carrier in CARRIERS:  # a small generic mapping for the rest
            if carrier == SUBJECT:
                continue
            for peer in rng.sample([c for c in CARRIERS if c != carrier], 4):
                rows.append(_peer_row(carrier, country, peer))
    return rows
```

- [ ] **Step 6: Write the table and force a rebuild of stale seeds**

In `build_seed`, after `peers = pd.DataFrame(_peer_rows(rng))`:

```python
    survey = pd.DataFrame(_survey_rows(rng))

    engine = create_engine(f"sqlite:///{path}")
    gpr.to_sql("GPR", engine, index=False, if_exists="replace")
    peers.to_sql("Peers", engine, index=False, if_exists="replace")
    survey.to_sql("Carriers", engine, index=False, if_exists="replace")
    engine.dispose()
    return path
```

Then replace `_matches_current_schema` so an older seed (no `Carriers`, no survey peer columns) is rebuilt rather than silently answering with nothing:

```python
def _matches_current_schema(path: Path) -> bool:
    """Whether an existing seed has the schema this module now builds.

    Two migrations so far: Peers gained a ``Country`` column (peer groups are per-market),
    then a ``Carrier``/``Peers`` naming pair so the SAME table serves the survey flow, and
    the survey book itself arrived as ``Carriers``. An older seed would resolve no peers or
    no survey rows at all, which looks like missing data rather than a stale file — so
    detect it and rebuild.
    """
    from sqlalchemy import inspect

    engine = None
    try:
        engine = create_engine(f"sqlite:///{path}")
        inspector = inspect(engine)
        peer_cols = {c["name"] for c in inspector.get_columns("Peers")}
        return {"Country", "Carrier"} <= peer_cols and "Carriers" in inspector.get_table_names()
    except Exception:  # noqa: BLE001 — an unreadable seed is simply rebuilt
        return False
    finally:
        if engine is not None:
            engine.dispose()
```

- [ ] **Step 7: Rebuild the seed and run the tests**

```
.venv/Scripts/python.exe -m studio.seed
.venv/Scripts/python.exe -m pytest tests/test_survey_facts.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 8: Confirm nothing else regressed**

```
.venv/Scripts/python.exe -m pytest tests/ -m "not e2e" -q
```
Expected: same pass/fail counts as before this task.

- [ ] **Step 9: Commit**

`studio/_seed/` is git-ignored — the seed DB is a generated artifact and stays that way.
`ensure_seed_db` rebuilds it wherever the schema check (Step 6) fails, so do NOT force-add it.

```bash
git add studio/seed.py tests/test_survey_facts.py
git commit -m "feat: seed the survey book so the Carrier Survey page is testable locally"
```

---

### Task 2: Band colours

**Files:**
- Create: `studio/template_fill/survey/__init__.py`, `studio/template_fill/survey/bands.py`
- Test: `tests/test_survey_bands.py`

**Interfaces:**
- Produces: `bands.band_for(delta: Optional[float]) -> Optional[str]` — an uppercase 6-digit hex with no `#`, or `None` for "no fill". Consumed by Task 6.

- [ ] **Step 1: Write the failing test**

Create `tests/test_survey_bands.py`:

```python
"""The Carrier Survey table's cell banding — Δ vs prior year → the legend's colour.

Edges are the ones read off the template's own legend picture: the NEUTRAL band is
inclusive on both sides (|Δ| = 0.2 is white); every other edge lands in the MORE
extreme band (Δ = -0.5 is amber, Δ = +0.5 is mid-green, |Δ| = 1 is the extreme).
"""
from __future__ import annotations

import pytest

from studio.template_fill.survey import bands


@pytest.mark.parametrize("delta,expected", [
    (-3.0, "CF3638"),
    (-1.0, "CF3638"),          # edge: closes the red band
    (-0.99, "FFBF35"),
    (-0.5, "FFBF35"),          # edge: closes the amber band
    (-0.49, "FFF3DC"),
    (-0.21, "FFF3DC"),
    (-0.2, None),              # edge: neutral is inclusive
    (0.0, None),
    (0.2, None),               # edge: neutral is inclusive
    (0.21, "ABDC97"),
    (0.49, "ABDC97"),
    (0.5, "5BBF41"),           # edge: opens the mid-green band
    (0.99, "5BBF41"),
    (1.0, "008542"),           # edge: opens the dark-green band
    (4.0, "008542"),
])
def test_band_for_covers_every_edge(delta, expected):
    assert bands.band_for(delta) == expected


def test_band_for_none_delta_is_unfilled():
    assert bands.band_for(None) is None


def test_every_legend_colour_is_reachable():
    reached = {bands.band_for(d) for d in (-2, -0.7, -0.3, 0, 0.3, 0.7, 2)}
    assert reached == {"CF3638", "FFBF35", "FFF3DC", None, "ABDC97", "5BBF41", "008542"}
```

- [ ] **Step 2: Run it to verify it fails**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_bands.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.template_fill.survey'`.

- [ ] **Step 3: Create the package marker**

`studio/template_fill/survey/__init__.py` — **docstring only, no imports**. Re-exporting
`page` here would make the package `__init__` import `page`, which imports back
`from studio.template_fill.survey import bands, facts` — a circular import that only works
by accident. Consumers import the submodules directly instead.

```python
"""The Carrier Survey page — the per-country slide built from ``survey_template.pptx``.

Split by responsibility so each piece stays testable on its own:

  * :mod:`bands`  — pure: a year-on-year score change → the legend's cell colour;
  * :mod:`ribbon` — pure: a ranking spec → the chart PNG;
  * :mod:`facts`  — the deterministic survey queries behind both;
  * :mod:`page`   — detection, slot binding and the fill payload (the module
    :mod:`studio.template_fill.assemble` actually calls).

Deliberately re-exports nothing: ``page`` imports its siblings from this package, so an
``__init__`` that imported ``page`` would close a cycle. Import the submodule you want.
"""
```

- [ ] **Step 4: Write `bands.py`**

```python
"""Δ-vs-prior-year → the Carrier Survey table's cell colour.

Pure and table-driven: the seven bands are read straight off the legend picture the
author placed on the slide (``template/survey_template.pptx``, shape 52), so the table
below IS the legend. Correcting a threshold is a one-line edit here and nowhere else.
"""
from __future__ import annotations

from typing import Optional, Tuple

RED = "CF3638"
AMBER = "FFBF35"
CREAM = "FFF3DC"
NEUTRAL: Optional[str] = None       # no fill — the cell keeps the template's own styling
LIGHT_GREEN = "ABDC97"
GREEN = "5BBF41"
DARK_GREEN = "008542"

# (upper bound, closed at that bound?, colour), worst first. A delta takes the FIRST band
# it falls under; anything past the last row is the dark-green band. The neutral band is
# closed on BOTH sides — |Δ| = 0.2 reads as "no material change" — while every other edge
# belongs to the more extreme band, which is how the legend labels them
# ("=< to -1" is red, ">= to 1" is dark green).
_BANDS: Tuple[Tuple[float, bool, Optional[str]], ...] = (
    (-1.0, True, RED),
    (-0.5, True, AMBER),
    (-0.2, False, CREAM),
    (0.2, True, NEUTRAL),
    (0.5, False, LIGHT_GREEN),
    (1.0, False, GREEN),
)


def band_for(delta: Optional[float]) -> Optional[str]:
    """The cell colour for a year-on-year score change (``None`` ⇒ leave unfilled).

    ``None`` in means the cell has no comparable prior-year score, which is not the same
    as "no change" — the number still prints, but nothing is claimed about its direction.
    """
    if delta is None:
        return None
    for upper, closed, colour in _BANDS:
        if delta < upper or (closed and delta == upper):
            return colour
    return DARK_GREEN
```

- [ ] **Step 5: Run the tests**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_bands.py -v
```
Expected: PASS (17 tests).

- [ ] **Step 6: Commit**

```bash
git add studio/template_fill/survey/__init__.py studio/template_fill/survey/bands.py tests/test_survey_bands.py
git commit -m "feat: add the Carrier Survey cell banding table"
```

---

### Task 3: The ribbon renderer

Pure spec → PNG. No data access. The code below is **already validated** — it renders in ~2s and closely matches the authored think-cell art.

**Files:**
- Create: `studio/template_fill/survey/ribbon.py`
- Modify: `pyproject.toml`
- Test: `tests/test_survey_ribbon.py`

**Interfaces:**
- Produces: `RibbonBox(carrier: str, score: float, highlight: bool = False)`, `RibbonColumn(label: str, boxes: Tuple[RibbonBox, ...])`, `RibbonSpec(columns, title, width_px, height_px)`, `render_ribbon_png(spec) -> bytes`, `available() -> bool`. Consumed by Tasks 4 and 6.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, in the `dependencies` list, after the two `plotly` entries:

```toml
    # Renders the Carrier Survey ribbon chart to PNG (studio/template_fill/survey/ribbon.py).
    # v1+ only: 0.2.1 hangs indefinitely on Windows. Needs a Chrome/Chromium on the host;
    # `plotly_get_chrome` fetches one where none exists. The survey page degrades to the
    # authored picture when it is unavailable, so this is a soft runtime requirement.
    "kaleido>=1.0.0",
```

Install it:

```
.venv/Scripts/python.exe -m pip install "kaleido>=1.0.0"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_survey_ribbon.py`:

```python
"""The Carrier Survey ribbon chart — geometry and rendering.

Geometry is asserted on the figure spec (fast, hermetic); the PNG render is asserted
once and skipped where kaleido has no browser, because that is an environment fact,
not a code fault.
"""
from __future__ import annotations

import pytest

from studio.template_fill.survey import ribbon as R

_SECTIONS = ["Underwriting", "Client Focus", "Loss Control"]


def _spec(highlight: str = "Zurich") -> R.RibbonSpec:
    columns = []
    for i, section in enumerate(_SECTIONS):
        scored = [("Zurich", 6.4 + i * 0.1), ("AIG", 7.1), ("Chubb", 6.8)]
        scored.sort(key=lambda t: -t[1])
        columns.append(R.RibbonColumn(section, tuple(
            R.RibbonBox(c, v, highlight=(c == highlight)) for c, v in scored)))
    return R.RibbonSpec(tuple(columns))


def test_boxes_are_ordered_best_first_within_a_column():
    column = _spec().columns[0]
    assert [b.score for b in column.boxes] == sorted((b.score for b in column.boxes), reverse=True)


def test_figure_draws_a_box_per_carrier_per_column():
    fig = R.build_figure(_spec())
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert len(rects) == len(_SECTIONS) * 3


def test_subject_boxes_use_the_carrier_colour_and_peers_the_grey():
    fig = R.build_figure(_spec())
    fills = [s.fillcolor for s in fig.layout.shapes if s.type == "rect"]
    assert fills.count(R.CARRIER_FILL) == len(_SECTIONS)
    assert fills.count(R.PEER_FILL) == len(_SECTIONS) * 2


def test_subject_band_is_drawn_after_every_peer_band():
    """The carrier's ribbon must read ON TOP of the grey ones, so it is added last."""
    fig = R.build_figure(_spec())
    paths = [s for s in fig.layout.shapes if s.type == "path"]
    colours = [s.fillcolor for s in paths]
    assert colours[-1] == R.CARRIER_BAND
    assert colours.index(R.CARRIER_BAND) == len(colours) - colours.count(R.CARRIER_BAND)


def test_column_labels_are_annotated_once_each():
    fig = R.build_figure(_spec())
    texts = [a.text for a in fig.layout.annotations]
    for section in _SECTIONS:
        assert any(section.split()[0] in t for t in texts)


def test_score_labels_are_one_decimal_place():
    fig = R.build_figure(_spec())
    assert "7.1" in [a.text for a in fig.layout.annotations]


def test_empty_spec_builds_without_dividing_by_zero():
    fig = R.build_figure(R.RibbonSpec(()))
    assert not [s for s in fig.layout.shapes if s.type == "rect"]


@pytest.mark.skipif(not R.available(), reason="kaleido/Chrome not available on this host")
def test_render_produces_a_png_of_the_authored_aspect():
    png = R.render_ribbon_png(_spec())
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5_000
```

- [ ] **Step 3: Run it to verify it fails**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_ribbon.py -v
```
Expected: FAIL — `ImportError: cannot import name 'ribbon'`.

- [ ] **Step 4: Write `ribbon.py`**

```python
"""The "Peers Ranked by Survey Scores" ribbon — a spec in, a PNG out.

The author drew this page's chart with think-cell and pasted the RESULT as a picture, so
there is no chart to refill: the page is filled by rendering our own image at the authored
picture's exact frame and swapping the blob (see :mod:`studio.template_fill.fill`).

The shape of the chart is a bump/ribbon: one COLUMN per survey section, each a rank-ordered
stack of score boxes (best at the top), with a curved band joining the same carrier's box
across adjacent columns so a reader follows one carrier's rank left to right. The deck's
subject is blue; every peer is grey and unnamed — ``flows.yaml`` sets
``peer_names_allowed: false`` for the survey flow, so a box carries its SCORE and nothing else.

Pure: no data access, no I/O beyond the render itself.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from logger import get_logger

logger = get_logger(__name__)

# Sampled from the authored picture so a refilled chart is indistinguishable in style.
CARRIER_FILL = "#7BBCFC"
CARRIER_BAND = "#BBDDFE"
PEER_FILL = "#BCB9B4"
PEER_BAND = "#DDDBD9"
SCORE_TEXT = "#FFFFFF"
AXIS_TEXT = "#444444"
TITLE_TEXT = "#222222"

# The authored picture's pixel size — the render matches it so the swap needs no rescale.
WIDTH_PX = 1162
HEIGHT_PX = 303

TITLE = "Peers Ranked by Survey Scores (Section level)"

# Layout, as fractions of the image. A box occupies under half its column's pitch so the
# ribbons have room to cross; the plot band stops short of the bottom to leave the wrapped
# section labels somewhere to sit.
_BOX_SHARE = 0.46
_ROW_SHARE = 0.74
_PLOT_TOP = 0.88
_PLOT_BOTTOM = 0.24
_LABEL_WRAP = 18


@dataclass(frozen=True)
class RibbonBox:
    """One carrier's score in one section. ``highlight`` marks the deck's subject."""

    carrier: str
    score: float
    highlight: bool = False


@dataclass(frozen=True)
class RibbonColumn:
    """One section's ranking — ``boxes`` ordered best score first."""

    label: str
    boxes: Tuple[RibbonBox, ...] = ()


@dataclass(frozen=True)
class RibbonSpec:
    """Everything the renderer needs: the columns, the title, and the output size."""

    columns: Tuple[RibbonColumn, ...] = ()
    title: str = TITLE
    width_px: int = WIDTH_PX
    height_px: int = HEIGHT_PX


def available() -> bool:
    """Whether a PNG can actually be rendered on this host (kaleido + a browser)."""
    try:
        import kaleido  # noqa: F401
    except ImportError:
        return False
    return True


# ── geometry (pure) ──────────────────────────────────────────────────────────


def _wrap(label: str) -> str:
    return "<br>".join(textwrap.wrap(str(label), width=_LABEL_WRAP) or [""])


def _row_count(spec: RibbonSpec) -> int:
    return max((len(c.boxes) for c in spec.columns), default=0)


def _metrics(spec: RibbonSpec) -> Tuple[float, float, float, float]:
    """``(column pitch, half box width, row pitch, half box height)`` in 0..1 coords."""
    pitch = 1.0 / max(len(spec.columns), 1)
    rows = max(_row_count(spec), 1)
    row_pitch = (_PLOT_TOP - _PLOT_BOTTOM) / rows
    return pitch, pitch * _BOX_SHARE / 2.0, row_pitch, row_pitch * _ROW_SHARE / 2.0


def _box_rect(spec: RibbonSpec, col: int, row: int) -> Tuple[float, float, float, float]:
    """One box's ``(left, bottom, right, top)``."""
    pitch, half_w, row_pitch, half_h = _metrics(spec)
    cx = (col + 0.5) * pitch
    cy = _PLOT_TOP - (row + 0.5) * row_pitch
    return cx - half_w, cy - half_h, cx + half_w, cy + half_h


def _band_path(x0: float, y0t: float, y0b: float,
               x1: float, y1t: float, y1b: float) -> str:
    """An SVG path for one ribbon: two mirrored cubic beziers closed into a band."""
    xm = (x0 + x1) / 2.0
    return (f"M {x0},{y0t} C {xm},{y0t} {xm},{y1t} {x1},{y1t} "
            f"L {x1},{y1b} C {xm},{y1b} {xm},{y0b} {x0},{y0b} Z")


# ── figure ───────────────────────────────────────────────────────────────────


def _ranks(spec: RibbonSpec) -> List[Dict[str, int]]:
    """Per column, ``{carrier: its row index}`` — what a band needs at both ends."""
    return [{b.carrier: i for i, b in enumerate(col.boxes)} for col in spec.columns]


def _band_shapes(spec: RibbonSpec, ranks: List[Dict[str, int]], *, highlight: bool) -> List[dict]:
    """The ribbons for the subject (``highlight``) or for the peers.

    Split so the caller can add the peers' first and the subject's last: shapes paint in
    insertion order, and the carrier's own thread must read on top of the grey ones.
    """
    out: List[dict] = []
    for i in range(len(spec.columns) - 1):
        for carrier, r0 in ranks[i].items():
            r1 = ranks[i + 1].get(carrier)
            if r1 is None or spec.columns[i].boxes[r0].highlight is not highlight:
                continue
            _, y0b, x0, y0t = _box_rect(spec, i, r0)
            x1, y1b, _, y1t = _box_rect(spec, i + 1, r1)
            out.append(dict(
                type="path", xref="paper", yref="paper",
                path=_band_path(x0, y0t, y0b, x1, y1t, y1b),
                fillcolor=(CARRIER_BAND if highlight else PEER_BAND),
                line=dict(width=0), layer="below",
            ))
    return out


def _box_shapes_and_labels(spec: RibbonSpec) -> Tuple[List[dict], List[dict]]:
    """Every score box and the score printed inside it."""
    shapes: List[dict] = []
    labels: List[dict] = []
    for i, column in enumerate(spec.columns):
        for j, box in enumerate(column.boxes):
            x0, y0, x1, y1 = _box_rect(spec, i, j)
            shapes.append(dict(
                type="rect", xref="paper", yref="paper", x0=x0, y0=y0, x1=x1, y1=y1,
                fillcolor=(CARRIER_FILL if box.highlight else PEER_FILL),
                line=dict(width=0), layer="above",
            ))
            labels.append(dict(
                xref="paper", yref="paper", x=(x0 + x1) / 2.0, y=(y0 + y1) / 2.0,
                text=f"{box.score:.1f}", showarrow=False, xanchor="center", yanchor="middle",
                font=dict(family="Arial", size=11, color=SCORE_TEXT),
            ))
    return shapes, labels


def _axis_labels(spec: RibbonSpec) -> List[dict]:
    """The section name under each column (wrapped — some run to four words)."""
    pitch, *_ = _metrics(spec)
    return [
        dict(xref="paper", yref="paper", x=(i + 0.5) * pitch, y=_PLOT_BOTTOM - 0.04,
             text=_wrap(column.label), showarrow=False, xanchor="center", yanchor="top",
             font=dict(family="Arial", size=11, color=AXIS_TEXT))
        for i, column in enumerate(spec.columns)
    ]


def build_figure(spec: RibbonSpec):
    """The plotly figure for ``spec`` — separated from the render so it is unit-testable."""
    import plotly.graph_objects as go

    ranks = _ranks(spec)
    boxes, scores = _box_shapes_and_labels(spec)
    shapes = (_band_shapes(spec, ranks, highlight=False)
              + _band_shapes(spec, ranks, highlight=True)
              + boxes)
    title = dict(xref="paper", yref="paper", x=0.0, y=1.0, text=spec.title,
                 showarrow=False, xanchor="left", yanchor="top",
                 font=dict(family="Arial", size=13, color=TITLE_TEXT))

    fig = go.Figure()
    fig.update_layout(
        shapes=shapes,
        annotations=scores + _axis_labels(spec) + [title],
        xaxis=dict(visible=False, range=[0, 1], fixedrange=True),
        yaxis=dict(visible=False, range=[0, 1], fixedrange=True),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="white", plot_bgcolor="white", showlegend=False,
    )
    return fig


def render_ribbon_png(spec: RibbonSpec) -> bytes:
    """``spec`` rendered to PNG bytes at twice the authored picture's pixel size.

    Raises whatever kaleido raises — the caller decides whether a missing renderer means
    "keep the authored picture" (the page) or "fail the test" (the suite).
    """
    return build_figure(spec).to_image(
        format="png", width=spec.width_px, height=spec.height_px, scale=2)
```

- [ ] **Step 5: Run the tests**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_ribbon.py -v
```
Expected: PASS (8 tests).

- [ ] **Step 6: Eyeball the render**

```
.venv/Scripts/python.exe -c "
from studio.template_fill.survey import ribbon as R
import random
rng = random.Random(7)
secs = ['Underwriting','Client Focus','Policy Administration','Claims – Claims Professionals','Claims – Non-Claims Professionals','Loss Control']
cols=[]
for s in secs:
    sc=[(f'C{i}', round(rng.uniform(6.2,7.3),1)) for i in range(9)]
    sc.sort(key=lambda t:-t[1])
    cols.append(R.RibbonColumn(s, tuple(R.RibbonBox(c,v,highlight=(c=='C3')) for c,v in sc)))
open('ribbon_check.png','wb').write(R.render_ribbon_png(R.RibbonSpec(tuple(cols))))
print('wrote ribbon_check.png')
"
```
Open `ribbon_check.png`. It must show six rank-ordered columns of grey boxes with one blue thread running through them, section names on the x-axis, and no clipped labels. Delete the file afterwards.

- [ ] **Step 7: Commit**

```bash
git add studio/template_fill/survey/ribbon.py tests/test_survey_ribbon.py pyproject.toml
git commit -m "feat: render the Carrier Survey ribbon chart to PNG"
```

---

### Task 4: Survey facts

**Files:**
- Create: `studio/template_fill/survey/facts.py`
- Test: `tests/test_survey_facts.py` (extend the file from Task 1)

**Interfaces:**
- Consumes: `ribbon.RibbonSpec` / `RibbonColumn` / `RibbonBox` (Task 3).
- Produces:
  - `SECTION_CANDIDATES`, `PRACTICE_COL`, `CARRIER_COL`, `COUNTRY_COL`, `YEAR_COL`, `SURVEY_FLOW` constants
  - `has_survey_data(result, country) -> bool`
  - `ScoreGrid` dataclass: fields `.year`, `.prior_year`, `.overall`, `.prior_overall`; methods `.score(section, practice)`, `.delta(section, practice)`, `.section_total(section)`, `.section_total_delta(section)`, `.practice_total(practice)`, `.practice_total_delta(practice)`, `.overall_delta()`
  - `load_grid(result, country) -> Optional[ScoreGrid]`
  - `load_ribbon(result, country, sections) -> Optional[ribbon.RibbonSpec]`
- Consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_survey_facts.py`:

```python
# ── the queries behind the page ──────────────────────────────────────────────


def _result(country="Singapore", peers=None):
    from studio.compute import OverallResult

    return OverallResult(subject=S.SUBJECT, flow="gpr",
                         resolved_filters={"Country": country}, peers=peers)


def test_has_survey_data_is_true_for_a_seeded_country(seeded):
    from studio.template_fill.survey import facts

    assert facts.has_survey_data(_result(), "Singapore") is True


def test_has_survey_data_is_false_for_an_unknown_country(seeded):
    from studio.template_fill.survey import facts

    assert facts.has_survey_data(_result(), "Atlantis") is False


def test_load_grid_reports_the_latest_year_against_the_one_before(seeded):
    from studio.template_fill.survey import facts

    grid = facts.load_grid(_result(), "Singapore")
    assert grid is not None
    assert grid.year == max(S.SURVEY_YEARS)
    assert grid.prior_year == max(S.SURVEY_YEARS) - 1


def test_load_grid_fills_every_authored_cell(seeded):
    from studio.template_fill.survey import facts

    grid = facts.load_grid(_result(), "Singapore")
    for section in S.SURVEY_SECTIONS:
        for practice in S.SURVEY_PRACTICES:
            assert grid.score(section, practice) is not None
            assert grid.delta(section, practice) is not None


def test_load_grid_totals_come_from_the_rows_not_the_cells(seeded):
    """A Total is its own AVG over the raw rows — never a mean of the displayed cells."""
    from statistics import fmean

    from studio.template_fill.survey import facts

    grid = facts.load_grid(_result(), "Singapore")
    cells = [grid.score(sec, S.SURVEY_PRACTICES[0]) for sec in S.SURVEY_SECTIONS]
    # Equal-sized cells make the two agree here; the point is that the total EXISTS
    # independently and is on the same scale, not that it is computed from the cells.
    assert grid.practice_total(S.SURVEY_PRACTICES[0]) == pytest.approx(fmean(cells), abs=0.05)
    assert 1.0 <= grid.overall <= 10.0


def test_load_grid_returns_none_for_a_country_with_no_survey(seeded):
    from studio.template_fill.survey import facts

    assert facts.load_grid(_result(), "Atlantis") is None


def test_load_ribbon_ranks_best_first_and_highlights_only_the_subject(seeded):
    from studio.template_fill.survey import facts

    spec = facts.load_ribbon(_result(), "Singapore", tuple(S.SURVEY_SECTIONS))
    assert spec is not None
    assert [c.label for c in spec.columns] == S.SURVEY_SECTIONS
    for column in spec.columns:
        scores = [b.score for b in column.boxes]
        assert scores == sorted(scores, reverse=True)
        assert sum(1 for b in column.boxes if b.highlight) == 1
        assert next(b for b in column.boxes if b.highlight).carrier == S.SUBJECT


def test_load_ribbon_honours_a_pinned_peer_set(seeded):
    from studio.template_fill.survey import facts

    spec = facts.load_ribbon(_result(peers=("AIG", "Chubb")), "Singapore",
                             tuple(S.SURVEY_SECTIONS))
    carriers = {b.carrier for c in spec.columns for b in c.boxes}
    assert carriers == {S.SUBJECT, "AIG", "Chubb"}


def test_load_ribbon_caps_the_stack_but_never_drops_the_subject(seeded):
    from studio.template_fill.survey import facts

    everyone = tuple(c for c in S.CARRIERS if c != S.SUBJECT)
    spec = facts.load_ribbon(_result(peers=everyone), "Singapore", tuple(S.SURVEY_SECTIONS))
    for column in spec.columns:
        assert len(column.boxes) == facts.MAX_RIBBON_ROWS
        assert any(b.highlight for b in column.boxes)
```

- [ ] **Step 2: Run to verify it fails**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_facts.py -v
```
Expected: FAIL — `ImportError: cannot import name 'facts'`.

- [ ] **Step 3: Write `facts.py`**

```python
"""The deterministic survey queries behind the Carrier Survey page.

Everything the page shows comes from the ``survey`` flow (table ``Carriers``), never the
premium book — a survey score is not a premium figure, and the two use different
taxonomies (``SurveyPractice`` vs ``Product_Line``, ``Carrier`` vs ``Carrier_Group``).
For that reason the page is scoped by COUNTRY, CARRIER and YEAR only: honouring a
``Product_Line`` pin would blank most of a table whose columns ARE the practices.

Two products:

  * :class:`ScoreGrid` — the table. The subject's average score per section × practice at
    the latest surveyed year, the same grid a year earlier, and the row/column/corner
    totals. Totals are their OWN average over the raw rows, not a mean of the displayed
    cells, so a sparse row cannot skew them.
  * :func:`load_ribbon` — the chart. Per section, the subject and its peers ranked by
    average score.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from logger import get_logger
from studio.template_fill.survey import ribbon as ribbon_mod

logger = get_logger(__name__)

SURVEY_FLOW = "survey"
SURVEY_TABLE = "Carriers"
CARRIER_COL = "Carrier"
COUNTRY_COL = "SurveyCountry"
PRACTICE_COL = "SurveyPractice"
YEAR_COL = "Survey_Year"
# ``flows.yaml`` names this column ``Sections`` in its column table but ``Section`` in the
# chart defaults, and the live warehouse has not been inspected — so resolve it against
# the real table rather than trusting either. Preference order, first match wins.
SECTION_CANDIDATES: Tuple[str, ...] = ("Sections", "Section")

# The stack the authored ribbon art fits. More rows than this and the score labels stop
# being legible at the picture's frame size.
MAX_RIBBON_ROWS = 9


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — a failing query degrades the page, never breaks it
        logger.warning("survey.facts: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


def _breakdown(result, group_by: Tuple[str, ...], filters: Dict[str, Any]):
    """``compute_breakdown`` over the survey flow, returning ``[]`` on any failure."""
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    return _safe(
        compute_breakdown,
        PrimitiveArgs(flow=SURVEY_FLOW, metric="score", group_by=group_by, filters=filters),
        engine=result.engine,
    ) or []


def section_column(result) -> Optional[str]:
    """Which column actually holds the survey sections, or ``None`` if there is no book."""
    from core.analytics.sql import resolve_engine, table_columns

    columns = _safe(table_columns, _safe(resolve_engine, result.engine), SURVEY_TABLE) or frozenset()
    for candidate in SECTION_CANDIDATES:
        if candidate in columns:
            return candidate
    return None


def _base_filters(result, country: str) -> Dict[str, Any]:
    """Country + carrier — the ONLY premium-side scoping the survey page inherits."""
    return {COUNTRY_COL: str(country), CARRIER_COL: str(result.subject)}


def has_survey_data(result, country: str) -> bool:
    """Whether ``country`` has any survey rows for the subject — the slide's gate."""
    if section_column(result) is None:
        return False
    return bool(_breakdown(result, (), _base_filters(result, country)))


def _reported_years(result, country: str) -> Tuple[Optional[int], Optional[int]]:
    """``(latest surveyed year, the one before it)`` for this country and carrier."""
    facts = _breakdown(result, (YEAR_COL,), _base_filters(result, country))
    years = sorted({int(f.dims[YEAR_COL]) for f in facts if f.dims.get(YEAR_COL) is not None})
    if not years:
        return None, None
    latest = years[-1]
    return latest, (latest - 1 if (latest - 1) in years else None)


# ── the table ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoreGrid:
    """The Carrier Survey table's numbers for one country.

    ``cells`` / ``prior_cells`` are keyed ``(section, practice)``; the totals are keyed by
    the one dimension they collapse to. Every lookup returns ``None`` when the data has no
    such cut — the page then keeps the template's own placeholder rather than inventing a
    number.
    """

    year: int
    prior_year: Optional[int]
    cells: Dict[Tuple[str, str], float]
    prior_cells: Dict[Tuple[str, str], float]
    section_totals: Dict[str, float]
    prior_section_totals: Dict[str, float]
    practice_totals: Dict[str, float]
    prior_practice_totals: Dict[str, float]
    overall: Optional[float] = None
    prior_overall: Optional[float] = None

    def score(self, section: str, practice: str) -> Optional[float]:
        return self.cells.get((section, practice))

    def delta(self, section: str, practice: str) -> Optional[float]:
        return _diff(self.cells.get((section, practice)),
                     self.prior_cells.get((section, practice)))

    def section_total(self, section: str) -> Optional[float]:
        return self.section_totals.get(section)

    def section_total_delta(self, section: str) -> Optional[float]:
        return _diff(self.section_totals.get(section), self.prior_section_totals.get(section))

    def practice_total(self, practice: str) -> Optional[float]:
        return self.practice_totals.get(practice)

    def practice_total_delta(self, practice: str) -> Optional[float]:
        return _diff(self.practice_totals.get(practice), self.prior_practice_totals.get(practice))

    def overall_delta(self) -> Optional[float]:
        return _diff(self.overall, self.prior_overall)


def _diff(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    """The year-on-year change, or ``None`` when either side is missing.

    ``None`` is NOT zero: a cell with no comparable prior year makes no claim about its
    direction, so it prints its number and takes no band colour.
    """
    return None if (current is None or prior is None) else float(current) - float(prior)


def _by_pair(facts, first: str, second: str) -> Dict[Tuple[str, str], float]:
    return {(str(f.dims[first]), str(f.dims[second])): float(f.value)
            for f in facts if f.dims.get(first) is not None and f.dims.get(second) is not None}


def _by_one(facts, column: str) -> Dict[str, float]:
    return {str(f.dims[column]): float(f.value) for f in facts if f.dims.get(column) is not None}


def _one(facts) -> Optional[float]:
    return float(facts[0].value) if facts else None


def load_grid(result, country: str) -> Optional[ScoreGrid]:
    """The table's numbers for ``country``, or ``None`` when it has no survey book.

    Four cuts per year — the body, the two total axes and the corner — because a Total is
    an average over the ROWS in that cut, which no arithmetic on the body can reproduce
    once any cell is missing.
    """
    section = section_column(result)
    if section is None:
        return None
    year, prior_year = _reported_years(result, country)
    if year is None:
        return None

    def cuts(for_year: int):
        filters = {**_base_filters(result, country), YEAR_COL: int(for_year)}
        return (
            _by_pair(_breakdown(result, (section, PRACTICE_COL), filters), section, PRACTICE_COL),
            _by_one(_breakdown(result, (section,), filters), section),
            _by_one(_breakdown(result, (PRACTICE_COL,), filters), PRACTICE_COL),
            _one(_breakdown(result, (), filters)),
        )

    cells, section_totals, practice_totals, overall = cuts(year)
    if not cells:
        return None
    if prior_year is None:
        prior: Tuple[Dict, Dict, Dict, Optional[float]] = ({}, {}, {}, None)
    else:
        prior = cuts(prior_year)

    return ScoreGrid(
        year=year, prior_year=prior_year,
        cells=cells, prior_cells=prior[0],
        section_totals=section_totals, prior_section_totals=prior[1],
        practice_totals=practice_totals, prior_practice_totals=prior[2],
        overall=overall, prior_overall=prior[3],
    )


# ── the ribbon ───────────────────────────────────────────────────────────────


def _peer_carriers(result, country: str) -> Tuple[str, ...]:
    """The carriers the subject is ranked against — the Setup peer selection.

    Order of authority: the custom peers pinned in Setup, else the subject's group from
    the survey flow's own Peers table. An empty result is not an error — the ribbon then
    shows the subject alone, which is honest.
    """
    pinned = tuple(str(p) for p in (result.peers or ()) if str(p).strip())
    if pinned:
        return pinned
    from studio.data import peer_members

    return tuple(_safe(peer_members, SURVEY_FLOW, str(result.subject), country=str(country)) or ())


def _capped(boxes: Sequence[ribbon_mod.RibbonBox]) -> Tuple[ribbon_mod.RibbonBox, ...]:
    """The top :data:`MAX_RIBBON_ROWS` boxes, with the subject kept whatever its rank.

    The authored art fits nine rows. Dropping the subject to fit would defeat the chart,
    so when the cap would cut it the lowest-scoring PEER goes instead.
    """
    if len(boxes) <= MAX_RIBBON_ROWS:
        return tuple(boxes)
    kept = list(boxes[:MAX_RIBBON_ROWS])
    if not any(b.highlight for b in kept):
        subject = next((b for b in boxes if b.highlight), None)
        if subject is not None:
            kept[-1] = subject
            kept.sort(key=lambda b: -b.score)
    return tuple(kept)


def load_ribbon(result, country: str, sections: Sequence[str]) -> Optional[ribbon_mod.RibbonSpec]:
    """The ranking chart's spec: one column per section, in the order ``sections`` gives.

    ``sections`` is the TEMPLATE's authored row order (minus its Total row), so the chart
    reads down the page in the same order as the table above it.
    """
    section = section_column(result)
    if section is None:
        return None
    year, _ = _reported_years(result, country)
    if year is None:
        return None
    subject = str(result.subject)
    wanted = {subject, *(_peer_carriers(result, country))}

    columns = []
    for label in sections:
        filters = {COUNTRY_COL: str(country), YEAR_COL: int(year), section: str(label)}
        facts = _breakdown(result, (CARRIER_COL,), filters)
        scored = [(str(f.dims[CARRIER_COL]), float(f.value))
                  for f in facts if str(f.dims.get(CARRIER_COL)) in wanted]
        if not scored:
            continue
        scored.sort(key=lambda pair: -pair[1])
        boxes = _capped([ribbon_mod.RibbonBox(name, value, highlight=(name == subject))
                         for name, value in scored])
        columns.append(ribbon_mod.RibbonColumn(str(label), boxes))

    return ribbon_mod.RibbonSpec(tuple(columns)) if columns else None
```

- [ ] **Step 4: Run the tests**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_facts.py -v
```
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add studio/template_fill/survey/facts.py tests/test_survey_facts.py
git commit -m "feat: load the Carrier Survey score grid and peer ranking"
```

---

### Task 5: Cell backgrounds and picture replacement in the fill engine

Two generic capabilities the engine does not have. Both sit beside `_fill_charts` and are driven by `values` payload keys, exactly like `gwp_bars` and `lc_ranking`.

**Files:**
- Modify: `studio/template_fill/fill.py`
- Test: `tests/test_fill_cell_and_picture.py`

**Interfaces:**
- Produces:
  - `values["cell_fills"]`: `{"<slide>:<shape>": [{"r": int, "c": int, "hex": str | None}]}`
  - `values["pictures"]`: `{"<slide>:<shape>": bytes}` (PNG only)
- Consumed by Task 6.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fill_cell_and_picture.py`:

```python
"""The two generic capabilities the Carrier Survey page needs from the fill engine:
painting table-cell backgrounds, and swapping a picture's image for a rendered one.

Hermetic — builds its own one-slide deck, so it proves the mechanics without a template.
"""
from __future__ import annotations

import base64
import io

import pytest
from pptx import Presentation
from pptx.util import Inches

from studio.template_fill import fill as F

# Two valid, distinct 1x1 PNGs. Inline rather than drawn with Pillow: Pillow is only a
# transitive dependency here, and the test needs nothing more than "two different PNGs".
_RED = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
_BLUE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.fixture
def deck():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(2))
    picture = slide.shapes.add_picture(io.BytesIO(_RED), Inches(1), Inches(4),
                                       Inches(2), Inches(1))
    return prs, table.shape_id, picture.shape_id


def test_cell_background_is_painted_from_the_payload(deck):
    prs, table_id, _ = deck
    F._fill_cell_backgrounds(prs, {"cell_fills": {f"0:{table_id}": [
        {"r": 1, "c": 1, "hex": "CF3638"}]}})
    cell = prs.slides[0].shapes[0].table.cell(1, 1)
    assert str(cell.fill.fore_color.rgb) == "CF3638"


def test_a_none_hex_clears_the_cell_to_no_fill(deck):
    from pptx.enum.dml import MSO_FILL

    prs, table_id, _ = deck
    key = f"0:{table_id}"
    F._fill_cell_backgrounds(prs, {"cell_fills": {key: [{"r": 0, "c": 0, "hex": "008542"}]}})
    F._fill_cell_backgrounds(prs, {"cell_fills": {key: [{"r": 0, "c": 0, "hex": None}]}})
    assert prs.slides[0].shapes[0].table.cell(0, 0).fill.type == MSO_FILL.BACKGROUND


def test_an_out_of_range_cell_is_skipped_not_raised(deck):
    prs, table_id, _ = deck
    F._fill_cell_backgrounds(prs, {"cell_fills": {f"0:{table_id}": [
        {"r": 9, "c": 9, "hex": "CF3638"}]}})   # must not raise


def test_no_payload_is_a_no_op(deck):
    prs, _, _ = deck
    F._fill_cell_backgrounds(prs, {})           # must not raise


def test_picture_blob_is_replaced_in_place(deck):
    prs, _, picture_id = deck
    before = prs.slides[0].shapes[1].image.blob
    replacement = _BLUE
    F._replace_pictures(prs, {"pictures": {f"0:{picture_id}": replacement}})
    after = prs.slides[0].shapes[1]
    assert after.image.blob == replacement
    assert after.image.blob != before


def test_picture_replacement_keeps_the_authored_frame(deck):
    prs, _, picture_id = deck
    shape = prs.slides[0].shapes[1]
    frame = (shape.left, shape.top, shape.width, shape.height)
    F._replace_pictures(prs, {"pictures": {f"0:{picture_id}": _BLUE}})
    after = prs.slides[0].shapes[1]
    assert (after.left, after.top, after.width, after.height) == frame


def test_think_cell_object_is_removed_from_a_refilled_slide(deck):
    prs, _, picture_id = deck
    slide = prs.slides[0]
    box = slide.shapes.add_textbox(Inches(0), Inches(0), Inches(1), Inches(1))
    box.name = "think-cell data - do not delete"
    F._replace_pictures(prs, {"pictures": {f"0:{picture_id}": _BLUE}})
    assert not [s for s in slide.shapes if "think-cell" in s.name.lower()]


def test_think_cell_survives_a_slide_we_did_not_refill(deck):
    prs, _, _ = deck
    box = prs.slides[0].shapes.add_textbox(Inches(0), Inches(0), Inches(1), Inches(1))
    box.name = "think-cell data - do not delete"
    F._replace_pictures(prs, {"pictures": {}})
    assert [s for s in prs.slides[0].shapes if "think-cell" in s.name.lower()]
```

- [ ] **Step 2: Run to verify it fails**

```
.venv/Scripts/python.exe -m pytest tests/test_fill_cell_and_picture.py -v
```
Expected: FAIL — `AttributeError: module 'studio.template_fill.fill' has no attribute '_fill_cell_backgrounds'`.

- [ ] **Step 3: Add both functions to `fill.py`**

Insert immediately before `def _apply_order(` (around line 1157, right after `_fill_charts`):

```python
# ── table-cell backgrounds ───────────────────────────────────────────────────


def _paint_cell(table, spec: Dict[str, Any]) -> None:
    """Paint one cell: a hex fills it solid, ``None`` clears it back to no fill."""
    from pptx.dml.color import RGBColor

    cell = table.cell(int(spec["r"]), int(spec["c"]))
    hexv = spec.get("hex")
    if hexv:
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor.from_string(str(hexv).lstrip("#").upper())
    else:
        cell.fill.background()


def _fill_cell_backgrounds(prs, values: Dict[str, Any]) -> None:
    """Paint table cells from the ``cell_fills`` payload, addressed by ``slide:shape``.

    The Carrier Survey table encodes each score's year-on-year move as the CELL COLOUR
    (:mod:`studio.template_fill.survey.bands`), which no text write can express — so the
    payload names the cells and their colours, and this writes them. Generic: any page can
    emit ``cell_fills``.
    """
    fills = values.get("cell_fills") or {}
    if not fills:
        return
    painted = 0
    for sidx, slide in enumerate(prs.slides):
        for sh in _iter_leaves(slide.shapes):
            specs = fills.get(f"{sidx}:{int(sh.shape_id)}")
            if not specs or not getattr(sh, "has_table", False):
                continue
            for spec in specs:
                try:
                    _paint_cell(sh.table, spec)
                    painted += 1
                except Exception as exc:  # noqa: BLE001 — one cell must not break the deck
                    logger.warning("template_fill: cell fill skipped (%s): %s", spec, exc)
    logger.info("template_fill: painted %d table cell(s)", painted)


# ── picture replacement ──────────────────────────────────────────────────────

_THINK_CELL = "think-cell"


def _drop_think_cell(slide) -> None:
    """Remove the think-cell data object from a slide whose picture we just replaced.

    The authored chart is a think-cell RENDER plus a hidden data object. Leaving the data
    behind means a viewer with think-cell installed can re-render the author's example
    numbers straight over the chart we just filled.
    """
    for sh in list(slide.shapes):
        if _THINK_CELL in str(getattr(sh, "name", "") or "").lower():
            sh._element.getparent().remove(sh._element)


def _swap_image(slide, shape, png: bytes) -> bool:
    """Point ``shape`` at ``png`` by replacing its image part's blob, keeping its frame."""
    rid = shape._element.blipFill.blip.rEmbed
    part = slide.part.related_part(rid)
    if "png" not in str(getattr(part, "content_type", "")).lower():
        logger.warning("template_fill: picture %s is not a PNG part; left as authored",
                       shape.shape_id)
        return False
    part._blob = png
    return True


def _replace_pictures(prs, values: Dict[str, Any]) -> None:
    """Swap picture images from the ``pictures`` payload, addressed by ``slide:shape``.

    Some authored visuals are images, not charts — the Carrier Survey ribbon is a pasted
    think-cell render — so the only way to fill them is to draw our own and put it in the
    same frame. PNG in, PNG out; the shape's position, size and crop are untouched.
    """
    pictures = values.get("pictures") or {}
    if not pictures:
        return
    swapped = 0
    for sidx, slide in enumerate(prs.slides):
        touched = False
        for sh in _iter_leaves(slide.shapes):
            png = pictures.get(f"{sidx}:{int(sh.shape_id)}")
            if not png or not hasattr(sh._element, "blipFill"):
                continue
            try:
                if _swap_image(slide, sh, png):
                    swapped += 1
                    touched = True
            except Exception as exc:  # noqa: BLE001 — a picture must never break the export
                logger.warning("template_fill: picture swap skipped (%s): %s", sh.shape_id, exc)
        if touched:
            _drop_think_cell(slide)
    logger.info("template_fill: replaced %d picture(s)", swapped)
```

- [ ] **Step 4: Wire them into `fill_template`**

In `fill_template`, replace the line `    _fill_charts(prs, values)` with:

```python
    _fill_charts(prs, values)
    _fill_cell_backgrounds(prs, values)
    _replace_pictures(prs, values)
```

- [ ] **Step 5: Run the tests**

```
.venv/Scripts/python.exe -m pytest tests/test_fill_cell_and_picture.py -v
```
Expected: PASS (8 tests).

- [ ] **Step 6: Confirm the engine still fills everything else**

```
.venv/Scripts/python.exe -m pytest tests/ -m "not e2e" -q
```
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add studio/template_fill/fill.py tests/test_fill_cell_and_picture.py
git commit -m "feat: fill engine can paint table cells and replace picture images"
```

---

### Task 6: The Carrier Survey page

**Files:**
- Create: `studio/template_fill/survey/page.py`
- Modify: `studio/template_fill/survey/__init__.py`, `studio/template_fill/sections.py`
- Test: `tests/test_survey_page.py`

**Interfaces:**
- Consumes: `bands.band_for` (Task 2), `ribbon.RibbonSpec` / `render_ribbon_png` / `available` (Task 3), `facts.load_grid` / `load_ribbon` (Task 4), the `cell_fills` / `pictures` payload keys (Task 5).
- Produces: `page.pages(template) -> List[SurveyPage]`, `page.augment(template, bindings) -> List[R.Binding]`, `page.values(template, result) -> Dict[str, Any]`, `page.ROLE_PREFIX = "survey:"`. Consumed by Task 7.

- [ ] **Step 1: Write the failing test**

Create `tests/test_survey_page.py`:

```python
"""The Carrier Survey page — detection against the REAL template, and its fill payload."""
from __future__ import annotations

import pytest

from studio import seed as S
from studio.template_fill import roles as R
from studio.template_fill.analyze import analyze
from studio.template_fill.sections import Section, section_of
from studio.template_fill.survey import page as P

_TEMPLATE = "template/survey_template.pptx"


@pytest.fixture(scope="module")
def template():
    return analyze(_TEMPLATE)


@pytest.fixture(scope="module")
def result():
    from studio.compute import OverallResult

    S.ensure_seed_db()
    return OverallResult(subject=S.SUBJECT, flow="gpr",
                         resolved_filters={"Country": "Singapore"})


def test_the_survey_slide_classifies_as_its_own_section(template):
    assert section_of(template.slides[0]) is Section.SURVEY


def test_other_templates_are_unaffected_by_the_new_section_rule():
    for name in ("overall", "country", "product"):
        for slide in analyze(f"template/{name}_template.pptx").slides:
            assert section_of(slide) is not Section.SURVEY


def test_page_detection_finds_the_table_axes_and_the_ribbon(template):
    pages = P.pages(template)
    assert len(pages) == 1
    page = pages[0]
    assert [label for _, label in page.rows] == S.SURVEY_SECTIONS
    assert [label for _, label in page.cols] == S.SURVEY_PRACTICES
    assert page.total_row is not None and page.total_col is not None
    assert page.ribbon_id is not None


def test_the_ribbon_is_the_taller_picture_not_the_legend(template):
    page = P.pages(template)[0]
    legend = min((sh for sh in template.slides[0].shapes if sh.kind == "picture"),
                 key=lambda sh: sh.h)
    assert page.ribbon_id != legend.shape_id


def test_augment_binds_every_data_cell(template):
    bound = P.augment(template, [])
    roles = {b.role for b in bound}
    page = P.pages(template)[0]
    # body + one total per row + one per column + the corner
    expected = len(page.rows) * len(page.cols) + len(page.rows) + len(page.cols) + 1
    assert len([r for r in roles if r and r.startswith(P.ROLE_PREFIX)]) == expected
    assert all(not b.placeholder for b in bound if str(b.role or "").startswith(P.ROLE_PREFIX))


def test_augment_is_idempotent(template):
    once = P.augment(template, [])
    twice = P.augment(template, list(once))
    assert len(twice) == len(once)


def test_values_fills_every_cell_and_emits_band_colours(template, result):
    values = P.values(template, result)
    page = P.pages(template)[0]
    for row, _ in page.rows:
        for col, _ in page.cols:
            assert P._role(page.slide_idx, row, col) in values
    fills = values["cell_fills"][f"{page.slide_idx}:{page.table_id}"]
    assert fills, "no cell colours computed"
    assert {f["hex"] for f in fills} - {None}, "every cell landed in the neutral band"
    assert all(f["hex"] is None or len(f["hex"]) == 6 for f in fills)


def test_values_renders_the_ribbon_picture(template, result):
    from studio.template_fill.survey import ribbon

    if not ribbon.available():
        pytest.skip("kaleido/Chrome not available on this host")
    values = P.values(template, result)
    page = P.pages(template)[0]
    png = values["pictures"][f"{page.slide_idx}:{page.ribbon_id}"]
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_values_survives_a_broken_renderer(template, result, monkeypatch):
    """A dead renderer must cost the CHART only — the table still fills."""
    from studio.template_fill.survey import ribbon

    monkeypatch.setattr(ribbon, "render_ribbon_png",
                        lambda spec: (_ for _ in ()).throw(RuntimeError("no chrome")))
    values = P.values(template, result)
    assert not values.get("pictures")
    assert values.get("cell_fills")


def test_values_is_empty_for_a_country_with_no_survey(template):
    from studio.compute import OverallResult

    result = OverallResult(subject=S.SUBJECT, flow="gpr",
                           resolved_filters={"Country": "Atlantis"})
    assert P.values(template, result) == {}


def test_values_is_empty_for_a_template_without_a_survey_page(result):
    assert P.values(analyze("template/country_template.pptx"), result) == {}
```

- [ ] **Step 2: Run to verify it fails**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_page.py -v
```
Expected: FAIL — `ImportError: cannot import name 'page'`.

- [ ] **Step 3: Teach `sections.py` about the survey page**

In `studio/template_fill/sections.py`, add to the `Section` enum, after `FEEDBACK`:

```python
    SURVEY = "survey"
```

And add as the FIRST entry of `_TITLE_RULES` (it is the most specific cue on the page and collides with nothing):

```python
    (("carrier survey", "survey"), Section.SURVEY),
```

- [ ] **Step 4: Write `page.py`**

```python
"""The Carrier Survey page — detection, slot binding, and the fill payload.

The author's page has two things the generic slot/role path cannot fill:

  * the **score table** — an 8x9 grid of ``x.x`` placeholders whose ROW is a survey
    section and whose COLUMN is a practice, and whose BACKGROUND encodes the score's move
    against last year (the legend the author pasted below it);
  * the **ribbon chart** — a pasted think-cell render, so there is no chart to refill; we
    draw our own PNG and swap the picture's image.

Mirrors :mod:`studio.template_fill.gwp_page`: ``augment`` re-binds the slots, ``values``
computes the texts (plus the ``cell_fills`` and ``pictures`` payloads the fill engine
consumes), and detection is header/geometry driven — never a slide index — so the page
keeps filling if it is moved, restyled or duplicated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from studio.template_fill import roles as R
from studio.template_fill.analyze import Slide, Template
from studio.template_fill.sections import Section, section_of
from studio.template_fill.slots import Slot, classify
from studio.template_fill.survey import bands, facts
from studio.template_fill.survey import ribbon as ribbon_mod

logger = get_logger(__name__)

ROLE_PREFIX = "survey:"

_TOTAL = "total"
_SECTION_HEADER = "section"
# Any dash the author might have typed (U+2010..U+2015 plus the minus sign), normalised so
# "Claims – Claims Professionals" matches the data's own label whichever dash each side used.
# Written as escapes on purpose — the dashes are indistinguishable in most editors.
_DASHES = re.compile("[\u2010-\u2015\u2212]")


def _norm(text: str) -> str:
    """Case/space/dash-insensitive form for header matching."""
    return _DASHES.sub("-", " ".join((text or "").split())).strip().lower()


# ── page anatomy ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SurveyPage:
    """One Carrier Survey page: its score table's axes and its ribbon picture."""

    slide_idx: int
    table_id: int
    rows: Tuple[Tuple[int, str], ...] = ()      # (row index, section label) — no Total
    cols: Tuple[Tuple[int, str], ...] = ()      # (col index, practice label) — no Total
    total_row: Optional[int] = None
    total_col: Optional[int] = None
    ribbon_id: Optional[int] = None


def _score_table(slide: Slide) -> Optional[Tuple[int, List[List[str]]]]:
    """The score table — the one whose top-left header names the section axis."""
    for sh in slide.shapes:
        table = sh.table if sh.kind == "table" else None
        if table and len(table) > 1 and table[0] and _SECTION_HEADER in _norm(table[0][0]):
            return sh.shape_id, table
    return None


def _axis(labels: List[str]) -> Tuple[Tuple[Tuple[int, str], ...], Optional[int]]:
    """Split an axis's labels into ``((index, label) …, the Total index)``.

    Index 0 is the axis's own header cell, never a data label.
    """
    entries: List[Tuple[int, str]] = []
    total: Optional[int] = None
    for i, raw in enumerate(labels):
        if i == 0:
            continue
        label = " ".join((raw or "").split())
        if not label:
            continue
        if _norm(label) == _TOTAL:
            total = i
        else:
            entries.append((i, label))
    return tuple(entries), total


def _ribbon_id(slide: Slide) -> Optional[int]:
    """The ribbon picture — the TALLEST picture on the page.

    The slide carries two: the banding legend (a thin colour strip) and the chart. Height
    separates them by an order of magnitude, so no caption matching is needed.
    """
    pictures = [sh for sh in slide.shapes if sh.kind == "picture"]
    return max(pictures, key=lambda sh: sh.h).shape_id if pictures else None


def _page_of(slide: Slide) -> Optional[SurveyPage]:
    found = _score_table(slide)
    if found is None:
        return None
    table_id, table = found
    rows, total_row = _axis([row[0] if row else "" for row in table])
    cols, total_col = _axis(list(table[0]))
    if not rows or not cols:
        return None
    return SurveyPage(slide_idx=slide.index, table_id=table_id, rows=rows, cols=cols,
                      total_row=total_row, total_col=total_col, ribbon_id=_ribbon_id(slide))


def pages(template: Template) -> List[SurveyPage]:
    """Every Carrier Survey page in ``template``, with its fillable parts located."""
    found = (_page_of(s) for s in template.slides if section_of(s) is Section.SURVEY)
    return [p for p in found if p is not None]


# ── binding ──────────────────────────────────────────────────────────────────


def _role(slide_idx: int, row: int, col: int) -> str:
    return f"{ROLE_PREFIX}{slide_idx}:{row}:{col}"


def _cells(page: SurveyPage) -> List[Tuple[int, int]]:
    """Every data cell on the page: the body, both Total axes, and the corner."""
    rows = [r for r, _ in page.rows] + ([page.total_row] if page.total_row is not None else [])
    cols = [c for c, _ in page.cols] + ([page.total_col] if page.total_col is not None else [])
    return [(r, c) for r in rows for c in cols]


def _token_at(template: Template, page: SurveyPage, row: int, col: int) -> str:
    sh = template.shape(page.slide_idx, page.table_id)
    if sh is None or not sh.table or row >= len(sh.table) or col >= len(sh.table[row]):
        return ""
    return sh.table[row][col]


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Bind every Carrier Survey data cell to its ``survey:`` role (idempotent)."""
    by_key = {b.slot.key: b for b in bindings}
    extra: List[R.Binding] = []
    n = 0
    for page in pages(template):
        for row, col in _cells(page):
            where = ["cell", row, col]
            token = _token_at(template, page, row, col)
            role = _role(page.slide_idx, row, col)
            existing = by_key.get(Slot(page.slide_idx, page.table_id, where, "", "text", "").key)
            if existing is not None:
                existing.role, existing.placeholder = role, False
            else:
                extra.append(R.Binding(
                    slot=Slot(page.slide_idx, page.table_id, where, token,
                              classify(token) or "text", ""),
                    role=role, placeholder=False))
            n += 1
    if n:
        logger.info("survey_page: bound %d cell(s) (%d added)", n, len(extra))
    return bindings + extra


# ── values ───────────────────────────────────────────────────────────────────

_COUNTRY_FILTER = "Country"


def _country_of(result) -> Optional[str]:
    """The single country this sub-deck is for — the survey page is always per-country."""
    value = (getattr(result, "resolved_filters", None) or {}).get(_COUNTRY_FILTER)
    values = list(value) if isinstance(value, (list, tuple, set)) else ([value] if value else [])
    named = [str(v) for v in values if v not in (None, "", "all", "All")]
    return named[0] if len(named) == 1 else None


def _reading(grid: facts.ScoreGrid, page: SurveyPage,
             row: int, col: int) -> Tuple[Optional[float], Optional[float]]:
    """``(score, Δ vs prior year)`` for one cell, whichever axis(es) it totals."""
    sections = dict(page.rows)
    practices = dict(page.cols)
    is_total_row = row == page.total_row
    is_total_col = col == page.total_col
    if is_total_row and is_total_col:
        return grid.overall, grid.overall_delta()
    if is_total_row:
        practice = practices[col]
        return grid.practice_total(practice), grid.practice_total_delta(practice)
    if is_total_col:
        section = sections[row]
        return grid.section_total(section), grid.section_total_delta(section)
    section, practice = sections[row], practices[col]
    return grid.score(section, practice), grid.delta(section, practice)


def _table_payload(page: SurveyPage,
                   grid: facts.ScoreGrid) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """``({role: score}, [{r, c, hex}])`` — the numbers and the colours behind them.

    A cell with no score is left out entirely: it keeps the template's own ``x.x`` and
    takes no colour, which reads as "not surveyed" rather than as a real zero.
    """
    texts: Dict[str, Any] = {}
    fills: List[Dict[str, Any]] = []
    for row, col in _cells(page):
        score, delta = _reading(grid, page, row, col)
        if score is None:
            continue
        texts[_role(page.slide_idx, row, col)] = float(score)
        fills.append({"r": row, "c": col, "hex": bands.band_for(delta)})
    return texts, fills


def _ribbon_png(page: SurveyPage, result, country: str) -> Optional[bytes]:
    """The ribbon image for this page, or ``None`` — a dead renderer costs the CHART only.

    The authored picture then stays, which is a visibly stale chart rather than a broken
    deck; the table above it is filled either way.
    """
    if page.ribbon_id is None or not ribbon_mod.available():
        return None
    spec = facts.load_ribbon(result, country, tuple(label for _, label in page.rows))
    if spec is None or not spec.columns:
        return None
    try:
        return ribbon_mod.render_ribbon_png(spec)
    except Exception as exc:  # noqa: BLE001 — no renderer must not cost us the table
        logger.warning("survey_page: ribbon render failed (%s); keeping the authored picture", exc)
        return None


def values(template: Template, result) -> Dict[str, Any]:
    """``{survey-role: score}`` plus the ``cell_fills`` and ``pictures`` payloads.

    Empty when the template has no survey page, when the sub-deck is not scoped to exactly
    one country, or when that country has no survey book — in every case the slide is
    simply not generated (see :func:`studio.template_fill.assemble.plan_subdecks`).
    """
    found = pages(template)
    if not found:
        return {}
    country = _country_of(result)
    if country is None:
        return {}
    grid = facts.load_grid(result, country)
    if grid is None:
        return {}

    out: Dict[str, Any] = {}
    cell_fills: Dict[str, Any] = {}
    pictures: Dict[str, Any] = {}
    for page in found:
        texts, fills = _table_payload(page, grid)
        out.update(texts)
        if fills:
            cell_fills[f"{page.slide_idx}:{page.table_id}"] = fills
        png = _ribbon_png(page, result, country)
        if png:
            pictures[f"{page.slide_idx}:{page.ribbon_id}"] = png
    if cell_fills:
        out["cell_fills"] = cell_fills
    if pictures:
        out["pictures"] = pictures
    logger.info("survey_page: %s %d — %d cell(s), %d chart(s)",
                country, grid.year, len(out), len(pictures))
    return out
```

- [ ] **Step 5: Run the tests**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_page.py tests/test_survey_bands.py tests/test_survey_facts.py tests/test_survey_ribbon.py -v
```
Expected: PASS.

- [ ] **Step 6: Check the new section rule broke nothing**

```
.venv/Scripts/python.exe -m pytest tests/ -m "not e2e" -q
```
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add studio/template_fill/survey/ studio/template_fill/sections.py tests/test_survey_page.py
git commit -m "feat: fill the Carrier Survey table and ribbon from real survey data"
```

---

### Task 7: Wire the survey axis into assembly

**Files:**
- Create: `studio/template_fill/maps/survey.json`
- Modify: `studio/template_fill/assemble.py`, `studio/authoring/generate.py`, `studio/page/authoring/setup.py`
- Test: `tests/test_survey_assemble.py`

**Interfaces:**
- Consumes: `survey.page.augment` / `survey.page.values` (Task 6), `survey.facts.has_survey_data` (Task 4).
- Produces: `assemble.SURVEY = "survey"`; `assemble.plan_subdecks(result, *, scope=None, data_basis=None)`; `assemble.assemble_deck(result, *, out_path=None, work_dir=None, scope=None, data_basis=None)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_survey_assemble.py`:

```python
"""Where the Carrier Survey slide lands, and when it is generated at all.

Hermetic, like ``test_template_assemble.py``: tiny in-memory templates and stubbed
resolvers, so it proves the COMPOSITION without a warehouse.
"""
from __future__ import annotations

import pytest
from pptx import Presentation
from pptx.util import Inches

from studio import compute as C
from studio.template_fill import assemble as A
from studio.template_fill import binding_map as BM


@pytest.fixture(autouse=True)
def _force_opc_merge(monkeypatch):
    monkeypatch.setenv("STUDIO_PPT_MERGE_ENGINE", "opc")


def _tiny(path: str, n: int) -> str:
    prs = Presentation()
    for i in range(n):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text_frame.text = f"s{i}"
    prs.save(path)
    return path


@pytest.fixture
def axes(tmp_path, monkeypatch):
    BM._REGISTRY.clear()
    BM.get_binding_map.cache_clear()
    for name, n in (("overall", 2), ("country", 5), ("survey", 1), ("end", 1)):
        path = _tiny(str(tmp_path / f"{name}.pptx"), n)
        BM._REGISTRY[name] = (lambda name=name, path=path: BM.BindingMap(name, path, ()))
    monkeypatch.setattr(BM, "_discover_json_maps", lambda: None)
    monkeypatch.setattr(A, "resolve_roles", lambda r: {})
    monkeypatch.setattr(A, "resolve_roles_for_product", lambda r, p: {})
    monkeypatch.setattr(A, "resolve_roles_for_country", lambda r, c: {})
    monkeypatch.setattr(A.survey_facts, "has_survey_data", lambda r, c: c != "Atlantis")
    yield
    BM._REGISTRY.clear()
    BM.get_binding_map.cache_clear()


def _result(countries=("Singapore", "Japan")):
    return C.OverallResult(subject="Zurich", flow="gpr",
                           resolved_filters={"Country": tuple(countries)})


def test_premium_only_generates_no_survey_slide(axes):
    decks = A.plan_subdecks(_result(), data_basis="premium")
    assert "survey" not in [d.template for d in decks]


def test_omitting_data_basis_keeps_todays_deck(axes):
    assert "survey" not in [d.template for d in A.plan_subdecks(_result())]


def test_survey_follows_each_country_block(axes):
    decks = A.plan_subdecks(_result(), data_basis="premium_survey")
    assert [d.template for d in decks] == [
        "overall", "country", "survey", "country", "survey", "end"]


def test_the_survey_deck_is_labelled_and_scoped_to_its_country(axes):
    decks = A.plan_subdecks(_result(), data_basis="premium_survey")
    surveys = [d for d in decks if d.template == "survey"]
    assert [d.label for d in surveys] == ["Singapore survey", "Japan survey"]
    assert surveys[0].values["country_name[0]"] == "Singapore"


def test_a_country_with_no_survey_book_is_skipped(axes):
    decks = A.plan_subdecks(_result(("Singapore", "Atlantis")), data_basis="premium_survey")
    assert [d.template for d in decks] == ["overall", "country", "survey", "country", "end"]


def test_an_overall_only_scope_generates_no_survey_slide(axes):
    decks = A.plan_subdecks(_result(), scope="overall", data_basis="premium_survey")
    assert [d.template for d in decks] == ["overall", "end"]


def test_the_merged_deck_has_six_slides_per_country(axes, tmp_path):
    out = A.assemble_deck(_result(), out_path=str(tmp_path / "deck.pptx"),
                          work_dir=str(tmp_path / "work"), data_basis="premium_survey")
    # overall(2) + 2 x (country 5 + survey 1) + end(1)
    assert len(Presentation(out).slides._sldIdLst) == 15


def test_generate_passes_the_selection_s_data_basis_through():
    from pathlib import Path

    src = Path("studio/authoring/generate.py").read_text(encoding="utf-8")
    assert 'data_basis=selection.get("data_basis")' in src
```

- [ ] **Step 2: Run to verify it fails**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_assemble.py -v
```
Expected: FAIL — `AttributeError: module 'studio.template_fill.assemble' has no attribute 'survey_facts'`.

- [ ] **Step 3: Register the survey template**

Create `studio/template_fill/maps/survey.json`:

```json
{
  "name": "survey",
  "path": "template/survey_template.pptx",
  "bindings": []
}
```

The bindings are deliberately empty: every cell on this page is recognised dynamically by
`survey.page.augment`, so re-authoring the template cannot invalidate a hand-maintained map.

- [ ] **Step 4: Add the survey axis to `assemble.py`**

Add to the imports:

```python
from studio.template_fill.survey import facts as survey_facts
from studio.template_fill.survey import page as survey_page
```

Add the axis constant after `END = "end"`:

```python
# The Carrier Survey page. NOT a member of _SCOPE_AXES: it is not a scope choice but a
# DATA BASIS one — the Setup form's "Premium + survey" — so it is gated separately, and
# rides along with whichever country blocks the chosen scope already builds.
SURVEY = "survey"
DATA_BASIS_WITH_SURVEY = "premium_survey"
```

Add the provider tuples just above `_build_subdeck`:

```python
# What each sub-deck's values are enriched with, in order. The survey page shares none of
# the premium providers — its numbers come from a different book entirely — so giving it
# its own list keeps it off five queries that could only ever return nothing.
_PREMIUM_PROVIDERS = (grids.grid_values, gwp_page.values, lc_page.values,
                      feedback.values, commentary.values)
_SURVEY_PROVIDERS = (survey_page.values,)
```

Change `_build_subdeck`'s signature and its provider loop:

```python
def _build_subdeck(template_name: str, scoped_result, values: Dict[str, Any], label: str,
                   *, providers=_PREMIUM_PROVIDERS) -> SubDeck:
```

and inside it replace

```python
        for provider in (grids.grid_values, gwp_page.values, lc_page.values,
                         feedback.values, commentary.values):
```

with

```python
        for provider in providers:
```

- [ ] **Step 5: Plan the survey sub-decks**

Change `plan_subdecks`'s signature to:

```python
def plan_subdecks(result, *, scope: Optional[str] = None,
                  data_basis: Optional[str] = None) -> List[SubDeck]:
```

and add to its docstring, after the ``scope`` paragraph:

```
    ``data_basis`` (the Setup form's DATA BASIS control) decides whether each country block
    is followed by its Carrier Survey page. Only ``"premium_survey"`` generates it, and only
    for a country that actually has a survey book — the rest keep today's five-slide block.
```

Add near the top of the body, after `countries = ...`:

```python
    want_survey = (str(data_basis or "") == DATA_BASIS_WITH_SURVEY
                   and SURVEY in names and want_countries)
```

Replace the country loop with:

```python
    for country in countries:
        decks.append(_build_subdeck(COUNTRY, scope_to_country(result, country),
                                    with_context(resolve_roles_for_country(result, country)),
                                    str(country)))
        if want_survey and survey_facts.has_survey_data(result, country):
            decks.append(_build_subdeck(
                SURVEY, scope_to_country(result, country),
                # The page needs no premium roles — only its own country label, which the
                # fill engine's "Country (1)" substitution reads.
                {"country_name[0]": str(country)}, f"{country} survey",
                providers=_SURVEY_PROVIDERS))
```

- [ ] **Step 6: Register the page's augmenter and thread `data_basis` through**

In `_augmented_manifest`, add `survey_page.augment` to the augment tuple (it no-ops on
every template without a survey page, and the manifest is cached per template file):

```python
        for augment in (grids.augment, gwp_page.augment, kpi_band.augment,
                        commentary.augment, feedback.augment, survey_page.augment):
```

Add it to that function's docstring bullet list:

```
      * ``survey_page.augment`` — the Carrier Survey table's score cells.
```

Change `assemble_deck`:

```python
def assemble_deck(result, *, out_path: Optional[str] = None, work_dir: Optional[str] = None,
                  scope: Optional[str] = None, data_basis: Optional[str] = None) -> str:
```

and its first body line:

```python
    decks = plan_subdecks(result, scope=scope, data_basis=data_basis)
```

- [ ] **Step 7: Pass the selection's data basis from the app**

In `studio/authoring/generate.py`, change line 219 to:

```python
    return assemble_deck(result, out_path=str(out), scope=selection.get("template_scope"),
                         data_basis=selection.get("data_basis"))
```

- [ ] **Step 8: Retire the Setup placeholder note**

In `studio/page/authoring/setup.py`, in `_data_basis_control`, delete the `html.Div` with
the "Survey pages are not generated yet" text, leaving:

```python
    return html.Div(
        [_radio_field("DATA BASIS", "studio-data-basis",
                      list(DATA_BASIS_OPTIONS), DATA_BASIS_DEFAULT)],
        className="qs-basis-field",
    )
```

and update the module comment above `DATA_BASIS_DEFAULT` (lines 238-240) to:

```python
# Which books the deck draws on. "premium_survey" appends a Carrier Survey page to each
# country block (see studio.template_fill.assemble.plan_subdecks).
```

- [ ] **Step 9: Run the tests**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_assemble.py tests/test_template_assemble.py tests/test_studio_setup_form.py -v
```
Expected: PASS.

- [ ] **Step 10: Full non-e2e sweep**

```
.venv/Scripts/python.exe -m pytest tests/ -m "not e2e" -q
```
Expected: no new failures.

- [ ] **Step 11: Commit**

```bash
git add studio/template_fill/assemble.py studio/template_fill/maps/survey.json studio/authoring/generate.py studio/page/authoring/setup.py tests/test_survey_assemble.py
git commit -m "feat: append the Carrier Survey page per country on the premium+survey basis"
```

---

### Task 8: End-to-end

Proves the real workflow: a Setup selection → the exported `.pptx` a user opens.

**Files:**
- Create: `tests/test_survey_end_to_end.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7.

- [ ] **Step 1: Write the test**

Create `tests/test_survey_end_to_end.py`:

```python
"""End-to-end: a Premium + survey selection → the assembled deck's Carrier Survey pages.

Runs the REAL pipeline over the REAL templates against the seed DB:

    selection → compute_overall → per-country sub-decks (+ survey) → fill (cells · colours
              · ribbon) → merge → one deck

then reads the exported file back. Deterministic: seed DB, no LLM.

    pytest -m "not e2e"      # skip
"""
from __future__ import annotations

import pytest
from pptx import Presentation

from studio import seed as S
from studio.compute import compute_overall
from studio.template_fill.assemble import assemble_deck, plan_subdecks

pytestmark = pytest.mark.e2e

_SELECTION = {"carrier": "Zurich", "country": ["Singapore", "Japan"], "year": 2025}


@pytest.fixture(scope="module")
def result():
    S.ensure_seed_db()
    out = compute_overall(filters=_SELECTION)
    assert out.subject == "Zurich"
    return out


@pytest.fixture(scope="module")
def survey_deck(result, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("survey_e2e")
    path = assemble_deck(result, out_path=str(tmp / "deck.pptx"),
                         work_dir=str(tmp / "work"), data_basis="premium_survey")
    return path


def _survey_slides(path):
    """Every slide in the exported deck whose title is the Carrier Survey page."""
    prs = Presentation(path)
    out = []
    for slide in prs.slides:
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        if any("carrier survey" in t.lower() for t in texts):
            out.append(slide)
    return out


def test_one_survey_page_per_selected_country(survey_deck):
    assert len(_survey_slides(survey_deck)) == len(_SELECTION["country"])


def test_each_survey_page_follows_its_own_country_block(result, tmp_path):
    axes = [d.template for d in plan_subdecks(result, data_basis="premium_survey")]
    assert axes == ["overall", "country", "survey", "country", "survey", "end"]


def test_the_survey_page_is_titled_for_its_country(survey_deck):
    titles = []
    for slide in _survey_slides(survey_deck):
        titles.extend(sh.text_frame.text.strip() for sh in slide.shapes if sh.has_text_frame)
    for country in _SELECTION["country"]:
        assert country in titles
    assert "Country (1)" not in titles


def test_no_x_placeholder_survives_in_the_score_table(survey_deck):
    for slide in _survey_slides(survey_deck):
        for shape in slide.shapes:
            if not shape.has_table:
                continue
            cells = [shape.table.cell(r, c).text
                     for r in range(len(shape.table.rows))
                     for c in range(len(shape.table.columns))]
            assert "x.x" not in cells


def test_the_scores_are_real_numbers_on_the_survey_scale(survey_deck):
    for slide in _survey_slides(survey_deck):
        for shape in slide.shapes:
            if not shape.has_table:
                continue
            for r in range(1, len(shape.table.rows)):
                for c in range(1, len(shape.table.columns)):
                    value = float(shape.table.cell(r, c).text)
                    assert 1.0 <= value <= 10.0


def test_cells_are_coloured_by_their_move_against_last_year(survey_deck):
    from studio.template_fill.survey import bands

    legend = {bands.RED, bands.AMBER, bands.CREAM, bands.LIGHT_GREEN,
              bands.GREEN, bands.DARK_GREEN}
    seen = set()
    for slide in _survey_slides(survey_deck):
        for shape in slide.shapes:
            if not shape.has_table:
                continue
            for r in range(1, len(shape.table.rows)):
                for c in range(1, len(shape.table.columns)):
                    cell = shape.table.cell(r, c)
                    try:
                        seen.add(str(cell.fill.fore_color.rgb))
                    except (AttributeError, TypeError):
                        pass          # an unfilled (neutral-band) cell
    assert seen & legend, "no cell took a band colour"
    assert seen <= legend, f"unexpected colours on the page: {seen - legend}"
    assert len(seen & legend) >= 3, "the seeded drifts should span several bands"


def test_the_ribbon_picture_is_ours_not_the_authored_one(survey_deck):
    from studio.template_fill.survey import ribbon

    if not ribbon.available():
        pytest.skip("kaleido/Chrome not available on this host")
    authored = Presentation("template/survey_template.pptx").slides[0]
    original = max((sh for sh in authored.shapes if sh.shape_type == 13),
                   key=lambda sh: sh.height).image.blob
    for slide in _survey_slides(survey_deck):
        pictures = [sh for sh in slide.shapes if sh.shape_type == 13]
        biggest = max(pictures, key=lambda sh: sh.height)
        assert biggest.image.blob != original


def test_the_think_cell_object_is_gone_from_the_filled_page(survey_deck):
    from studio.template_fill.survey import ribbon

    if not ribbon.available():
        pytest.skip("kaleido/Chrome not available on this host")
    for slide in _survey_slides(survey_deck):
        assert not [sh for sh in slide.shapes if "think-cell" in (sh.name or "").lower()]


def test_no_peer_carrier_is_named_anywhere_on_the_page(survey_deck):
    peers = [c for c in S.CARRIERS if c != "Zurich"]
    for slide in _survey_slides(survey_deck):
        blocks = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        for shape in slide.shapes:
            if shape.has_table:
                blocks.extend(shape.table.cell(r, c).text
                              for r in range(len(shape.table.rows))
                              for c in range(len(shape.table.columns)))
        text = " ".join(blocks)
        for peer in peers:
            assert peer not in text


# ── regression: the premium-only deck must be untouched ──────────────────────


def test_premium_only_deck_is_unchanged_by_this_feature(result, survey_deck, tmp_path):
    """The premium deck carries no survey page, and the survey deck adds EXACTLY one
    slide per country to it — derived from the two decks, so neither count is hardcoded
    against a template that may gain or lose slides for unrelated reasons."""
    premium = assemble_deck(result, out_path=str(tmp_path / "premium.pptx"),
                            work_dir=str(tmp_path / "w1"), data_basis="premium")
    assert not _survey_slides(premium)
    premium_n = len(Presentation(premium).slides._sldIdLst)
    survey_n = len(Presentation(survey_deck).slides._sldIdLst)
    assert survey_n - premium_n == len(_SELECTION["country"])


def test_default_data_basis_still_produces_the_premium_deck(result, tmp_path):
    default = assemble_deck(result, out_path=str(tmp_path / "default.pptx"),
                            work_dir=str(tmp_path / "w2"))
    assert not _survey_slides(default)
```

- [ ] **Step 2: Run it**

```
.venv/Scripts/python.exe -m pytest tests/test_survey_end_to_end.py -v
```
Expected: PASS. Both counts in `test_premium_only_deck_is_unchanged_by_this_feature` are
derived from the two decks it builds, so a template that gains or loses slides for unrelated
reasons cannot make it fail. If it DOES fail, the delta is wrong — that is a real defect in
this feature, not a number to adjust. Never relax it to make it pass.

- [ ] **Step 3: Run the whole suite, e2e included**

```
.venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: PASS, including the pre-existing `tests/test_template_end_to_end.py`.

- [ ] **Step 4: Look at the actual deck**

```
.venv/Scripts/python.exe -c "
from studio import seed as S
from studio.compute import compute_overall
from studio.template_fill.assemble import assemble_deck
S.ensure_seed_db()
r = compute_overall(filters={'carrier':'Zurich','country':['Singapore','Japan'],'year':2025})
print(assemble_deck(r, out_path='survey_check.pptx', data_basis='premium_survey'))
"
```

Open `survey_check.pptx` and confirm on each survey page: the subtitle names the country;
every table cell has a one-decimal score; the colours vary and match the legend strip below
the table; the ribbon shows section names on the x-axis with one blue thread. Delete the
file afterwards.

- [ ] **Step 5: Commit**

```bash
git add tests/test_survey_end_to_end.py
git commit -m "test: end-to-end coverage for the Carrier Survey page"
```

---

## Self-Review Notes

Spec coverage check, section by section:

| spec section | task |
|---|---|
| §2 Placement (per-country, gated on data basis) | 7 |
| §3 Modules (`bands`/`ribbon`/`facts`/`page`, minimal `survey.json`) | 2, 3, 4, 6, 7 |
| §4 `_fill_cell_backgrounds`, `_replace_pictures`, think-cell removal | 5 |
| §5 Table: fixed axes, four cuts, 1 dp, scope, banding | 4, 6 |
| §6 Ribbon: section axis, ranking, cap 9, colours, no names, title | 3, 4 |
| §7 kaleido dependency + graceful degrade | 3, 6 |
| §8 Seed data | 1 |
| §9 Testing (unit / integration / e2e / failure paths) | every task; 8 for e2e |
| §10 Setup page note removal | 7 |

Known risks the implementer should watch for:

1. **The section column name.** `flows.yaml` says `Sections` in one place and `Section` in
   another, and the live warehouse was never inspected. `facts.section_column` resolves it
   against the real table. If BOTH are absent in production, `has_survey_data` returns
   False and no survey slide is generated — a quiet, safe failure. Log a warning if that
   happens in a live run.
2. **`Section.SURVEY` is a new classification.** Task 6 Step 7 exists to catch any slide in
   another template that the new title rule steals. As of writing there is none.
3. **kaleido needs a browser.** Present on the dev machine. On a host without one the page
   degrades to the authored picture; that is tested, but it means a stale-looking chart
   rather than a loud failure. If that trade is wrong for production, change
   `_ribbon_png` to re-raise.
