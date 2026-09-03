"""The Studio pipeline/builder layer — the shape every build now reads in.

Covers the shared step runner (``studio.steps``) and the builders that use it:

    FILL_PIPELINE                         the .pptx write, stage by stage
    ComputeRequest/OverallResultBuilder   the Overall page, section by section
    ReportPlanBuilder                     the business argument, finding by finding

Unit-level here; the real workflow they sit in is covered end to end by
``tests/test_qbr_pipeline.py`` and ``tests/test_template_end_to_end.py``. The two
builders not exercised here already have their own suites — ``TemplateDocBuilder``
via ``tests/test_template_end_to_end.py`` and ``SubDeckPlanBuilder`` via
``tests/test_survey_assemble.py`` and ``tests/test_studio_dataset_shape.py``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import pytest

os.environ["STUDIO_AI"] = "off"          # deterministic: no LLM anywhere

from studio.steps import Pipeline, PipelineBuilder, StepFailed  # noqa: E402


# ── the step runner ───────────────────────────────────────────────────────────


@dataclass
class Box:
    """A trivial context: the steps below just record that they ran."""

    seen: List[str] = field(default_factory=list)


def _record(name: str):
    def step(ctx: Box) -> None:
        ctx.seen.append(name)

    return step


def _boom(ctx: Box) -> None:
    raise ValueError("no data for this step")


def test_steps_run_in_declared_order():
    pipeline = (
        PipelineBuilder("demo")
        .step("first", _record("first"))
        .step("second", _record("second"))
        .step("third", _record("third"))
        .build()
    )
    assert pipeline.step_names() == ["first", "second", "third"]

    run = pipeline.run(Box())
    assert run.context.seen == ["first", "second", "third"]
    assert [r.name for r in run.trace] == ["first", "second", "third"]
    assert not run.failed


def test_a_critical_failure_names_the_step_that_failed():
    pipeline = PipelineBuilder("demo").step("write_values", _boom).build()

    with pytest.raises(StepFailed) as excinfo:
        pipeline.run(Box())

    assert excinfo.value.step == "write_values"
    assert "write_values" in str(excinfo.value)          # debuggable without a traceback
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_an_optional_failure_is_recorded_and_the_run_continues():
    pipeline = (
        PipelineBuilder("demo")
        .step("before", _record("before"))
        .optional("enrichment", _boom)
        .step("after", _record("after"))
        .build()
    )
    run = pipeline.run(Box())

    assert run.context.seen == ["before", "after"]       # the run survived
    assert [r.name for r in run.failed] == ["enrichment"]
    assert "no data for this step" in run.summary()


def test_the_trace_summarises_every_step():
    run = PipelineBuilder("demo").step("only", _record("only")).build().run(Box())
    assert run.trace[0].ok and run.trace[0].seconds >= 0
    assert "only" in run.summary()


# ── the fill pipeline ─────────────────────────────────────────────────────────


def test_fill_pipeline_stages_are_declared_in_write_then_geometry_order():
    from studio.template_fill.fill import FILL_PIPELINE

    names = FILL_PIPELINE.step_names()
    assert isinstance(FILL_PIPELINE, Pipeline)
    assert names[0] == "write_values"                   # text before anything moves
    assert names[-1] == "save_deck"
    # Geometry edits address shapes by the indices the writes used, so they come last.
    assert names.index("write_values") < names.index("drop_shapes")
    assert names.index("fill_charts") < names.index("resize_shapes")


# ── the Overall compute builder ───────────────────────────────────────────────


def test_compute_request_resolves_form_filters_to_real_columns():
    from studio.compute import DEFAULT_BREAKDOWNS, build_compute_request

    request = build_compute_request(
        engine=object(), filters={"carrier": "Zurich", "year": 2025, "country": "all"})

    assert request.filters["Carrier_Group"] == "Zurich"
    assert request.filters["Year"] == 2025
    assert "Country" not in request.filters              # "all" is not a filter
    assert request.subject == "Zurich"
    assert request.breakdowns == DEFAULT_BREAKDOWNS


def test_a_failing_section_is_skipped_not_fatal(monkeypatch):
    import studio.compute as compute

    monkeypatch.setattr(compute, "_kpis", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db")))
    monkeypatch.setattr(compute, "_breakdown_section",
                        lambda flow, dim, *a, **k: compute.BreakdownSection(dim, dim, []))
    monkeypatch.setattr(compute, "_whitespace", lambda *a, **k: [{"name": "Mining"}])

    request = compute.build_compute_request(engine=object(), filters={"carrier": "Zurich"})
    result = (compute.OverallResultBuilder(request)
              .add_kpis().add_breakdowns().add_whitespace().build())

    assert result.kpis == []                             # the failing section, left out
    assert [b.column for b in result.breakdowns] == list(compute.DEFAULT_BREAKDOWNS)
    assert result.whitespace                             # and the rest still computed


def test_whitespace_needs_a_subject(monkeypatch):
    import studio.compute as compute

    monkeypatch.setattr(compute, "_whitespace", lambda *a, **k: [{"name": "Mining"}])
    request = compute.build_compute_request(engine=object(), filters={"year": 2025})

    assert compute.OverallResultBuilder(request).add_whitespace().build().whitespace == []


# ── the report-plan builder ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def evidence():
    from studio.compute import compute_overall
    from studio.content.evidence_graph import build_evidence_graph
    from studio.pipeline.qbr_pipeline import build_evidence

    pack = build_evidence(compute_overall(filters={"carrier": "Zurich", "year": 2025}))
    return pack, build_evidence_graph(pack)


def test_each_finding_is_added_by_its_own_builder_call(evidence):
    from studio.pipeline.qbr_pipeline import ReportPlanBuilder, StudioSelection

    pack, graph = evidence
    selection = StudioSelection(filters={"carrier": "Zurich", "year": 2025})

    performance = ReportPlanBuilder(pack, graph, selection).add_performance_finding().build()
    assert [f.section for f in performance.findings] == ["performance"]

    everything = (ReportPlanBuilder(pack, graph, selection)
                  .add_performance_finding()
                  .add_movement_driver_finding()
                  .add_whitespace_finding()
                  .build())
    assert [f.section for f in everything.findings][0] == "performance"
    assert len(everything.findings) >= len(performance.findings)


def test_findings_only_cite_facts_the_pack_holds(evidence):
    from studio.pipeline.qbr_pipeline import build_report_plan, StudioSelection

    pack, graph = evidence
    plan = build_report_plan(pack, graph, StudioSelection(filters={"carrier": "Zurich"}))

    assert plan.findings
    for finding in plan.findings:
        for claim in finding.claims:
            assert claim.fact_ids
            assert all(fid in pack.items for fid in claim.fact_ids)
