"""Data mode — upload, HITL column mapping, KPI capture, shape & pivot.

The custom-data workflow: upload → **review the proposed mapping** (every column
arrives with a suggested target and an editable description) → declare KPIs for
metric columns that match nothing canonical → submit → "Use for the deck" returns
to Setup with this data governing generation.

The page is built as a three-step pipeline (upload · map · use), so at any moment
the screen says which step you are on and what is still missing. Mapping rows are
cards: what the column IS on the left, where it goes on the right, and a badge
saying whether the machine proposed it or you did.

Pure layout: the live callbacks live in ``studio.authoring.data``; the proposals
themselves come from ``studio.dataset.automap``. The saved dataset list and the
active dataset's frame are read server-side from the repository.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import dash_ag_grid as dag
from dash import dcc, html

from studio.dataset.automap import SOURCE_LABEL, is_proposed
from studio.page.authoring import data_queue as Q
from studio.dataset.ingest import SUPPORTED_EXTENSIONS
from studio.dataset.model import (
    REQUIRED_TARGETS,
    ColumnMapping,
    ColumnProfile,
    CustomMeasure,
    DatasetRecord,
    premium_mapped,
)

# The PIVOT builder stays parked (the column tools are live — see ``_columns_section``).
# Its engine (studio/dataset/pivot.py) is kept and tested; flip this to True and
# re-register the parked callback in studio/authoring/data.py to restore it.
PIVOT_ENABLED = False
SHAPE_TOOLS_ENABLED = PIVOT_ENABLED      # kept for backward-compat imports

_PREVIEW_ROWS = 500  # grid preview cap — plenty to eyeball, cheap to ship to the browser

# Uploaded-column kind → (icon, label) for the type pill on a mapping row.
_KIND_META = {"number": ("bi-123", "Number"), "text": ("bi-fonts", "Text"),
              "date": ("bi-calendar3", "Date")}

_AGG_OPTIONS = [{"label": "Sum", "value": "sum"}, {"label": "Average", "value": "avg"},
                {"label": "Count", "value": "count"}]
_FMT_OPTIONS = [{"label": "Number", "value": "number"}, {"label": "Currency", "value": "currency"},
                {"label": "Percent", "value": "percent"}]

# Dataset status → (chip label, chip tone).
_STATUS_CHIP = {"uploaded": ("Needs review", "todo"), "mapped": ("Mapped", "ok"),
                "submitted": ("In use", "live")}


# ── canonical mapping targets (from the flow registry) ───────────────────────


@lru_cache(maxsize=1)
def _target_options() -> Tuple[Mapping[str, str], ...]:
    """Canonical GPR columns a user column can map onto — entity, temporal, measure.

    Cached: the registry is static for the process, and this is read once per mapping
    row — a 40-column upload rebuilt the same list forty times per render.
    """
    from core.registry import get_flow_registry

    spec = get_flow_registry().get("gpr")
    if spec is None:
        return ()
    cols = [c for c in spec.columns.values() if c.role in {"entity", "temporal", "measure"}]
    return tuple({"label": c.name.replace("_", " "), "value": c.name} for c in cols)


def _target_description(target: str) -> str:
    """The registry's definition for a canonical column (the description seed)."""
    from core.registry import get_flow_registry

    spec = get_flow_registry().get("gpr")
    col = spec.column(target) if (spec and target) else None
    return col.definition if col else ""


# ── the three-step pipeline header ───────────────────────────────────────────


def _step(number: int, title: str, state: str) -> html.Div:
    """One node of the stepper: done (a tick), active (numbered, lit) or still to come."""
    mark = html.I(className="bi bi-check-lg") if state == "done" else str(number)
    return html.Div([html.Span(mark, className="qs-step-mark"),
                     html.Span(title, className="qs-step-title")],
                    className=f"qs-step is-{state}")


def _step_states(record: Optional[DatasetRecord]) -> Tuple[str, str, str]:
    """Which of upload / map / use is done, which is the one to act on."""
    if record is None:
        return "active", "todo", "todo"
    if record.status == "submitted":
        return "done", "done", "done"
    if record.status == "mapped":
        return "done", "done", "active"
    return "done", "active", "todo"


def _pipeline(record: Optional[DatasetRecord]) -> html.Div:
    upload, mapping, use = _step_states(record)
    return html.Div(
        [
            _step(1, "Upload", upload),
            html.Span(className="qs-step-link"),
            _step(2, "Map columns", mapping),
            html.Span(className="qs-step-link"),
            _step(3, "Use for deck", use),
        ],
        className="qs-pipeline qs8-steps",
    )


# ── upload + saved datasets (the aside) ──────────────────────────────────────


def _upload_zone() -> html.Div:
    return html.Div(
        [
            html.Div([html.I(className="bi bi-cloud-arrow-up"), "Upload data"], className="qs-preview-head"),
            dcc.Upload(
                id="qs-data-upload",
                children=html.Div(
                    [
                        html.I(className="bi bi-file-earmark-spreadsheet qs-data-drop-icon"),
                        html.Div("Drop a spreadsheet here", className="qs-data-drop-title"),
                        html.Div(
                            f"or click to browse — {', '.join(SUPPORTED_EXTENSIONS)}, up to 1M rows",
                            className="qs-data-drop-sub",
                        ),
                    ],
                    className="qs-data-drop-inner",
                ),
                # Filter the OS file picker to what we can actually parse, so a wrong
                # type is caught before the round trip rather than after it.
                accept=",".join(SUPPORTED_EXTENSIONS),
                multiple=False,
                className="qs-data-drop",
            ),
            html.Div(id="qs-data-upload-msg", className="qs-data-upload-msg"),
        ],
        className="qs-scope-preview",
    )


def _dataset_row(record: DatasetRecord, active: bool) -> html.Div:
    label, tone = _STATUS_CHIP.get(record.status, (record.status, "todo"))
    return html.Div(
        [
            html.Button(
                [
                    html.I(className="bi bi-table qs-ds-icon"),
                    html.Div(
                        [
                            html.Div(record.name, className="qs-ds-name"),
                            html.Div(f"{record.n_rows:,} rows · {record.n_cols} cols",
                                     className="qs-ds-sub"),
                        ],
                        className="qs-ds-text",
                    ),
                    html.Span(label, className=f"qs-ds-chip {tone}"),
                ],
                id={"type": "qs-ds-open", "id": record.dataset_id},
                className="qs-ds-open",
            ),
            html.Button(
                html.I(className="bi bi-trash3"),
                id={"type": "qs-ds-delete", "id": record.dataset_id},
                className="qs-ds-delete",
                title="Delete this dataset",
            ),
        ],
        className="qs-ds-row" + (" active" if active else ""),
    )


def _dataset_list(records: Sequence[DatasetRecord], active_id: Optional[str]) -> html.Div:
    if not records:
        body: Any = html.Div(
            [html.I(className="bi bi-inbox"), html.Span("No saved datasets yet.")],
            className="qs-preview-empty",
        )
    else:
        body = html.Div(
            [_dataset_row(r, r.dataset_id == active_id) for r in records],
            className="qs-ds-list",
        )
    return html.Div(
        [
            html.Div([html.I(className="bi bi-collection"), "Saved datasets"], className="qs-aside-card-head"),
            body,
        ],
        className="qs-aside-card",
    )


# ── section chrome ───────────────────────────────────────────────────────────


def _section(icon: str, title: str, sub: str, children: Any, *, aside: Any = None) -> html.Div:
    """One titled block. ``aside`` rides on the header's right — a count, a state chip."""
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div([html.I(className=f"bi {icon}"), title], className="qs-sec-title"),
                            html.Div(sub, className="qs-sec-sub") if sub else None,
                        ],
                    ),
                    aside,
                ],
                className="qs-sec-head",
            ),
            children,
        ],
        className="qs-setup-section span",
    )


# ── the mapping panel (HITL) ─────────────────────────────────────────────────


def _mapping_for(record: DatasetRecord, column: str) -> Optional[ColumnMapping]:
    return next((m for m in record.mappings if m.uploaded == column), None)


def _source_badge(mapping: Optional[ColumnMapping]) -> Optional[html.Span]:
    """Who decided this row — and, for a proposal, how sure it is.

    The point of showing it: a mapping the machine proposed is exactly the one worth
    a second look, and it is indistinguishable from a confirmed one otherwise.
    """
    if mapping is None or not mapping.target:
        return None
    label = SOURCE_LABEL.get(mapping.source, "")
    if not label:
        return None
    if is_proposed(mapping):
        pct = f" {round(mapping.confidence * 100)}%" if mapping.confidence else ""
        return html.Span([html.I(className="bi bi-magic"), f"{label}{pct}"],
                         className="qs-map-badge auto",
                         title="Proposed automatically — change it if it's wrong.")
    return html.Span([html.I(className="bi bi-person-check"), label],
                     className="qs-map-badge user", title="You confirmed this mapping.")


def _row_state(mapping: Optional[ColumnMapping]) -> Tuple[str, str, bool]:
    """``(target, description, needs a description)`` for one mapping row.

    An unmapped column has nothing but its description to explain it, so the description
    is mandatory there — flagged inline on the row, counted in the progress meter, and
    enforced on submit. One derivation, so all three agree.
    """
    target = mapping.target if mapping else ""
    description = (mapping.description if mapping else "") or _target_description(target)
    return target, description, not target and not description.strip()


def _samples(profile: ColumnProfile) -> html.Div:
    """Two lines of real values — the evidence the author decides from."""
    values = [str(v) for v in profile.sample[:3]]
    first, rest = (values[0], ", ".join(values[1:])) if values else ("—", "")
    return html.Div([html.Div(first, className="qs8-sample-a"),
                     html.Div(rest, className="qs8-sample-b") if rest else None],
                    className="qs8-samples", title=", ".join(values))


def _tier_chip(tier: str) -> Any:
    if not tier:
        return html.Span("—", className="qs8-tier none")
    return html.Span(tier, className=f"qs8-tier {tier.lower()}")


def _queue_row(row: "Q.QueueRow") -> html.Div:
    """One column in the queue: what it is, its values, where it goes, why, how sure."""
    profile, mapping = row.profile, row.mapping
    target, description, needs_desc = _row_state(mapping)
    icon, kind_label = _KIND_META.get(profile.kind, ("bi-fonts", "Text"))
    desc_input = dcc.Input(
        id={"type": "qs-map-desc", "col": profile.name},
        value=description,
        placeholder="Required — what is this column?" if needs_desc else "What this column means…",
        debounce=True,
        className="qs-map-desc qs8-desc" + (" required" if needs_desc else ""),
    )
    derive = (html.Button([html.I(className="bi bi-magic"), "Create Year"],
                          id={"type": "qs8-derive-year", "col": profile.name, "at": "row"},
                          n_clicks=0, className="qs8-fix sm")
              if row.can_derive_year else None)
    why = html.Div(
        [html.Div(row.reason, className="qs8-reason"), derive,
         desc_input if not target else html.Details(
             [html.Summary([html.I(className="bi bi-pencil"), "Description"],
                           className="qs8-desc-toggle"), desc_input],
             className="qs8-desc-wrap")],
        className="qs8-cell qs8-why",
    )
    return html.Div(
        [
            html.Div(
                [html.Div(profile.name, className="qs8-col", title=profile.name),
                 html.Div([html.I(className=f"bi {icon}"),
                           f"{kind_label} · column {row.letter}"], className="qs8-colmeta")],
                className="qs8-cell qs8-src",
            ),
            html.Div(_samples(profile), className="qs8-cell"),
            html.I(className="bi bi-arrow-right qs8-arrow"),
            html.Div(
                [dcc.Dropdown(
                    id={"type": "qs-map-target", "col": profile.name},
                    options=list(_target_options()),
                    value=target or None,
                    placeholder="Not mapped",
                    maxHeight=320,
                    className="qs6-dd qs8-dd",
                 ),
                 _source_badge(mapping)],
                className="qs8-cell qs8-target",
            ),
            why,
            html.Div(_tier_chip(row.tier), className="qs8-cell qs8-conf"),
        ],
        className="qs-map-row qs8-row" + (" mapped" if target else "")
                  + (" needs-desc" if needs_desc else "")
                  + (" is-decide" if row.needs_decision else ""),
    )


def _queue_header() -> html.Div:
    return html.Div(
        [html.Span(t, className="qs8-h") for t in
         ("Source column", "Sample values", "", "Target", "Reason", "Confidence")],
        className="qs8-row qs8-headrow",
    )


def _queue_card(title: str, sub: str, rows: List["Q.QueueRow"], *, tone: str,
                fold_after: int = 0) -> html.Section:
    """One table of the queue. ``fold_after`` keeps the rest behind "Show N more" — still
    in the page, because the submit callback reads every row."""
    shown, rest = (rows[:fold_after], rows[fold_after:]) if fold_after else (rows, [])
    body = [_queue_header(), *[_queue_row(r) for r in shown]]
    if rest:
        body.append(html.Details(
            [html.Summary([html.I(className="bi bi-chevron-down"),
                           f"Show {len(rest)} more mapped column" + ("s" if len(rest) != 1 else "")],
                          className="qs8-more"),
             *[_queue_row(r) for r in rest]],
            className="qs8-fold",
        ))
    return html.Section(
        [
            html.Div(
                [html.H2([title, html.Span(str(len(rows)), className=f"qs8-count {tone}")],
                         className="qs8-h2"),
                 html.P(sub, className="qs8-sub")],
                className="qs8-card-head",
            ),
            html.Div(body, className="qs8-table"),
        ],
        className=f"qs8-card qs8-queue {tone}",
    )


def _queue_cards(record: DatasetRecord) -> List[Any]:
    decide, suggested = Q.queue(
        record, lambda p, m: _row_state(m)[1])
    cards = []
    if decide:
        cards.append(_queue_card(
            "Needs your decision",
            "These columns need a person: a match we were not sure of, a column with nothing "
            "to explain it, or a date the deck's Year could come from.",
            decide, tone="decide"))
    cards.append(_queue_card(
        "Suggested mappings",
        "Mapped from the column names and values. Review and change anything that is wrong.",
        suggested, tone="ok", fold_after=6))
    return cards


def _readiness_rail(record: DatasetRecord) -> html.Aside:
    """The three columns every deck needs, the one-click fix for a missing Year, and the
    two actions: confirm the mapping, look at the data."""
    items = Q.readiness(record)
    ready = sum(1 for i in items if i.ready)
    rows = []
    for item in items:
        fix = (html.Button([html.I(className="bi bi-magic"), f"Create Year from {item.derive_from}"],
                           id={"type": "qs8-derive-year", "col": item.derive_from, "at": "rail"},
                           n_clicks=0,
                           className="qs8-fix") if item.derive_from else None)
        rows.append(html.Div(
            [html.Span(html.I(className="bi bi-check-circle-fill" if item.ready
                              else "bi bi-exclamation-triangle-fill"),
                       className="qs8-ready-icon"),
             html.Div([html.Div(item.target.replace("_", " "), className="qs8-ready-name"),
                       html.Div(item.detail, className="qs8-ready-detail"), fix],
                      className="qs8-ready-text")],
            className="qs-req-chip qs8-ready" + (" ok" if item.ready else " todo"),
        ))
    in_use = record.status == "submitted"
    usable = record.status in ("mapped", "submitted")
    return html.Aside(
        [
            html.H3("Deck readiness", className="qs8-h3"),
            html.Div(rows, className="qs8-ready-list"),
            html.Div(
                [html.Div(f"{ready} of {len(items)} required fields ready", className="qs8-ready-sum"),
                 html.P("Resolve the items in the queue to continue. You can still adjust any "
                        "mapping below." if ready < len(items) else
                        "Every column the deck needs is in place.", className="qs8-sub")],
                className="qs8-ready-foot",
            ),
            html.Button([html.I(className="bi bi-stars"), "Confirm mapping"],
                        id="qs-map-submit", className="qs8-btn primary",
                        disabled=not record.profile.columns),
            html.Div(id="qs-map-msg", className="qs-map-msg qs8-msg"),
            html.Button([html.I(className="bi bi-rocket-takeoff"),
                         "Update deck data" if in_use else "Use this data for the deck"],
                        id="qs-ds-use", className="qs8-btn go") if usable else None,
            html.A([html.I(className="bi bi-eye"), "Preview the data"],
                   href="#qs8-data-view", className="qs8-btn ghost"),
        ],
        className="qs8-card qs8-rail",
    )


def _coverage(record: DatasetRecord) -> Tuple[List[str], List[str]]:
    """``(covered, missing)`` required canonical targets for this record."""
    covered = {m.target for m in record.mappings if m.target}
    if premium_mapped(record):
        covered.add("Premium")
    return ([t for t in REQUIRED_TARGETS if t in covered],
            [t for t in REQUIRED_TARGETS if t not in covered])


# ── primary measure + custom KPIs ────────────────────────────────────────────


def _numeric_unmapped(record: DatasetRecord) -> List[ColumnProfile]:
    mapped = {m.uploaded for m in record.mappings if m.target}
    return [p for p in record.profile.columns if p.kind == "number" and p.name not in mapped]


def _field(label: str, control: Any, *, grow: bool = False) -> html.Div:
    return html.Div([html.Div(label, className="studio-field-label"), control],
                    className="qs-kpi-field" + (" grow" if grow else ""))


def _primary_measure_card(record: DatasetRecord) -> Optional[html.Div]:
    """Shown when nothing maps to Premium: designate or calculate the primary measure.

    The three fields carry PATTERN-MATCHING ids on purpose: this whole card
    disappears once a column maps to Premium, and a plain ``State("qs-primary-…")``
    on a component that has left the layout makes Dash refuse the Submit callback
    ("a nonexistent object was used in a State"). With ``{"type": "qs-primary"}``
    the absent card simply reads back as an empty list.
    """
    if any(m.target == "Premium" for m in record.mappings):
        return None
    numeric = [{"label": p.name, "value": p.name}
               for p in record.profile.columns if p.kind == "number"]
    primary = record.primary
    return _section(
        "bi-cash-stack", "Primary measure",
        "No column maps to Premium. Pick the money measure that drives the deck — "
        "a column, or a calculation over your columns (e.g. Written_Premium + Fees).",
        html.Div(
            [
                _field("NAME", dcc.Input(
                    id={"type": "qs-primary", "field": "name"},
                    value=(primary.name if primary else ""),
                    placeholder="e.g. Gross Revenue",
                    debounce=True, className="qs-map-desc",
                )),
                _field("COLUMN", dcc.Dropdown(
                    id={"type": "qs-primary", "field": "column"}, options=numeric,
                    value=(primary.column or None) if primary else None,
                    placeholder="Pick a numeric column…",
                    className="studio-dd",
                )),
                _field("OR CALCULATION", dcc.Input(
                    id={"type": "qs-primary", "field": "formula"},
                    value=(primary.formula if primary else ""),
                    placeholder="e.g. Written_Premium + Fees",
                    debounce=True, className="qs-map-desc",
                ), grow=True),
            ],
            className="qs-kpi-grid",
        ),
    )


def _kpi_for(record: DatasetRecord, column: str) -> Optional[CustomMeasure]:
    return next((m for m in record.custom_measures if m.column == column), None)


def _kpi_row(profile: ColumnProfile, kpi: Optional[CustomMeasure]) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Span([html.I(className="bi bi-123"), "Number"],
                              className="qs-map-kindpill number"),
                    html.Span(profile.name, className="qs-map-col"),
                ],
                className="qs-map-colhead",
            ),
            dcc.Input(
                id={"type": "qs-kpi-name", "col": profile.name},
                value=(kpi.name if kpi else ""),
                placeholder="KPI name — leave blank to skip",
                debounce=True, className="qs-map-desc",
            ),
            dcc.Dropdown(
                id={"type": "qs-kpi-agg", "col": profile.name},
                options=_AGG_OPTIONS, value=(kpi.aggregation if kpi else "sum"),
                clearable=False, className="studio-dd qs-kpi-dd",
            ),
            dcc.Dropdown(
                id={"type": "qs-kpi-fmt", "col": profile.name},
                options=_FMT_OPTIONS, value=(kpi.format if kpi else "number"),
                clearable=False, className="studio-dd qs-kpi-dd",
            ),
            dcc.Input(
                id={"type": "qs-kpi-desc", "col": profile.name},
                value=(kpi.description if kpi else ""),
                placeholder="How is it calculated / what does it mean?",
                debounce=True, className="qs-map-desc",
            ),
        ],
        className="qs-kpi-row" + (" on" if (kpi and kpi.name) else ""),
    )


def _custom_kpi_card(record: DatasetRecord) -> Optional[html.Div]:
    """Metric columns matching nothing canonical → ask for KPI information."""
    candidates = _numeric_unmapped(record)
    primary_col = record.primary.column if record.primary else ""
    candidates = [p for p in candidates if p.name != primary_col]
    if not candidates:
        return None
    rows = [_kpi_row(p, _kpi_for(record, p.name)) for p in candidates]
    return _section(
        "bi-graph-up-arrow", "Custom KPIs",
        "These numeric columns don't match a standard measure. Name the ones you "
        "want in the deck — they become available in pivots and as slide widgets.",
        html.Div(rows, className="qs-map-rows"),
        aside=html.Span(f"{len(candidates)} candidates", className="qs-sec-count"),
    )


# ── shape & pivot (after mapping is submitted) ───────────────────────────────


def _column_chips(frame, record: DatasetRecord) -> html.Div:
    """Every working-frame column as a chip, each deletable.

    Any column may go, mapped or not: the mapping goes with it (``shape.drop_column``),
    which is the honest outcome — the deck cannot bind to data that is not there. The
    raw upload is untouched and Undo puts it back.
    """
    from studio.dataset.shape import derived_columns

    mapped = {m.uploaded for m in record.mappings if m.target}
    made = derived_columns(record)
    chips = []
    for col in frame.columns:
        name = str(col)
        chips.append(
            html.Span(
                [
                    html.I(className="bi bi-magic qs-colchip-made",
                           title="Created from another column") if name in made else None,
                    html.Span(name, className="qs-colchip-name"),
                    html.Button(
                        html.I(className="bi bi-x"),
                        id={"type": "qs-col-del", "col": name},
                        className="qs-colchip-x",
                        title=(f"Delete {name} — its mapping goes with it"
                               if name in mapped else f"Delete {name}"),
                    ),
                ],
                className="qs-colchip" + (" mapped" if name in mapped else "")
                          + (" made" if name in made else ""),
            )
        )
    return html.Div(chips, className="qs-colchip-row")


def _recipe_options() -> List[Mapping[str, Any]]:
    """Every reading, grouped: text surgery (split, combine…) first, then dates and tidy-ups."""
    from studio.dataset.transform import PARAM_RECIPES, RECIPES

    return ([{"label": label, "value": key} for key, (label, _fn, _args) in PARAM_RECIPES.items()]
            + [{"label": label, "value": key} for key, (label, _fn) in RECIPES.items()])


def _recipe_arg_specs() -> Dict[str, Any]:
    """``{recipe: [setting 1 label, setting 2 label]}`` — what the clientside relabel reads."""
    from studio.dataset.transform import PARAM_RECIPES

    return {key: list(args) for key, (_label, _fn, args) in PARAM_RECIPES.items()}


def _add_column_bar(frame) -> html.Div:
    """Create a column: read one out of another (split, combine, a Year from a date…), or
    compute a formula. The two settings boxes only appear for a reading that needs them."""
    columns = [{"label": str(c), "value": str(c)} for c in frame.columns]
    hidden = {"display": "none"}
    return html.Div(
        [
            dcc.Store(id="qs-col-arg-specs", data=_recipe_arg_specs()),
            _field("FROM COLUMN", dcc.Dropdown(id="qs-col-source", options=columns,
                                               placeholder="Pick a column…",
                                               maxHeight=320, className="studio-dd")),
            _field("MAKE", dcc.Dropdown(id="qs-col-recipe", options=_recipe_options(),
                                        placeholder="Split, combine, Year from a date…",
                                        maxHeight=320, className="studio-dd")),
            html.Div(_field("SETTING", dcc.Input(id="qs-col-arg1", debounce=False,
                                                 className="qs-map-desc qs-col-arg")),
                     id="qs-col-arg1-wrap", style=hidden),
            html.Div(_field("AND", dcc.Input(id="qs-col-arg2", debounce=False,
                                             className="qs-map-desc qs-col-arg")),
                     id="qs-col-arg2-wrap", style=hidden),
            _field("NAME", dcc.Input(id="qs-col-name", placeholder="Defaults to the reading",
                                     debounce=False, className="qs-map-desc qs-col-name")),
            _field("OR FORMULA", dcc.Input(id="qs-col-formula",
                                           placeholder="e.g. Premium + Fees",
                                           debounce=False,
                                           className="qs-map-desc qs-col-formula")),
            html.Button([html.I(className="bi bi-plus-lg"), "Add column"],
                        id="qs-col-add", className="qs-tf-addbtn qs-col-addbtn"),
        ],
        className="qs-addcol-bar",
    )


def _columns_section(record: DatasetRecord, frame) -> Optional[html.Div]:
    """Shape the columns BEFORE mapping them — the step that makes a thin file usable.

    Sits above the mapping panel on purpose: a spreadsheet with a billing date and no
    Year column cannot map to Year, and every period comparison in the deck stays
    empty until that column exists.
    """
    from studio.dataset.shape import shape_history

    if frame is None:
        return None
    history = shape_history(record)
    return _section(
        "bi-columns-gap", "Your columns",
        "Create a column from one you already have — split \"Asia - Singapore\" into its "
        "parts, combine two, read a Year out of a date — or delete what the deck does not "
        "need. Your mapping choices are kept either way.",
        html.Div(
            [
                _column_chips(frame, record),
                _add_column_bar(frame),
                html.Div(
                    [
                        html.Div(id="qs-col-msg", className="qs-col-msg"),
                        html.Div(
                            [
                                html.Span(history[-1], className="qs-col-last"),
                                html.Button([html.I(className="bi bi-arrow-counterclockwise"),
                                             "Undo"],
                                            id="qs-col-undo", className="qs-col-undo"),
                            ],
                            className="qs-col-history",
                        ) if history else html.Button(
                            [html.I(className="bi bi-arrow-counterclockwise"), "Undo"],
                            id="qs-col-undo", className="qs-col-undo", disabled=True,
                        ),
                    ],
                    className="qs-col-foot",
                ),
            ],
            className="qs-shape-stack",
        ),
        aside=html.Span(f"{len(frame.columns)} columns", className="qs-sec-count"),
    )


def _pivot_controls(frame, record: DatasetRecord) -> html.Div:
    from studio.dataset.model import PivotSpec

    dims = [{"label": str(c), "value": str(c)} for c in frame.columns]
    numeric_cols = [str(c) for c in frame.select_dtypes("number").columns]
    kpi_names = [m.name for m in record.custom_measures if m.name]
    if record.primary and record.primary.name:
        kpi_names.append(record.primary.name)
    values = [{"label": v, "value": v} for v in dict.fromkeys(numeric_cols + kpi_names)]
    spec = record.pivot or PivotSpec()
    fcol = spec.filters[0][0] if spec.filters else None
    fvals = list(spec.filters[0][1]) if spec.filters else []
    fval_options = (
        [{"label": str(v), "value": str(v)} for v in sorted(frame[fcol].dropna().astype(str).unique())]
        if fcol and fcol in frame.columns else []
    )
    return html.Div(
        [
            _field("ROWS", dcc.Dropdown(id="qs-pivot-rows", options=dims, value=list(spec.rows),
                                        multi=True, placeholder="Group by…", className="studio-dd")),
            _field("COLUMNS", dcc.Dropdown(id="qs-pivot-cols", options=dims, value=spec.cols or None,
                                           placeholder="Optional", className="studio-dd")),
            _field("VALUES", dcc.Dropdown(id="qs-pivot-values", options=values, value=spec.values or None,
                                          placeholder="Measure…", className="studio-dd")),
            _field("AGGREGATION", dcc.Dropdown(id="qs-pivot-agg", options=_AGG_OPTIONS,
                                               value=spec.aggregation, clearable=False,
                                               className="studio-dd")),
            _field("FILTER COLUMN", dcc.Dropdown(id="qs-pivot-fcol", options=dims, value=fcol,
                                                 placeholder="Optional", className="studio-dd")),
            _field("FILTER VALUES", dcc.Dropdown(id="qs-pivot-fvals", options=fval_options, value=fvals,
                                                 multi=True, placeholder="Keep only…",
                                                 className="studio-dd")),
            html.Button([html.I(className="bi bi-play-fill"), "Apply pivot"],
                        id="qs-pivot-apply", className="qs-tf-addbtn qs-pivot-apply"),
        ],
        className="qs-pivot-grid",
    )


def _pivot_preview(frame, record: DatasetRecord) -> Any:
    from studio.dataset.pivot import build_pivot

    spec = record.pivot
    if not spec or not spec.is_runnable:
        return html.Div(
            [html.I(className="bi bi-bounding-box"), html.Span("Pick rows and a values column, then Apply.")],
            className="qs-preview-empty",
        )
    try:
        table = build_pivot(frame, spec)
    except ValueError as exc:
        return html.Div([html.I(className="bi bi-exclamation-triangle"), html.Span(str(exc))],
                        className="qs-preview-empty")
    return _grid(table, grid_id="qs-pivot-grid-view", height=320)


def _use_for_deck_section(record: DatasetRecord, frame) -> Optional[html.Div]:
    """The hand-off to Setup. With ``PIVOT_ENABLED`` the pivot builder appears above
    the CTA; parked for now, so this is the CTA alone."""
    if record.status not in ("mapped", "submitted") or frame is None:
        return None
    in_use = record.status == "submitted"
    cta = html.Div(
        [
            html.Div(
                ("This data is live — Setup and Generate run on it."
                 if in_use else
                 "Ready when you are: this makes your data govern the deck — filters, "
                 "figures and commentary all derive from it."),
                className="qs-map-hint" + (" ok" if in_use else ""),
            ),
            html.Button(
                [html.I(className="bi bi-rocket-takeoff"),
                 "Update deck data" if in_use else "Use this data for the deck"],
                id="qs-ds-use",
                className="qs-generate-btn qs-map-submit",
            ),
        ],
        className="qs-map-actions",
    )
    if not PIVOT_ENABLED:
        return _section(
            "bi-rocket-takeoff", "Use for the deck",
            "Your mapping is saved. Hand this dataset to Setup and it takes "
            "precedence over the governed database.",
            html.Div([cta], className="qs-shape-stack"),
        )
    from studio.dataset.materialize import pivot_frame

    enriched = pivot_frame(record, frame)
    return _section(
        "bi-bounding-box", "Pivot",
        "Build the pivot that scopes the deck. The deck still computes from "
        "row-level data.",
        html.Div(
            [
                _pivot_controls(enriched, record),
                _pivot_preview(enriched, record),
                cta,
            ],
            className="qs-shape-stack",
        ),
    )


# ── the grid preview ─────────────────────────────────────────────────────────


def _grid(frame, *, grid_id: str = "qs-data-grid", height: int = 480) -> Any:
    if frame is None or frame.empty:
        return html.Div(
            [html.I(className="bi bi-grid-3x2"), html.Span("No rows to preview.")],
            className="qs-preview-empty",
        )
    head = frame.head(_PREVIEW_ROWS)
    return dag.AgGrid(
        id=grid_id,
        rowData=head.to_dict("records"),
        columnDefs=[
            {"field": str(c), "sortable": True, "filter": True, "resizable": True}
            for c in head.columns
        ],
        defaultColDef={"minWidth": 110},
        dashGridOptions={"pagination": True, "paginationPageSize": 25,
                         "paginationPageSizeSelector": [25, 50, 100]},
        className="ag-theme-alpine qs-data-grid",
        style={"height": f"{height}px", "width": "100%"},
    )


def _data_view(record: DatasetRecord, frame) -> html.Div:
    """See the data: the working rows (with any created columns), sortable and filterable."""
    n_rows = len(frame) if frame is not None else record.n_rows
    n_preview = min(n_rows, _PREVIEW_ROWS)
    return html.Div(
        _section(
            "bi-grid-3x2", "Your data",
            f"First {n_preview:,} of {n_rows:,} rows, including any columns you created — "
            "sort and filter to explore.",
            _grid(frame, height=520),
            aside=html.Span(f"{len(frame.columns) if frame is not None else record.n_cols} columns",
                            className="qs-sec-count"),
        ),
        id="qs8-data-view",
    )


def _active_panel(record: DatasetRecord, frame) -> html.Div:
    sections = [
        *_queue_cards(record),
        _primary_measure_card(record),
        _custom_kpi_card(record),
        _columns_section(record, frame),
        _use_for_deck_section(record, frame) if PIVOT_ENABLED else None,
        _data_view(record, frame),
    ]
    return html.Div([s for s in sections if s is not None], className="qs-data-active")


def _empty_panel() -> html.Div:
    return html.Div(
        [
            html.I(className="bi bi-table qs-empty-icon"),
            html.Div("No dataset selected", className="qs-empty-title"),
            html.P(
                "Upload a spreadsheet or open a saved dataset. Every column arrives with a "
                "proposed mapping for you to confirm — then that data builds the deck, taking "
                "precedence over the governed database.",
                className="qs-empty-sub",
            ),
        ],
        className="qs-empty",
    )


# ── the mode body ────────────────────────────────────────────────────────────


def _uploaded_on(record: DatasetRecord) -> str:
    from datetime import datetime

    try:
        return "Uploaded " + datetime.fromisoformat(str(record.created)[:19]).strftime(
            "%d %b %Y, %H:%M")
    except ValueError:
        return ""


def _head(record: Optional[DatasetRecord]) -> html.Div:
    if record is None:
        title = [html.H1("Your data", className="qs8-h1"),
                 html.P("Bring your own spreadsheet. We propose what every column is, you "
                        "confirm it once, and the deck builds from it.", className="qs8-sub")]
    else:
        meta = " · ".join(p for p in (f"{record.n_rows:,} rows", f"{record.n_cols} columns",
                                      _uploaded_on(record)) if p)
        title = [html.H1("Your data", className="qs8-h1"),
                 html.Div(record.filename or record.name, className="qs8-file"),
                 html.Div(meta, className="qs8-meta")]
    status = None
    if record is not None:
        label, tone = _STATUS_CHIP.get(record.status, (record.status, "todo"))
        status = html.Span([html.I(className="bi bi-check-circle" if tone != "todo"
                                   else "bi bi-pencil-square"), label],
                           className=f"qs8-status {tone}")
    return html.Div(
        [html.Div(title, className="qs8-title"), _pipeline(record), status],
        className="qs8-head",
    )


def data_body(dataset_state: Optional[Mapping[str, Any]]) -> html.Div:
    """The Data mode body. ``dataset_state`` is the ``qs-dataset`` browser store
    (only the active dataset id lives there — data stays server-side)."""
    from studio.dataset.materialize import working_frame
    from studio.dataset.repository import get_repository

    repo = get_repository()
    records = repo.list()
    active_id = (dataset_state or {}).get("active")
    record = repo.get(active_id) if active_id else None
    frame = None
    if record is not None:
        try:
            frame = working_frame(repo, record)
        except ValueError:
            frame = repo.load_frame(active_id)

    library = html.Div([_upload_zone(), _dataset_list(records, active_id)],
                       className="qs8-library")
    main = _active_panel(record, frame) if record else _empty_panel()
    rail = html.Div([_readiness_rail(record) if record else None, library],
                    className="qs-setup-aside qs8-aside")
    return html.Div(
        [_head(record),
         html.Div([html.Div(main, className="qs-data-main qs8-main"), rail],
                  className="qs8-layout")],
        className="qs-setup-wrap qs8-page",
    )
