"""The Recap engine, from the pure helpers up to the whole workflow.

The integration tests at the bottom run the REAL pipeline over a real .pptx with the
model replaced by a stub. That is the point of injecting the client: extraction, noise
filtering, content units, enrichment, classification, the insight store, the recap and
the rendered .pptx are all exercised without a credential.

    deck(s) -> insights -> one recap -> recap.json + recap.pptx
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pptx import Presentation

from recap import jobs
from recap.config import RunPaths, new_run_paths, runs_root
from recap.metadata import DeckMetadata, deck_id_for, read_cover
from recap.progress import PHASES, STAGES, label_for, percent_done, phase_for
from recap.run import (
    RecapRequest,
    build_deck_specs,
    deck_reporter,
    period_label,
    run_recap_pipeline,
)
from recap.uploads import UploadRejected, safe_name, staged_from_store, stage_upload


# ── the stub model ───────────────────────────────────────────────────────────

#: One answer that satisfies every parser in the pipeline. Each caller reads only the
#: keys it knows, and every one of them falls back safely on a key it does not find —
#: so a single superset object drives the whole run and keeps the stub honest about
#: what the real model must return.
ANSWER = {
    "is_noise": False, "reason": "stub", "confidence": 0.9,
    "lines_of_business": ["Property"], "countries": ["Germany", "Spain"],
    "regions": ["Europe"], "segments": ["Multinational"],
    "kpis": ["GWP"], "metrics": ["GWP"], "performance_direction": "positive",
    "value": True, "evidence_element_ids": ["e1"], "rationale": "stub",
    "sub_category": None,
    "is_action_item": True, "urgency": "high",
    "action": "Confirm the Spain renewal terms", "owner": "Marsh", "deadline": "Q3",
    "title": "Growth in Germany",
    "narrative": "Germany grew on property renewals while Spain outperformed plan.",
    "executive_summary": "Growth held up across both markets with property leading.",
    "summary": "Germany anchored the quarter. Spain outperformed plan on new business.",
}


class StubLLM:
    """Answers every prompt with :data:`ANSWER`, and records what it was asked."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def call(self, *, system_prompt, user_message, response_model=None,
                   tier=None, max_completion_tokens=2048):
        self.prompts.append(system_prompt)
        return json.dumps(ANSWER)

    async def call_cheap(self, *, system_prompt, user_message, response_model=None):
        return await self.call(system_prompt=system_prompt, user_message=user_message)


# ── fixtures ─────────────────────────────────────────────────────────────────


DEFAULT_SECTIONS = (
    (
        "Performance overview",
        (
            "GWP grew 12% in Germany, driven by property renewals.",
            "Spain outperformed plan with 8% new business growth.",
            "Loss ratio improved to 61% across the portfolio.",
            "Action: confirm the Spain renewal terms before Q3.",
        ),
    ),
)


def write_deck(path: Path, *, title="Acme Corp QBR Q2 2026", sections=DEFAULT_SECTIONS) -> Path:
    """A QBR deck: a cover slide, then one content slide per section."""
    presentation = Presentation()
    cover = presentation.slides.add_slide(presentation.slide_layouts[0])
    cover.shapes.title.text = title
    cover.placeholders[1].text = "Marsh ICG\n2026-04-15"

    for heading, bullets in sections:
        body = presentation.slides.add_slide(presentation.slide_layouts[1])
        body.shapes.title.text = heading
        frame = body.placeholders[1].text_frame
        frame.text = bullets[0]
        for line in bullets[1:]:
            frame.add_paragraph().text = line

    presentation.save(path)
    return path


@pytest.fixture()
def deck(tmp_path) -> Path:
    return write_deck(tmp_path / "acme_q2_2026.pptx")


@pytest.fixture()
def paths(tmp_path) -> RunPaths:
    return RunPaths(tmp_path / "run").create()


# ── the cover slide ──────────────────────────────────────────────────────────


def test_the_cover_slide_names_the_client_and_the_period(deck):
    metadata = read_cover(deck.read_bytes())
    assert metadata.client_name == "Acme Corp"
    assert metadata.quarter == "Q2"
    assert metadata.year == "2026"
    assert metadata.meeting_date == "2026-04-15"


def test_a_period_label_is_only_carried_when_it_adds_something(deck):
    """With a quarter AND a year, a label saying "Q2 2026" says it twice — and the
    recap title would then read it twice."""
    assert read_cover(deck.read_bytes()).period_label == ""


def test_an_unreadable_deck_costs_the_run_nothing():
    """A cover that will not parse must not block an upload: the run can still go
    ahead with nothing, and the chips say so."""
    metadata = read_cover(b"not a pptx at all")
    assert metadata.is_empty()
    assert metadata.found() == []


def test_metadata_survives_a_round_trip_through_the_store():
    metadata = DeckMetadata(client_name="Acme", quarter="Q2", year="2026")
    assert DeckMetadata.from_store(metadata.as_store()) == metadata
    assert DeckMetadata.from_store({"client_name": "Acme", "unknown": "x"}).client_name == "Acme"


def test_two_decks_uploaded_together_get_different_ids():
    """Every artefact is named from the deck id, and two quarters exported from one
    template have the same filename."""
    assert deck_id_for("Q2 QBR.pptx", 0) != deck_id_for("Q2 QBR.pptx", 1)
    assert deck_id_for("Q2 QBR.pptx", 0) == "q2_qbr_0"
    assert deck_id_for("", 0) == "deck_0"


def test_the_period_reads_back_however_the_cover_stated_it():
    assert period_label(DeckMetadata(quarter="Q2", year="2026")) == "Q2 2026"
    assert period_label(DeckMetadata(period_label="H1 2026")) == "H1 2026"
    assert period_label(DeckMetadata()) is None


# ── uploads ──────────────────────────────────────────────────────────────────


def test_a_deck_is_staged_to_disk_not_into_the_browser_store(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAP_RUNS_DIR", str(tmp_path))
    staged = stage_upload("data:application/pptx;base64,YWJj", "Q2 review.pptx")
    assert staged.exists()
    assert staged.path.read_bytes() == b"abc"
    assert staged.as_store() == {"name": staged.name, "path": str(staged.path)}
    assert str(tmp_path) in str(staged.path)


def test_a_file_that_is_not_a_deck_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAP_RUNS_DIR", str(tmp_path))
    with pytest.raises(UploadRejected):
        stage_upload("data:text/plain;base64,YWJj", "notes.txt")


def test_a_filename_from_the_client_can_never_escape_the_staging_directory():
    assert "/" not in safe_name("../../etc/passwd")
    assert safe_name("") == "upload"


def test_a_staged_deck_that_has_gone_away_is_not_offered_to_a_run(tmp_path):
    """The store outlives the files it names — a restart takes the staging directory
    with it, and a run started against a missing path fails minutes later."""
    present = tmp_path / "here.pptx"
    present.write_bytes(b"x")
    rows = [{"name": "here.pptx", "path": str(present)},
            {"name": "gone.pptx", "path": str(tmp_path / "gone.pptx")}]
    assert [f.name for f in staged_from_store(rows)] == ["here.pptx"]
    assert staged_from_store(None) == []


# ── progress ─────────────────────────────────────────────────────────────────


def test_the_bar_only_ever_moves_forward():
    percents = [stage.percent for stage in STAGES]
    assert percents == sorted(percents)
    assert 0 < percents[0] and percents[-1] < 100
    assert percent_done(STAGES[-1].id, finished=True) == 100


def test_an_unknown_stage_reads_as_the_start_rather_than_crashing():
    assert percent_done(None) == 0
    assert percent_done("not-a-stage") == 0
    assert label_for(None) == "Working"
    assert phase_for("not-a-stage") is None


def test_every_stage_lights_a_rail_phase():
    known = {phase.id for phase in PHASES}
    assert all(phase_for(stage.id) in known for stage in STAGES)


def test_a_run_directory_is_never_shared(monkeypatch, tmp_path):
    monkeypatch.setenv("RECAP_RUNS_DIR", str(tmp_path))
    first, second = new_run_paths(), new_run_paths()
    assert first.root != second.root
    assert runs_root() == tmp_path
    for path in (first.inputs, first.artefacts, first.output_dir):
        assert path.is_dir()


# ── the request ──────────────────────────────────────────────────────────────


def test_the_cover_metadata_is_applied_to_every_deck_in_the_run(paths):
    """The user uploaded them as one review: a deck whose own cover was unreadable is
    still filed under the client the others named."""
    request = RecapRequest(
        deck_paths=(Path("q1.pptx"), Path("q2.pptx")),
        metadata=DeckMetadata(client_name="Acme Corp", quarter="Q2", year="2026"),
        paths=paths,
    )
    specs = build_deck_specs(request)
    assert [spec["deck_id"] for spec in specs] == ["q1_0", "q2_1"]
    assert all(spec["client_name"] == "Acme Corp" for spec in specs)
    assert all(spec["year"] == 2026 for spec in specs)


def test_a_year_that_is_not_a_year_is_dropped_rather_than_crashing_the_run(paths):
    request = RecapRequest(
        deck_paths=(Path("q1.pptx"),),
        metadata=DeckMetadata(year="not a year"),
        paths=paths,
    )
    assert build_deck_specs(request)[0]["year"] is None


def test_the_reporter_names_the_deck_only_when_there_is_more_than_one():
    seen: list[tuple[str, str]] = []
    single = deck_reporter(lambda stage, message="": seen.append((stage, message)),
                           "q2.pptx", 1, 1)
    single("extracting")
    many = deck_reporter(lambda stage, message="": seen.append((stage, message)),
                         "q2.pptx", 2, 3)
    many("extracting")
    assert seen[0] == ("extracting", "q2.pptx")
    assert seen[1] == ("extracting", "q2.pptx (2 of 3)")


# ── the whole workflow ───────────────────────────────────────────────────────


@pytest.fixture()
def run_result(deck, paths):
    """One real run over one real deck, with the model stubbed."""
    stub = StubLLM()
    stages: list[str] = []
    result = run_recap_pipeline(
        RecapRequest(
            deck_paths=(deck,),
            metadata=read_cover(deck.read_bytes()),
            paths=paths,
        ),
        report=lambda stage, message="": stages.append(stage),
        llm=stub,
    )
    return result, stages, stub


def test_a_run_produces_a_deck_a_recap_and_its_evidence(run_result):
    result, _, _ = run_result
    assert result.pptx_path.is_file() and result.pptx_path.stat().st_size > 10_000
    assert result.recap_json_path.is_file()
    assert result.insight_store_path.is_file()
    assert result.client == "Acme Corp"
    assert result.period == "Q2 2026"
    assert result.insight_count > 0


def test_the_rendered_deck_is_a_readable_powerpoint(run_result):
    """The .pptx is the deliverable — a file that python-pptx cannot reopen is not one."""
    result, _, _ = run_result
    presentation = Presentation(result.pptx_path)
    text = " ".join(
        shape.text_frame.text
        for slide in presentation.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )
    assert "Acme Corp" in text
    assert ANSWER["executive_summary"] in text


def test_the_recap_json_carries_the_takeaways_and_their_evidence(run_result):
    result, _, _ = run_result
    recap = json.loads(result.recap_json_path.read_text(encoding="utf-8"))
    assert recap["executive_summary"] == ANSWER["executive_summary"]
    assert recap["key_takeaways"], "a recap with no takeaways is an empty deck"
    assert all(t["source_content_unit_ids"] for t in recap["key_takeaways"])
    assert recap["client_name"] == "Acme Corp"


def test_every_takeaway_traces_back_to_an_insight_in_the_store(run_result):
    """The claim the deck makes and the evidence behind it must be the same run."""
    result, _, _ = run_result
    recap = json.loads(result.recap_json_path.read_text(encoding="utf-8"))
    store = json.loads(result.insight_store_path.read_text(encoding="utf-8"))
    known = {insight["content_unit_id"] for insight in store}
    for takeaway in recap["key_takeaways"]:
        assert set(takeaway["source_content_unit_ids"]) <= known


def test_the_run_reports_its_stages_in_order(run_result):
    _, stages, _ = run_result
    order = [stage.id for stage in STAGES]
    seen = [stage for stage in stages if stage in order]
    assert seen == sorted(seen, key=order.index)
    assert seen[0] == "staging" and seen[-1] == "rendering"


def test_the_run_asked_the_model_for_every_stage_that_needs_one(run_result):
    _, _, stub = run_result
    asked = " ".join(stub.prompts).lower()
    for marker in ("noise", "action item", "recap"):
        assert marker in asked, marker


def test_two_decks_make_one_recap_covering_both(tmp_path, paths):
    """Not one recap each: they share an insight store, and the recap is generated
    once everything is in it."""
    first = write_deck(tmp_path / "acme_q1.pptx", title="Acme Corp QBR Q1 2026")
    second = write_deck(
        tmp_path / "acme_q2.pptx",
        title="Acme Corp QBR Q2 2026",
        sections=(("Casualty", ("Casualty premium fell 4% in Spain on rate pressure.",
                                "Retention held at 94% across the portfolio.")),),
    )
    single = run_recap_pipeline(
        RecapRequest(deck_paths=(first,), metadata=DeckMetadata(client_name="Acme Corp"),
                     paths=paths),
        llm=StubLLM(),
    )
    both = run_recap_pipeline(
        RecapRequest(deck_paths=(first, second),
                     metadata=DeckMetadata(client_name="Acme Corp"),
                     paths=RunPaths(tmp_path / "run2").create()),
        llm=StubLLM(),
    )
    assert both.insight_count > single.insight_count
    assert both.pptx_path.is_file()


def test_a_deck_with_enough_country_narrative_gets_the_country_slide(tmp_path, paths):
    """Slide 2 of the deliverable. It is deliberately withheld from a thin deck — a
    country named once carries no narrative — so it takes a deck with real prose on
    two slides to prove the slide is reachable at all."""
    deck = write_deck(
        tmp_path / "acme_full.pptx",
        sections=(
            ("Germany", ("GWP grew 12% in Germany, driven by property renewals.",
                         "German retention held at 94% despite rate pressure.")),
            ("Spain", ("Spain outperformed plan with 8% new business growth.",
                       "Spanish casualty premium fell 4% on sustained rate pressure.")),
        ),
    )
    result = run_recap_pipeline(
        RecapRequest(deck_paths=(deck,), metadata=DeckMetadata(client_name="Acme Corp"),
                     paths=paths),
        llm=StubLLM(),
    )
    recap = json.loads(result.recap_json_path.read_text(encoding="utf-8"))
    assert {c["country"] for c in recap["country_summaries"]} == {"Germany", "Spain"}

    presentation = Presentation(result.pptx_path)
    assert len(presentation.slides) >= 2
    slide_two = " ".join(
        shape.text_frame.text for shape in presentation.slides[1].shapes
        if shape.has_text_frame
    )
    assert "Germany" in slide_two and "Spain" in slide_two


def test_a_deck_with_nothing_in_it_still_finishes(tmp_path, paths):
    """A deck of blank slides must produce an empty recap, not a crash: the failure
    the user sees should be "there was nothing to say", not a stack trace."""
    empty = Presentation()
    empty.slides.add_slide(empty.slide_layouts[6])
    path = tmp_path / "blank.pptx"
    empty.save(path)

    result = run_recap_pipeline(
        RecapRequest(deck_paths=(path,), metadata=DeckMetadata(), paths=paths),
        llm=StubLLM(),
    )
    assert result.insight_count == 0
    assert result.pptx_path.is_file()


# ── the command line ─────────────────────────────────────────────────────────


def test_the_cli_recaps_several_decks_in_one_run(deck):
    """`--file` repeats: the CLI has the same "several decks, one recap" shape the
    workspace does, because both call the same function."""
    from recap.main import _build_parser, _metadata_from

    args = _build_parser().parse_args(
        ["run", "--file", str(deck), "--file", str(deck), "--client", "Zurich"]
    )
    assert args.file == [str(deck), str(deck)]

    metadata = _metadata_from(args, [deck])
    assert metadata.client_name == "Zurich", "what was typed beats what was detected"
    assert metadata.quarter == "Q2", "and the cover slide fills in the rest"


# ── the job the workspace polls ──────────────────────────────────────────────


def test_a_finished_job_reports_the_deck_it_produced(deck, paths):
    job = jobs.start_run(
        RecapRequest(deck_paths=(deck,), metadata=DeckMetadata(client_name="Acme Corp"),
                     paths=paths),
        runner=lambda request, report: _fake_result(paths, report),
    )
    _await(job)
    state = job.snapshot()
    assert state["done"] and not state["error"]
    assert state["percent"] == 100
    assert state["filename"] == "recap.pptx"
    assert state["client"] == "Acme Corp"
    assert job.pptx_path().endswith("recap.pptx")


def test_a_failed_job_carries_the_reason_and_no_deck(deck, paths):
    def explode(request, report):
        raise RuntimeError("the template is missing")

    job = jobs.start_run(
        RecapRequest(deck_paths=(deck,), metadata=DeckMetadata(), paths=paths),
        runner=explode,
    )
    _await(job)
    state = job.snapshot()
    assert state["done"] and state["error"] == "the template is missing"
    assert job.pptx_path() is None


def test_a_running_job_reports_the_stage_it_is_in(deck, paths):
    job = jobs.RecapJob(job_id="test", request=RecapRequest(
        deck_paths=(deck,), metadata=DeckMetadata(), paths=paths))
    job.report("classifying")
    state = job.snapshot()
    assert state["step"] == "Classifying insights"
    assert state["phase"] == "classify"
    assert 0 < state["percent"] < 100


def _fake_result(paths: RunPaths, report):
    from recap.run import RecapResult

    report("rendering")
    pptx = paths.output_dir / "recap.pptx"
    pptx.write_bytes(b"deck")
    return RecapResult(
        pptx_path=pptx, recap_json_path=paths.output_dir / "recap.json",
        insight_store_path=paths.insight_store, deck_id="acme_0",
        client="Acme Corp", period="Q2 2026", takeaway_titles=["Growth in Germany"],
        action_item_count=2, insight_count=9, confidence=0.7,
    )


def _await(job, timeout: float = 10.0) -> None:
    """Wait for a job's daemon thread to finish, the way the poll does."""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline and not job.snapshot()["done"]:
        time.sleep(0.02)
    assert job.snapshot()["done"], "the job never finished"
