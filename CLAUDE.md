# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Engineering Style

Keep the code simple, modular, and easy to follow.

Do:

- Prefer small files with one clear responsibility.
- Prefer small functions that do one task.
- Prefer explicit data flow over hidden side effects.
- Prefer dataclasses for internal data contracts.
- Prefer pure functions for transformation, validation, mapping, and formatting.
- Prefer composition over inheritance.
- Prefer clear names over clever abstractions.
- Prefer a readable pipeline function that calls named sub-functions in order.
- Prefer simple Python design patterns as explained in the ArjanCodes style: Strategy, Adapter, Factory Function, Repository, and simple dependency injection.

Avoid:

- Complex engineering for small problems.
- Large "manager" or "service" classes that do everything.
- Deep inheritance trees.
- Abstract base classes unless there is more than one real implementation.
- One function that loads data, transforms it, calls an LLM, validates output, and writes files.
- Hidden global state.
- Framework magic when plain Python is enough.
- Premature generalization.

## Core Rule

One function should do one job.

Multi-step work uses a **builder** (see Builder Pattern) or a **step pipeline**
(see Step Pipelines). The entry point lists the steps; the steps do the work.

Bad:

```python
def build_deck(selection):
    data = query_database(selection)
    facts = calculate_metrics(data)
    template = parse_powerpoint(selection.template_path)
    prompt = make_prompt(facts, template)
    commentary = call_llm(prompt)
    validate_commentary(commentary, facts)
    path = export_pptx(template, facts, commentary)
    return path
```

Good:

```python
def build_deck(selection):
    data = load_data(selection)
    facts = build_facts(data)
    template = load_template(selection.template_path)
    commentary = build_commentary(facts)
    qa_report = validate_deck(facts, template, commentary)
    return export_deck(template, facts, commentary, qa_report)
```

Even better for larger flows:

```python
async def build_qbr_deck_pipeline(selection: StudioSelection) -> QBRPipelineResult:
    sql_output = await load_structured_sql_output(selection)
    evidence_pack = build_evidence_pack(sql_output)
    evidence_graph = build_evidence_graph(evidence_pack)

    template_descriptor = parse_template(selection.template_path)
    layout_intent = await detect_layout_intent(template_descriptor)
    binding_map = validate_or_create_binding_map(template_descriptor, layout_intent)

    report_plan = build_report_plan(evidence_pack, evidence_graph, selection)
    render_plan = build_render_plan(report_plan, binding_map)

    commentary_plan = build_commentary_plan(report_plan, evidence_graph, render_plan)
    commentary = await draft_and_verify_commentary(commentary_plan, evidence_pack)

    qa_report = run_qbr_qa(render_plan, commentary, evidence_pack, binding_map)
    deck_path = export_qbr_deck(render_plan, commentary, qa_report)

    return QBRPipelineResult(deck_path=deck_path, qa_report=qa_report)
```

The pipeline should read like steps in the business process.

## Async Guidance

Use `asyncio` only when it makes the code faster without making it harder to understand.

Good uses:

- Independent LLM calls.
- Independent template analysis tasks.
- Independent QA checks.
- Independent slide commentary drafts.

Bad uses:

- Parallelizing steps that depend on earlier validation.
- Making every function async by default.
- Changing output order based on completion order.

Preserve deterministic output order:

```python
async def gather_ordered(tasks):
    return await asyncio.gather(*tasks)
```

Use bounded concurrency when calling models or external services:

```python
async def run_bounded(items, limit, worker):
    semaphore = asyncio.Semaphore(limit)

    async def run_one(item):
        async with semaphore:
            return await worker(item)

    return await asyncio.gather(*(run_one(item) for item in items))
```

## Dataclass Contracts

Use dataclasses for internal contracts that move through the pipeline.

Example:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvidenceItem:
    fact_id: str
    measure: str
    value: float
    rendered: str
    dims: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CommentarySentence:
    text: str
    fact_ids: tuple[str, ...]
```

Use Pydantic or strict schemas at LLM boundaries when structured output must be validated.

## SOLID Principles, Practically

Apply SOLID in a simple Python way.

Single Responsibility:

- One module parses templates.
- One module maps bindings.
- One module builds commentary.
- One module validates commentary.
- One module exports PowerPoint.

Open/Closed:

- Add new rules by adding rule functions or YAML config, not by rewriting the pipeline.
- Add new template types by adding binding config, not by editing compute code.

Liskov Substitution:

- Avoid inheritance unless substitutions are genuinely needed.
- If you use interfaces, make sure all implementations behave the same way.

Interface Segregation:

- Keep small protocols or callables.
- Do not force a class to implement methods it does not need.

Dependency Inversion:

- Business logic should depend on small interfaces or functions.
- Keep database, LLM, and PowerPoint details at the edges.

Example:

```python
from typing import Protocol


class CommentaryDraftClient(Protocol):
    async def draft(self, request: CommentaryRequest) -> CommentaryDraft:
        ...


async def draft_and_verify_commentary(
    plan: CommentaryPlan,
    facts: EvidencePack,
    client: CommentaryDraftClient,
) -> VerifiedCommentary:
    draft = await client.draft(CommentaryRequest(plan=plan, facts=facts))
    return verify_commentary(draft, facts)
```

## Builder Pattern — the default shape for anything multi-step

This is the pattern we reach for most. Any flow that assembles a result out of
several optional or ordered parts is a **builder**: one `add_*` per part, a
`build()` that returns the finished value, and a short public function that reads
as the list of parts.

The point is that the top-level function becomes the specification. You should be
able to read what a deck contains, or what a page computes, without opening a
single step.

```python
class OverallResultBuilder:
    """Builds an OverallResult one section at a time."""

    def __init__(self, request: ComputeRequest) -> None:
        self._request = request
        self._result = OverallResult(...)

    def add_kpis(self) -> "OverallResultBuilder":
        ...
        return self

    def add_breakdowns(self) -> "OverallResultBuilder":
        ...
        return self

    def build(self) -> OverallResult:
        return self._result


def compute_overall(**form_answers) -> OverallResult:
    request = build_compute_request(**form_answers)
    return (
        OverallResultBuilder(request)
        .add_kpis()
        .add_breakdowns()
        .add_whitespace()
        .build()
    )
```

Rules:

- Take a **frozen request dataclass**, not a long keyword-argument list. Resolve
  form values into real columns/handles once, in a `build_*_request` factory
  function, so no step re-reads a raw form value.
- One `add_*` per part of the result, named for the part it adds.
- An `add_*` owns the whole answer for its part, including "this part is not in
  scope" — it returns `self` unchanged rather than making the caller check.
- `add_*` returns `self` **only** so the call sequence reads as a list. Never hide
  branching in the chain.
- `build()` returns the value and does nothing else worth debugging.
- Keep the original public function name and signature. The builder is how it is
  implemented, not a new API callers have to learn.

Live examples: `studio/compute.py` (`OverallResultBuilder`),
`studio/template_fill/assemble.py` (`SubDeckPlanBuilder`),
`studio/template_fill/model.py` (`TemplateDocBuilder`),
`studio/pipeline/qbr_pipeline.py` (`ReportPlanBuilder`).

## Step Pipelines — for ordered work over one context

When the steps **mutate one shared thing** in a fixed order (a `Presentation`, a
run directory) rather than accumulating a value, use `studio/steps.py` instead of
a builder:

```python
FILL_PIPELINE = (
    PipelineBuilder("fill_template")
    .step("write_values", write_values)
    .step("fill_charts", fill_charts)
    .optional("crop_pictures", crop_pictures)   # logged on failure, run continues
    .step("save_deck", save_deck)
    .build()
)


def fill_template(doc, *, out_path=None) -> str:
    ctx = build_fill_context(doc, out_path or default_out_path())
    FILL_PIPELINE.run(ctx)
    return ctx.out_path
```

What you get for free, and why it is worth the small indirection:

- Every step is **named**, so a failure says which step failed before you open a
  stack trace (`StepFailed`), and the run's `trace` times every step.
- `optional(...)` replaces the `try/except … logger.warning` that otherwise gets
  copy-pasted around every best-effort call. Critical vs. optional becomes a
  property of the step, declared once, next to its name.
- Because the order lives in one list, reordering is a diff you can read.

Rules:

- A step takes the context and returns `None`. It works on the context.
- **A step never calls another step.** Ordering lives in the pipeline and nowhere
  else — that is the whole reason the pipeline exists.
- A step is a plain module-level function, so it is callable on its own in a test.
- Build the context in one `build_*_context` function up front. A step must not
  discover its inputs.

Live example: `studio/template_fill/fill.py` (`FILL_PIPELINE`).

Async flows keep the same shape with `await` between steps —
`studio/pipeline/qbr_pipeline.py::build_qbr_deck_pipeline` is the reference.

## Flat Call Chains — no deep nesting

Nested call chains are the main thing that makes this codebase hard to debug. A
function that calls a function that calls a function means a breakpoint on the
top-level flow tells you nothing, and a stack trace is the only way to find out
what actually ran.

Keep the depth shallow and the sequence visible:

```text
entry point  ->  step / add_*  ->  small helper
                                   (and no further)
```

Do:

- Put the sequence in ONE place — the pipeline list or the builder chain.
- Let steps be siblings, not a chain. Step 3 must not call step 4.
- Pass what a helper needs as arguments. If a helper reaches back for context, it
  wants to be a step.
- Extract a helper to name a piece of logic, not to continue the flow.

Avoid:

- A "step" whose real job is to call the next step.
- Helper → helper → helper chains three deep or more.
- Closures defined inside an orchestrator that capture its locals. Make them
  methods or module functions with explicit arguments; a closure is invisible to
  a debugger's frame list and untestable on its own.
- Passing a half-built result down a chain for each level to add to. Accumulate
  it in the builder instead.

Bad:

```python
def build_page(result):
    return _finish(_enrich(_seed(result)))       # what ran? in what order?
```

Good:

```python
def build_page(result):
    page = seed_page(result)
    enrich_page(page)
    finish_page(page)
    return page
```

## Recommended Python Design Patterns

Use patterns only when they make code simpler.

### Strategy

Use when behavior changes by audience, slide type, template type, or commentary style.

```python
def build_commentary(plan, facts, strategy):
    return strategy(plan, facts)


def executive_strategy(plan, facts):
    return concise_commentary(plan, facts)


def technical_strategy(plan, facts):
    return detailed_commentary(plan, facts)
```

### Adapter

Use when wrapping existing code or external libraries.

```python
class PowerPointTemplateAdapter:
    def __init__(self, pptx_path: str):
        self.pptx_path = pptx_path

    def describe(self) -> TemplateDescriptor:
        return parse_pptx(self.pptx_path)
```

### Factory Function

Use a function instead of a complex factory class.

```python
def make_commentary_client(settings) -> CommentaryDraftClient:
    if settings.ai_enabled:
        return DeepAgentCommentaryClient(settings.model)
    return DeterministicCommentaryClient()
```

### Repository

Use only at data boundaries.

```python
class StudioDataRepository:
    def __init__(self, engine):
        self.engine = engine

    def load_premium_rows(self, selection):
        return query_premium_rows(self.engine, selection)
```

### Facade

Use a facade only for a high-level entrypoint. The facade should delegate, not contain all logic.

```python
class QBRDeckBuilder:
    def __init__(self, client, repository):
        self.client = client
        self.repository = repository

    async def build(self, selection):
        return await build_qbr_deck_pipeline(selection, self.repository, self.client)
```

## QBR Studio Specific Rules

For Studio and QBR deck generation:

- Deterministic facts are the source of truth.
- SQL output should become structured evidence before commentary is written.
- Every number in commentary must trace to a fact ID.
- Charts and tables must be validated against the same evidence used for commentary.
- Deep agents can identify template structure, suggest mappings, draft commentary, and explain QA issues.
- Deep agents must not decide final truth, invent data, or bypass YAML rules.
- Template parsing should be deterministic.
- Layout interpretation can use a deep agent with structured output and confidence scores.
- Binding maps should be validated before use.
- Carrier-facing output must avoid named peer disclosure unless explicitly allowed.

## Review Checklist

Before finishing a change, check:

- Does each changed function do one clear task?
- Can the main flow be read from top to bottom?
- Is multi-step work a builder chain or a named step pipeline, not a call chain?
- Is every call chain at most entry point -> step -> helper deep?
- Is each step callable on its own, with its inputs passed in?
- Are LLM calls isolated behind small adapters?
- Are facts and commentary connected by IDs?
- Are validation rules deterministic?
- Is the code testable without calling the LLM?
- Did we run or define an end-to-end test path, not only unit tests?
- Did we avoid adding abstractions that are not needed yet?
- Did we preserve existing Studio behavior unless the task explicitly changes it?

## Testing Expectation

Always think beyond unit tests.

Unit tests are necessary, but they are not enough. For meaningful changes, include an end-to-end or integration test path that proves the real workflow still works.

For QBR Studio, an end-to-end test should cover the actual business flow:

```text
selection/filter input
  -> structured data load
  -> evidence/facts
  -> report/deck plan
  -> template binding
  -> commentary
  -> QA validation
  -> exported PPTX
```

Good testing shape:

- Unit tests for pure functions.
- Integration tests for module boundaries.
- End-to-end tests for the real user workflow.
- Regression tests for existing fixed-template behavior.
- Failure-path tests for invalid data, missing template slots, unsupported commentary, and `STUDIO_AI=off`.

Do not finish with only isolated unit tests when the change affects Studio generation, template binding, commentary, export, or QA.
