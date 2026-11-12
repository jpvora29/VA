"""Phase 2 step 2: story sections per shape, and the shadow that measures coverage."""
from __future__ import annotations

from langchain_core.messages import HumanMessage

from core.agents.common.answer_shape import DEFAULT_SHAPE, SHAPE_KEYS
from core.analysis.requirements import build_contract, get_requirements
from core.analysis.story import (
    DEFAULT_SHAPE as STORY_DEFAULT,
    DEFERRED,
    FILLABLE,
    NOT_OWED,
    UNSUPPORTED,
    StoryLibrary,
    StorySection,
    build_story_plan,
    get_story_library,
    load_story_library,
    section_problems,
    sections_left_open,
)
from core.turn import build_turn_spec
from core.turn import node as turn_node
from core.turn import story_shadow
from core.turn.build import spec_contract


def performance(sources=("gpr",), conditions=("material_product_movement",)):
    return build_contract("performance_assessment", conditions=conditions,
                          allowed_sources=sources)


def statuses(story):
    return {s.key: s.status for s in story.sections}


# --------------------------------------------------------------------------- #
# The shipped config
# --------------------------------------------------------------------------- #


def test_every_answer_shape_has_a_story_and_nothing_else_does():
    assert set(get_story_library().shapes) == set(SHAPE_KEYS)
    assert STORY_DEFAULT == DEFAULT_SHAPE


def test_the_shipped_sections_name_only_real_requirements_and_sections():
    known = get_requirements().requirements
    for shape, sections in get_story_library().shapes.items():
        assert section_problems(shape, sections, known) == ()


# --------------------------------------------------------------------------- #
# Building the plan
# --------------------------------------------------------------------------- #


def test_a_performance_question_can_fill_every_required_analyst_section():
    story = build_story_plan("analyst", performance())
    assert story.unfillable() == ()
    assert statuses(story)["movement"] == FILLABLE
    assert statuses(story)["what_it_means"] == FILLABLE


def test_a_section_excluded_by_the_turns_conditions_carries_the_limitation():
    story = build_story_plan("analyst", performance())
    broker = next(s for s in story.sections if s.key == "broker_view")
    assert broker.status == DEFERRED
    assert "survey" in broker.reason.lower()
    assert not broker.required  # optional, so not reported as unfillable


def test_a_shape_promise_the_contract_never_gathers_is_stated_not_dropped():
    breakdown = build_contract("breakdown", allowed_sources=["gpr"])
    story = build_story_plan("analyst", breakdown)
    unfillable = {s.key: s for s in story.unfillable()}
    assert unfillable["position"].status == NOT_OWED
    assert "breakdown" in unfillable["position"].reason
    assert unfillable["movement"].status == DEFERRED
    # Nothing it builds on can be filled, so the insight cannot be written either.
    assert unfillable["executive_insight"].status == UNSUPPORTED
    assert statuses(story)["what_it_means"] == FILLABLE  # drivers still fill


def test_an_unknown_shape_tells_the_default_story():
    story = build_story_plan("no-such-shape", performance())
    assert story.shape == DEFAULT_SHAPE
    assert [s.key for s in story.sections][:2] == ["executive_insight", "movement"]


def test_the_plan_lists_the_requirements_its_fillable_sections_draw_on():
    story = build_story_plan("driver", performance())
    assert story.requirements() == (
        "annual_movement", "product_contributors", "quarterly_comparison",
        "industry_concentration",
    )


def test_sections_left_open_are_the_fillable_ones_nothing_reached():
    story = build_story_plan("driver", performance())
    assert sections_left_open(story, ["annual_movement", "product_contributors"]) == (
        "timing", "concentration",
    )
    assert sections_left_open(story, story.requirements()) == ()


def test_a_synthesis_section_on_nothing_is_always_fillable():
    library = StoryLibrary({"analyst": (StorySection("note", "Note"),)})
    story = build_story_plan("analyst", performance(), library=library)
    assert statuses(story) == {"note": FILLABLE}


def test_the_dict_form_is_json_safe():
    import json
    json.dumps(build_story_plan("briefing", performance()).as_dict())


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def test_config_typos_are_reported_at_load(tmp_path, caplog):
    path = tmp_path / "story.yaml"
    path.write_text(
        "shapes:\n  analyst:\n"
        "    - {key: a, requirements: [nope]}\n"
        "    - {key: b, builds_on: [missing]}\n",
        encoding="utf-8",
    )
    library = load_story_library(path, known_requirements=["annual_movement"])
    assert [s.key for s in library.sections_for("analyst")] == ["a", "b"]
    assert "unknown requirement 'nope'" in caplog.text
    assert "unknown section 'missing'" in caplog.text


def test_a_broken_config_yields_an_empty_story(tmp_path):
    path = tmp_path / "story.yaml"
    path.write_text("shapes: [unclosed", encoding="utf-8")
    library = load_story_library(path, known_requirements=[])
    assert build_story_plan("analyst", performance(), library=library).sections == ()


# --------------------------------------------------------------------------- #
# The TurnSpec side
# --------------------------------------------------------------------------- #


def routing(depth="analytical", shape="analyst"):
    return {
        "table_family": "premium",
        "analysis_depth": depth,
        "output_directives": {"shape": shape, "presentation": "prose", "depth": "analyst"},
        "resolved_filters": {"Country": ["Singapore"], "Year": ["2025"]},
        "unresolved_terms": [],
    }


def test_the_spec_contract_round_trips_the_recorded_keys():
    spec = build_turn_spec("How was Zurich's performance in Singapore in 2025?", routing())
    contract = spec_contract(spec)
    assert contract.keys() == spec.requirements
    assert tuple(r.key for r in contract.deferred) == spec.deferred


def capture_events(monkeypatch, module):
    events = []
    monkeypatch.setattr(module, "log_event",
                        lambda _logger, name, *a, **kw: events.append((name, kw)))
    return events


def test_the_turn_node_logs_the_sections_the_turn_cannot_fill(monkeypatch):
    events = capture_events(monkeypatch, turn_node)
    state = {"messages": [HumanMessage("Break down Zurich's premium in Singapore by product")],
             "routing_context": routing(shape="analyst")}
    turn_node.turn_spec_node(state)
    name, fields = events[-1]
    assert name == "turn_spec_built"
    assert fields["story_unfillable"].get("position") == NOT_OWED


def test_story_coverage_logs_what_the_plan_leaves_open(monkeypatch):
    events = capture_events(monkeypatch, story_shadow)
    story_shadow.record_story_coverage(
        "driver", performance(), ["annual_movement"], stage="planned", node="t",
    )
    name, fields = events[-1]
    assert name == "story_coverage" and fields["stage"] == "planned"
    assert "drivers" in fields["left_open"]


def test_story_coverage_is_silent_when_the_shadow_is_off(monkeypatch):
    events = capture_events(monkeypatch, story_shadow)
    monkeypatch.setenv("TURN_SPEC", "off")
    story_shadow.record_story_coverage("driver", performance(), [], stage="planned", node="t")
    assert events == []


def test_story_coverage_never_raises(monkeypatch):
    events = capture_events(monkeypatch, story_shadow)

    def boom(*_a, **_kw):
        raise RuntimeError("bad config")

    monkeypatch.setattr(story_shadow, "build_story_plan", boom)
    story_shadow.record_story_coverage("driver", performance(), [], stage="planned", node="t")
    assert events[-1][0] == "story_coverage_error"
