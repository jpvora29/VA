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
from typing import Any, List, Mapping, Optional, Sequence, Tuple

import dash_ag_grid as dag
from dash import dcc, html

from studio.dataset.automap import SOURCE_LABEL, is_proposed
from studio.dataset.ingest import SUPPORTED_EXTENSIONS
from studio.dataset.model import (
    REQUIRED_TARGETS,
    ColumnMapping,
    ColumnProfile,
    CustomMeasure,
    DatasetRecord,
    premium_mapped,
)

# Column add/delete and the pivot builder are parked for now. The engine
# (studio/dataset/transform.py, pivot.py) is kept and tested; flip this to True
# and re-register the parked callbacks in studio/authoring/data.py to restore.
SHAPE_TOOLS_ENABLED = False

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


def _step(number: int, title: str, sub: str, state: str) -> html.Div:
    """One node of the pipeline: done (a tick), active (numbered, lit) or still to come."""
    mark = html.I(className="bi bi-check-lg") if state == "done" else str(number)
    return html.Div(
        [
            html.Div(mark, className="qs-step-mark"),
            html.Div(
                [html.Div(title, className="qs-step-title"),
                 html.Div(sub, className="qs-step-sub")],
                className="qs-step-text",
            ),
        ],
        className=f"qs-step is-{state}",
    )


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
            _step(1, "Upload", "Bring a spreadsheet", upload),
            html.Div(className="qs-step-link"),
            _step(2, "Map columns", "Confirm what each column is", mapping),
            html.Div(className="qs-step-link"),
            _step(3, "Use for the deck", "Hand it to Setup", use),
        ],
        className="qs-pipeline",
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
                            f"or click to browse — {', '.join(SUPPORTED_EXTENSIONS)}, up to 100k rows",
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


def _column_facts(profile: ColumnProfile) -> html.Div:
    """The evidence for a decision: how many distinct values, how empty, and examples."""
    chips = [html.Span(str(value), className="qs-map-sample") for value in profile.sample[:3]]
    return html.Div(
        [
            html.Div(
                [
                    html.Span([html.B(f"{profile.n_distinct:,}"), " distinct"], className="qs-map-stat"),
                    html.Span([html.B(f"{profile.null_pct:g}%"), " empty"],
                              className="qs-map-stat" + (" warn" if profile.null_pct >= 50 else "")),
                ],
                className="qs-map-stats",
            ),
            html.Div(chips, className="qs-map-samples") if chips else None,
        ],
        className="qs-map-facts",
    )


def _row_state(mapping: Optional[ColumnMapping]) -> Tuple[str, str, bool]:
    """``(target, description, needs a description)`` for one mapping row.

    An unmapped column has nothing but its description to explain it, so the description
    is mandatory there — flagged inline on the row, counted in the progress meter, and
    enforced on submit. One derivation, so all three agree.
    """
    target = mapping.target if mapping else ""
    description = (mapping.description if mapping else "") or _target_description(target)
    return target, description, not target and not description.strip()


def _mapping_row(profile: ColumnProfile, mapping: Optional[ColumnMapping]) -> html.Div:
    target, description, needs_desc = _row_state(mapping)
    icon, kind_label = _KIND_META.get(profile.kind, ("bi-fonts", "Text"))
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span([html.I(className=f"bi {icon}"), kind_label],
                                      className=f"qs-map-kindpill {profile.kind}"),
                            html.Span(profile.name, className="qs-map-col", title=profile.name),
                        ],
                        className="qs-map-colhead",
                    ),
                    _column_facts(profile),
                ],
                className="qs-map-src",
            ),
            html.I(className="bi bi-arrow-right qs-map-arrow"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("Maps to", className="qs-map-fieldlabel"),
                            _source_badge(mapping),
                        ],
                        className="qs-map-fieldhead",
                    ),
                    dcc.Dropdown(
                        id={"type": "qs-map-target", "col": profile.name},
                        options=list(_target_options()),
                        value=target or None,
                        placeholder="Not mapped — pick a column",
                        className="studio-dd qs-map-dd",
                    ),
                ],
                className="qs-map-field",
            ),
            html.Div(
                [
                    html.Span("Description" + (" — required" if needs_desc else ""),
                              className="qs-map-fieldlabel"),
                    dcc.Input(
                        id={"type": "qs-map-desc", "col": profile.name},
                        value=description,
                        placeholder="Required — what is this column?" if needs_desc
                                    else "What this column means…",
                        debounce=True,
                        className="qs-map-desc" + (" required" if needs_desc else ""),
                    ),
                ],
                className="qs-map-field",
            ),
        ],
        className="qs-map-row" + (" mapped" if target else "")
                  + (" needs-desc" if needs_desc else ""),
    )


def _coverage(record: DatasetRecord) -> Tuple[List[str], List[str]]:
    """``(covered, missing)`` required canonical targets for this record."""
    covered = {m.target for m in record.mappings if m.target}
    if premium_mapped(record):
        covered.add("Premium")
    return ([t for t in REQUIRED_TARGETS if t in covered],
            [t for t in REQUIRED_TARGETS if t not in covered])


def _requirement_chips(record: DatasetRecord) -> html.Div:
    """The three columns the fixed templates cannot fill without, ticked off live."""
    covered, _ = _coverage(record)
    chips = []
    for target in REQUIRED_TARGETS:
        ok = target in covered
        chips.append(
            html.Span(
                [
                    html.I(className="bi " + ("bi-check-circle-fill" if ok else "bi-circle")),
                    target.replace("_", " "),
                ],
                className="qs-req-chip" + (" ok" if ok else ""),
                title="Required before this dataset can build a deck.",
            )
        )
    return html.Div(chips, className="qs-req-chips")


def _mapping_progress(record: DatasetRecord) -> html.Div:
    """How much of the upload is accounted for — a meter plus the three counts."""
    columns = record.profile.columns
    states = [_row_state(_mapping_for(record, p.name)) for p in columns]
    mapped = sum(1 for target, _, _ in states if target)
    proposed = sum(1 for m in record.mappings if is_proposed(m))
    pending = sum(1 for _, _, needs_desc in states if needs_desc)
    return html.Div(
        [
            html.Div(
                html.Div(className="qs-meter-fill",
                         style={"width": f"{round(100 * mapped / max(len(columns), 1))}%"}),
                className="qs-meter",
            ),
            html.Div(
                [
                    html.Span([html.B(f"{mapped}"), f" of {len(columns)} mapped"],
                              className="qs-map-count"),
                    html.Span([html.B(f"{proposed}"), " proposed for review"],
                              className="qs-map-count alt") if proposed else None,
                    html.Span([html.B(f"{pending}"), " need a description"],
                              className="qs-map-count warn") if pending else None,
                ],
                className="qs-map-counts",
            ),
        ],
        className="qs-map-progress",
    )


def _mapping_header() -> html.Div:
    return html.Div(
        [
            html.Span("Your column", className="qs-map-h"),
            html.Span(""),
            html.Span("Maps to", className="qs-map-h"),
            html.Span("Description", className="qs-map-h"),
        ],
        className="qs-map-row qs-map-headrow",
    )


def _mapping_panel(record: DatasetRecord) -> html.Div:
    rows = [_mapping_row(p, _mapping_for(record, p.name)) for p in record.profile.columns]
    _, missing = _coverage(record)
    ready = not missing
    hint = (
        "Every number in the deck traces to these mappings."
        if ready
        else "Still needed: " + ", ".join(t.replace("_", " ") for t in missing)
    )
    return _section(
        "bi-signpost-2", "Column mapping",
        "Each column arrives with a proposed target. Change anything that's wrong — "
        "columns you leave unmapped need a description, that's all the deck has to go on.",
        html.Div(
            [
                _mapping_progress(record),
                html.Div([_mapping_header(), *rows], className="qs-map-rows"),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Div(hint, className="qs-map-hint" + ("" if ready else " warn")),
                                html.Div(id="qs-map-msg", className="qs-map-msg"),
                            ],
                            className="qs-map-hints",
                        ),
                        html.Button(
                            [html.I(className="bi bi-check2-circle"), "Confirm mapping"],
                            id="qs-map-submit",
                            className="qs-generate-btn qs-map-submit",
                            disabled=not record.profile.columns,
                        ),
                    ],
                    className="qs-map-actions",
                ),
            ],
            className="qs-map-panel",
        ),
        aside=_requirement_chips(record),
    )


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
    """Every working-frame column as a chip; unmapped ones are deletable."""
    mapped = {m.uploaded for m in record.mappings if m.target}
    chips = []
    for col in frame.columns:
        deletable = col not in mapped
        chips.append(
            html.Span(
                [
                    html.Span(str(col), className="qs-colchip-name"),
                    html.Button(
                        html.I(className="bi bi-x"),
                        id={"type": "qs-col-del", "col": str(col)},
                        className="qs-colchip-x",
                        title="Delete this column",
                    ) if deletable else html.I(
                        className="bi bi-link-45deg qs-colchip-lock",
                        title="Mapped column — unmap it before deleting",
                    ),
                ],
                className="qs-colchip" + ("" if deletable else " locked"),
            )
        )
    return html.Div(chips, className="qs-colchip-row")


def _add_column_bar() -> html.Div:
    return html.Div(
        [
            dcc.Input(id="qs-col-name", placeholder="New column name",
                      debounce=False, className="qs-map-desc qs-col-name"),
            dcc.Input(id="qs-col-formula", placeholder="Formula — e.g. Premium * 0.15",
                      debounce=False, className="qs-map-desc qs-col-formula"),
            html.Button([html.I(className="bi bi-plus-lg"), "Add column"],
                        id="qs-col-add", className="qs-tf-addbtn"),
            html.Div(id="qs-col-msg", className="qs-map-hint warn"),
        ],
        className="qs-addcol-bar",
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
    """The hand-off to Setup. With ``SHAPE_TOOLS_ENABLED`` the column and pivot
    builders appear above the CTA; parked for now, so this is the CTA alone."""
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
    if not SHAPE_TOOLS_ENABLED:
        return _section(
            "bi-rocket-takeoff", "Use for the deck",
            "Your mapping is saved. Hand this dataset to Setup and it takes "
            "precedence over the governed database.",
            html.Div([cta], className="qs-shape-stack"),
        )
    from studio.dataset.materialize import pivot_frame

    enriched = pivot_frame(record, frame)
    return _section(
        "bi-bounding-box", "Shape & pivot",
        "Delete columns you don't need, add calculated ones, and build the pivot "
        "that scopes the deck. The deck still computes from row-level data.",
        html.Div(
            [
                _column_chips(frame, record),
                _add_column_bar(),
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
        dashGridOptions={"pagination": True, "paginationPageSize": 25},
        className="ag-theme-alpine qs-data-grid",
        style={"height": f"{height}px", "width": "100%"},
    )


def _active_panel(record: DatasetRecord, frame) -> html.Div:
    n_rows = len(frame) if frame is not None else record.n_rows
    n_preview = min(n_rows, _PREVIEW_ROWS)
    sections = [
        _mapping_panel(record),
        _primary_measure_card(record),
        _custom_kpi_card(record),
        _use_for_deck_section(record, frame),
        _section(
            "bi-grid-3x2", "Data preview",
            f"First {n_preview:,} of {n_rows:,} rows — sort and filter to explore.",
            _grid(frame),
            aside=html.Span(f"{record.n_cols} columns", className="qs-sec-count"),
        ),
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


def _head(record: Optional[DatasetRecord]) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div("QBR Studio", className="qs-setup-eyebrow"),
                    html.Div([html.I(className="bi bi-table"), "Your data"], className="qs-setup-title"),
                    html.P(
                        "Bring your own dataset. We propose what every column is, you confirm "
                        "it once, and the deck builds from it — figures stay deterministic "
                        "and traceable.",
                        className="qs-setup-sub",
                    ),
                ],
                className="qs-setup-head-text",
            ),
            html.Span(
                [html.I(className="bi bi-person-check"), "Your data governs"],
                className="qs-govern-chip",
                title="A submitted dataset takes precedence over the governed database for this deck.",
            ),
        ],
        className="qs-setup-head",
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

    aside = html.Div([_upload_zone(), _dataset_list(records, active_id)], className="qs-setup-aside")
    main = _active_panel(record, frame) if record else _empty_panel()
    card = html.Div(
        [
            _head(record),
            _pipeline(record),
            html.Div(
                [html.Div(main, className="qs-data-main"), aside],
                className="qs-setup-layout",
            ),
        ],
        className="qs-setup-card",
    )
    return html.Div(card, className="qs-setup-wrap")
