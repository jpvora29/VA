"""The context chip: what a prompt is made of, and how full its window got.

Covers the pure splitter (:mod:`core.context_meter`), its wiring into the turn's
usage meter (:mod:`core.run_trace`), and the footer chip
(:mod:`ui.components.context_meter`). No model is called.

Run:  pytest tests/test_context_meter.py -q
"""
from __future__ import annotations

import json
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from core.context_meter import (
    DEFAULT_WINDOW,
    context_summary,
    context_window,
    measure_prompt,
    scale_to_tokens,
    split_text,
)
from core.run_trace import ModelCall, RunRecorder, UsageCallbackHandler, build_trace
from ui.components.context_meter import context_meter, format_share, node_label


def _text(component) -> str:
    return json.dumps(component.to_plotly_json(), default=str, ensure_ascii=False)


# ── splitting a prompt ───────────────────────────────────────────────────────


def test_solver_prompt_blocks_land_in_their_categories():
    prompt = (
        "You gather evidence.\n"
        "[PRIMARY FLOW] gpr\n"
        "[SCHEMA for flow=\"gpr\"]\n{\"GPR\": [\"Premium\"]}\n"
        "[DOMAIN RULES — always apply]\n## gpr-default-timeframe\nLatest year.\n"
        "[LENS TO APPLY]\nTrend.\n"
        "[RESULTS FROM EARLIER STEPS — build on these]\n[{\"rows\": []}]\n"
        "[SUB-QUESTION — answer only this]\nWhy did premium fall?"
    )
    split = split_text(prompt, "instructions")
    assert set(split) == {"instructions", "schema", "rules", "history", "question"}
    assert sum(split.values()) == len(prompt)


def test_signature_inputs_land_in_their_categories():
    """The signature layer labels every input `[FIELD_NAME] — desc`."""
    prompt = (
        "[USER_QUERY] — the question\nTop carriers?\n\n"
        "[CONVERSATION_HISTORY]\n[\"earlier\"]\n\n"
        "[VALID_VALUES]\n{\"Country\": [\"Canada\"]}\n\n"
        "[RULES]\nUse Carrier_Group.\n\n"
        "[SQL_OUTPUT]\n[{\"Premium\": 1}]"
    )
    split = split_text(prompt, "question")
    assert set(split) == {"question", "history", "schema", "rules", "data"}


def test_a_header_that_runs_long_and_wraps_is_still_a_header():
    """Real headers close their bracket lines later: only the lead-in is read."""
    prompt = ("intro\n[LENS TO APPLY — follow this shape and interpretation. Where a named\n"
              "calculation above covers a step, call it.]\nTrend body.")
    assert set(split_text(prompt, "instructions")) == {"instructions", "rules"}


def test_a_skill_bodys_own_heading_stays_inside_the_rules():
    prompt = "[DOMAIN RULES]\n## gpr-planner-base\n[GPR PLANNER BASE]\nUse Carrier_Group."
    assert set(split_text(prompt, "instructions", nested=True)) == {"rules"}
    # A signature's user prompt is flat: an unknown field is a top-level input.
    assert set(split_text("[RULES]\nx\n[ROUTE]\ngpr", "question")) == {"rules", "question"}


def test_a_real_solver_prompt_splits_into_rules_schema_history_and_question(monkeypatch):
    from core.agents.analyst import common
    from core.agents.analyst.generic_solver import _ROLE
    from core.schemas.analyst_subgraph import SchemaSlice

    monkeypatch.setattr(common, "get_schema", lambda flow: {"GPR": [{"Column Name": "Premium"}]})
    prompt = common._solver_prompt(
        role=_ROLE, question="Why did premium fall?", sub_question="Why did premium fall?",
        lens="temporal_trend", flow="gpr", route="premium", schema_slice=SchemaSlice(),
        prior_digest='[{"rows": []}]')
    split = split_text(prompt, "instructions", nested=True)
    assert {"instructions", "rules", "schema", "history", "question"} <= set(split)
    assert "data" not in split  # nothing in a solver's brief is evidence
    assert max(split, key=split.get) == "rules"


def test_a_lowercase_bracket_is_text_not_a_header():
    text = "[note] keep going\n[x] item"
    assert split_text(text, "question") == {"question": len(text)}


def test_measure_prompt_counts_messages_by_role_and_the_tool_schemas():
    tools = [{"type": "function", "function": {"name": "run_sql", "parameters": {}}}]
    call = AIMessage(content="", tool_calls=[{"id": "1", "name": "run_sql", "args": {"sql": "x"}}])
    chars = measure_prompt(
        [SystemMessage(content="Gather evidence."), HumanMessage(content="Why?"),
         call, ToolMessage(content="[1, 2, 3]", tool_call_id="1")],
        tools,
    )
    assert chars["instructions"] == len("Gather evidence.")
    assert chars["question"] == len("Why?")
    assert chars["tools"] == len(json.dumps(tools))
    assert chars["working"] > len("[1, 2, 3]")  # the call AND its result


def test_scaling_sums_exactly_to_the_reported_input_tokens():
    scaled = scale_to_tokens({"rules": 333, "schema": 333, "question": 334}, 1001)
    assert sum(scaled.values()) == 1001


def test_without_reported_usage_the_split_is_an_estimate():
    assert scale_to_tokens({"rules": 400}, 0) == {"rules": 100}


def test_context_windows_follow_the_model_family():
    assert context_window("gpt-4.1-mini") == 1_047_576
    assert context_window("gpt-41-mini") == 1_047_576
    assert context_window("gpt-4o-mini") == 128_000
    assert context_window("some-custom-deployment") == DEFAULT_WINDOW


# ── the turn meter ───────────────────────────────────────────────────────────


def test_the_callback_records_what_each_prompt_was_made_of():
    recorder = RunRecorder()
    handler = UsageCallbackHandler(recorder)
    run_id = uuid4()
    tools = [{"type": "function", "function": {"name": "compute_metric"}}]
    handler.on_chat_model_start(
        {"kwargs": {"deployment_name": "gpt-4.1-mini"}},
        [[SystemMessage(content="[DOMAIN RULES]\n" + "r" * 400),
          HumanMessage(content="Why did premium fall?")]],
        run_id=run_id, metadata={"langgraph_node": "model"},
        invocation_params={"tools": tools},
    )
    message = AIMessage(content="x", usage_metadata={
        "input_tokens": 150, "output_tokens": 10, "total_tokens": 160})
    handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id)
    (call,) = recorder.calls
    assert sum(call.context.values()) == 150
    assert {"rules", "tools", "question"} <= set(call.context)


def test_the_peak_is_the_prompt_closest_to_its_own_window():
    """A 100k prompt on a 128k model is fuller than a 200k prompt on a 1M one."""
    calls = [ModelCall("model", "gpt-4.1-mini", 200_000, 0, 200_000, 0, 1, {"rules": 200_000}),
             ModelCall("writer_node", "gpt-4o-mini", 100_000, 0, 100_000, 0, 1, {"data": 100_000})]
    peak = context_summary(calls)["peak"]
    assert (peak["node"], peak["window"]) == ("writer_node", 128_000)


def test_the_trace_carries_the_context_view():
    calls = [ModelCall("model", "gpt-4.1-mini", 900, 50, 950, 300, 10,
                       {"rules": 600, "question": 300}),
             ModelCall("model", "gpt-4.1-mini", 1200, 50, 1250, 600, 10,
                       {"rules": 600, "working": 600})]
    context = build_trace([], calls, 100)["context"]
    assert context["peak"]["used"] == 1200
    assert context["turn"] == {
        "calls": 2, "input_tokens": 2100, "cached_tokens": 900,
        "split": [{"key": "rules", "tokens": 1200}, {"key": "working", "tokens": 600},
                  {"key": "question", "tokens": 300}],
    }


def test_a_turn_with_no_measured_call_has_no_context_view():
    assert build_trace([], [ModelCall("w", "gpt", 1, 1, 2)], 100)["context"] == {}


# ── the chip ─────────────────────────────────────────────────────────────────


def _run():
    calls = [ModelCall("model", "gpt-4.1-mini", 14_000, 200, 14_200, 7_000, 900,
                       {"instructions": 1_000, "rules": 3_000, "tools": 2_000,
                        "working": 7_000, "question": 1_000})]
    return build_trace([], calls, 4_000)


def test_the_chip_says_how_full_the_window_is():
    text = _text(context_meter(_run()))
    assert "1.3% context" in text


def test_hovering_splits_the_fullest_prompt_and_the_whole_turn():
    text = _text(context_meter(_run()))
    for label in ("Context window", "Rules & skills", "Tool definitions",
                  "Tool calls & results", "Free space", "Whole turn", "Fullest prompt",
                  "Analysis step · gpt-4.1-mini", "served from cache"):
        assert label in text, label


def test_a_full_window_is_called_out_in_words_not_colour_alone():
    calls = [ModelCall("writer_node", "gpt-4o-mini", 120_000, 0, 120_000, 0, 1,
                       {"data": 120_000})]
    assert "near limit" in _text(context_meter(build_trace([], calls, 10)))


def test_an_answer_without_a_context_view_has_no_chip():
    assert context_meter(None) is None
    assert context_meter({"elapsed_ms": 10}) is None
    assert context_meter({"context": {}}) is None


def test_reader_formatting():
    assert format_share(14_000, 1_047_576) == "1.3%"
    assert format_share(50, 100) == "50%"
    assert format_share(1, 1_000_000) == "<0.1%"
    assert node_label("model") == "Analysis step"
    assert node_label("gimmi_insight") == "Gimmi insight"
