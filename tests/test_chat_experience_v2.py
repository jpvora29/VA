"""The chat v2 pass: meter, memory, speculation, clarification, charts, early answers.

Each block pins one behaviour a user can see or feel:

    run meter        every answer knows its time, model calls and tokens
    memory           the welcome and clarification offer the user's own scope
    speculation      the ambiguity check overlaps the intent classifier
    clarification    questions carry why / recommended / skip
    charts           units on every number, the waterfall closes on its net
    early answer     the answer is shown before the follow-ups are written
    persistence      reopening a chat does not rewrite it

Run:  pytest tests/test_chat_experience_v2.py -q -o pythonpath=.
"""
from __future__ import annotations

import contextvars
import json
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import core.graph.hitl as hitl
from core.graph import speculation
from core.memory.focus import FocusScope, rank_focus, scope_from_chips
from core.run_trace import (ModelCall, RunRecorder, StepTiming, UsageCallbackHandler,
                            build_trace, format_duration, format_tokens, merge_steps)
from core.schemas.hitl import ClarifyDecision, ClarifyOption, ClarifyQuestion
from core.schemas.routing import RoutingContext
from ui.chart_functions import (format_value, generate_chart, measure_unit, semantic_colors,
                                CURRENT_COLOR, BENCHMARK_COLOR)
from ui.components.run_meta import conversation_usage, run_meta


# ── run meter ────────────────────────────────────────────────────────────────


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_the_recorder_times_each_step_from_one_entry_to_the_next():
    clock = _Clock()
    recorder = RunRecorder(clock=clock)
    recorder.enter("context_filler", "Understanding your question")
    clock.now = 1.2
    recorder.enter("intent_classifier", "Understanding your question")
    clock.now = 2.0
    recorder.enter("gpr_agent", "Reviewing premium data")
    clock.now = 5.5
    trace = recorder.finish()
    assert trace["elapsed_ms"] == 5500
    # Two nodes with one label read as ONE step with their combined time.
    assert [(s["label"], s["duration_ms"]) for s in trace["steps"]] == [
        ("Understanding your question", 2000), ("Reviewing premium data", 3500)]


def test_internal_nodes_are_timed_but_not_listed():
    recorder = RunRecorder(clock=_Clock())
    recorder.enter("tools")
    recorder.enter("model")
    assert recorder.finish()["steps"] == []


def test_the_trace_totals_tokens_by_node():
    calls = [ModelCall("writer", "gpt", 100, 40, 140, 20, 900),
             ModelCall("writer", "gpt", 10, 5, 15, 0, 100),
             ModelCall("planner", "gpt-mini", 50, 10, 60, 0, 300)]
    trace = build_trace([], calls, 1500)
    assert trace["llm_calls"] == 3
    assert trace["tokens"] == {"input_tokens": 160, "output_tokens": 55,
                               "total_tokens": 215, "cached_tokens": 20}
    assert trace["by_node"]["writer"] == {"calls": 2, "total_tokens": 155, "duration_ms": 1000}
    assert trace["models"] == ["gpt", "gpt-mini"]


def test_merge_steps_does_not_mutate_its_input():
    steps = [StepTiming("a", "X", 0, 10), StepTiming("b", "X", 10, 5)]
    merged = merge_steps(steps)
    assert merged[0].duration_ms == 15 and steps[0].duration_ms == 10


def test_the_callback_meters_every_model_call_with_its_node():
    """A direct invoke (the narrator) is metered too — it never reported itself."""
    recorder = RunRecorder(clock=_Clock())
    handler = UsageCallbackHandler(recorder)
    run_id = uuid4()
    handler.on_chat_model_start({"kwargs": {"deployment_name": "gpt-4.1"}}, [[]],
                                run_id=run_id, metadata={"langgraph_node": "writer_node"})
    message = AIMessage(content="x", usage_metadata={
        "input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500})
    handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id)
    (call,) = recorder.calls
    assert (call.node, call.model, call.total_tokens) == ("writer_node", "gpt-4.1", 1500)


def test_the_callback_falls_back_to_llm_output_usage():
    recorder = RunRecorder(clock=_Clock())
    handler = UsageCallbackHandler(recorder)
    run_id = uuid4()
    handler.on_llm_start({}, ["p"], run_id=run_id, metadata={})
    handler.on_llm_end(LLMResult(generations=[[]], llm_output={
        "token_usage": {"prompt_tokens": 7, "completion_tokens": 3}}), run_id=run_id)
    assert recorder.calls[0].total_tokens == 10


def test_meter_formatting_reads_like_a_person_wrote_it():
    assert format_tokens(12345) == "12.3k"
    assert format_tokens(999) == "999"
    assert format_duration(840) == "0.8s"
    assert format_duration(75_000) == "1m 15s"


def test_the_chip_says_time_and_tokens_and_opens_into_the_timeline():
    run = build_trace([StepTiming("w", "Writing the insight", 0, 800)],
                      [ModelCall("w", "gpt", 900, 300, 1200)], 8400)
    chip = run_meta(run)
    text = json.dumps(chip.to_plotly_json(), default=str)
    assert "8.4s" in text and "1.2k tokens" in text and "Writing the insight" in text


def test_an_answer_without_a_trace_has_no_chip():
    assert run_meta(None) is None
    assert run_meta({"elapsed_ms": 0}) is None


def test_conversation_usage_sums_every_metered_answer():
    trace = build_trace([], [ModelCall("w", "gpt", 1, 1, 2)], 1000)
    totals = conversation_usage([{"type": "AIMessage", "run": trace},
                                 {"type": "HumanMessage"},
                                 {"type": "AIMessage", "run": trace}])
    assert totals == {"answers": 2, "total_tokens": 4, "elapsed_ms": 2000, "llm_calls": 2}


# ── memory ───────────────────────────────────────────────────────────────────


def _asked(carrier="", country="", text="q"):
    return {"kind": "question", "content": text,
            "meta": {"scope": {k: v for k, v in (("carrier", carrier), ("country", country)) if v}}}


def test_focus_ranks_by_frequency_then_recency():
    episodes = [_asked("AXA", "France", "a"), _asked("Zurich", "Canada", "b"),
                _asked("Zurich", "Canada", "c"), _asked("AXA", "France", "d"),
                _asked("Chubb", "Canada", "e")]
    focus = rank_focus(episodes)
    # Two ties at two mentions: AXA/France was seen more recently (first).
    assert [s.label for s in focus.scopes] == ["AXA · France", "Zurich · Canada", "Chubb · Canada"]
    assert focus.countries[0] == "Canada"
    assert focus.recent_questions == ("a", "b", "c")


def test_a_focus_scope_becomes_an_editable_question():
    assert FocusScope("Zurich", "Canada").question() == "How is Zurich performing in Canada this year?"


def test_only_single_valued_chips_are_remembered():
    chips = [{"key": "carrier", "value": "Zurich"}, {"key": "country", "value": "Canada, France"},
             {"key": "period", "value": "2025"}, {"key": "product", "value": "Property"}]
    assert scope_from_chips(chips) == {"carrier": "Zurich", "period": "2025"}


def test_an_empty_history_remembers_nothing():
    assert rank_focus([]).is_empty


# ── speculation ──────────────────────────────────────────────────────────────


_MARK: contextvars.ContextVar = contextvars.ContextVar("mark", default="unset")


def test_a_speculation_runs_in_the_callers_context_and_is_taken_once():
    token = _MARK.set("turn-7")
    try:
        speculation.start("k1", lambda: _MARK.get())
    finally:
        _MARK.reset(token)
    future = speculation.take("k1")
    assert future.result(timeout=5) == "turn-7"
    assert speculation.take("k1") is None


def test_starting_twice_under_one_key_runs_once():
    calls = []
    first = speculation.start("k2", lambda: calls.append(1) or len(calls))
    second = speculation.start("k2", lambda: calls.append(1) or len(calls))
    assert first is second
    speculation.take("k2").result(timeout=5)
    assert calls == [1]


def test_the_ambiguity_source_collects_a_speculated_decision(monkeypatch):
    asked = ClarifyDecision(needs_clarification=True, questions=[ClarifyQuestion(
        question="By 'performance', do you mean premium growth or broker perception?",
        header="Metric",
        options=[ClarifyOption(label="Premium", recommended=True),
                 ClarifyOption(label="Broker perception")])])

    def never(**_):
        raise AssertionError("the decider must not run twice")

    speculation.start("ambiguity:m9", lambda: asked)
    monkeypatch.setattr(hitl, "_CLARIFY_DECIDER", never)
    ctx = hitl.ClarifyContext(query="q", routing_context=None, valid_values={},
                              speculation_key="ambiguity:m9")
    (question,) = hitl.AmbiguityClassifierSource().gather(ctx)
    assert question["header"] == "Metric"


# ── clarification ────────────────────────────────────────────────────────────


class _Decider:
    def __init__(self, decision):
        self.decision = decision

    def __call__(self, **_):
        return self.decision


def _scoped_state(text="How is Zurich performing?"):
    return {"messages": [HumanMessage(content=text, id="m1")],
            "routing_context": RoutingContext(
                table_family="premium", intent_type="new_question",
                resolved_filters={"Carrier_Group": ["ZURICH GROUP"], "Country": ["Canada"]})}


def test_the_model_may_ask_two_questions_with_one_recommendation_each(monkeypatch):
    two = ClarifyDecision(needs_clarification=True, questions=[
        ClarifyQuestion(question="Which period — 2025 to date or full 2024?", header="Period",
                        why="2025 is only partly loaded.",
                        options=[ClarifyOption(label="2025 to date", recommended=True),
                                 ClarifyOption(label="Full 2024", recommended=True)]),
        ClarifyQuestion(question="Against the default peers or your custom set?", header="Peers",
                        options=[ClarifyOption(label="Default"), ClarifyOption(label="Custom")]),
    ])
    monkeypatch.setattr(hitl, "_CLARIFY_DECIDER", _Decider(two))
    questions = hitl.clarify_decide(_scoped_state())["clarify_questions"]
    assert [q["id"] for q in questions] == ["llm:ambiguity", "llm:ambiguity:1"]
    assert questions[0]["why"] == "2025 is only partly loaded."
    assert [o["recommended"] for o in questions[0]["options"]] == [True, False]


def test_a_skipped_question_writes_no_filter_and_says_use_the_default(monkeypatch):
    state = _scoped_state()
    state["clarify_questions"] = [{"id": "mandatory:country", "kind": "mandatory_filter",
                                   "header": "Market", "column": "Country", "entity_kind": "country"}]
    monkeypatch.setattr(hitl, "interrupt", lambda payload: {"mandatory:country": hitl.SKIP_ANSWER})
    update = hitl.clarify_gate(state)
    assert update["routing_context"].resolved_filters["Country"] == ["Canada"]
    assert "no preference" in update["clarification"]


def test_missing_scope_offers_the_users_own_markets_first(monkeypatch):
    from core.memory import focus as focus_module

    monkeypatch.setattr(focus_module, "user_focus", lambda uid: rank_focus(
        [_asked("Zurich", "Canada"), _asked("Zurich", "Canada"), _asked("AXA", "France")]))
    options = hitl.remembered_options(7, "country")
    assert [o["label"] for o in options] == ["Canada", "France"]
    assert options[0]["recommended"] and not options[1]["recommended"]
    assert hitl.remembered_options(None, "country") == []


def test_the_card_numbers_its_options_flags_the_recommendation_and_offers_skip():
    from ui.components.chatbot import CLARIFY_SKIP, clarify_card

    card = clarify_card({"kind": "clarify", "questions": [{
        "id": "q1", "header": "Metric", "question": "Which one?", "why": "They differ.",
        "options": [{"label": "Premium", "recommended": True}, {"label": "Score"}]}]})
    text = json.dumps(card.to_plotly_json(), default=str)
    assert "Recommended" in text and "They differ." in text
    assert CLARIFY_SKIP in text and "data-key" in text


def test_the_custom_peer_card_has_no_skip():
    from ui.components.chatbot import CLARIFY_SKIP, clarify_card

    card = clarify_card({"kind": "custom_peer_mismatch", "question": "Keep peers?",
                         "options": [{"label": "Keep"}, {"label": "Pick new peers"}]})
    assert CLARIFY_SKIP not in json.dumps(card.to_plotly_json(), default=str)


# ── charts ───────────────────────────────────────────────────────────────────


def _spec(**kw):
    return SimpleNamespace(y_title=kw.get("y_title", ""), y=kw.get("y", []))


def test_the_unit_is_read_from_the_measure():
    assert measure_unit(_spec(y=["Marsh Premium"])) == "money"
    assert measure_unit(_spec(y_title="Share of wallet (%)", y=["x"])) == "pct"
    assert measure_unit(_spec(y=["NPS score"])) == ""


def test_values_carry_their_unit_and_sign():
    assert format_value(1_240_000, "money") == "$1.2M"
    assert format_value(-20, "money", signed=True) == "-$20"
    assert format_value(60, "money", signed=True) == "+$60"
    assert format_value(41.03, "pct") == "41.0%"


def test_colour_says_current_versus_prior_and_subject_versus_benchmark():
    assert semantic_colors(["2024", "2025"])[1] == CURRENT_COLOR
    assert semantic_colors(["2025", "2024"])[0] == CURRENT_COLOR
    assert semantic_colors(["Marsh Premium", "Carrier Premium"]) == [BENCHMARK_COLOR, CURRENT_COLOR]
    assert semantic_colors(["Premium"]) == [CURRENT_COLOR]


def test_the_waterfall_closes_on_its_real_net_change():
    frame = pd.DataFrame({"Product line": ["Marine", "Casualty", "Property"],
                          "Change vs prior year": [-20, 30, 60]})
    figure, _ = generate_chart(frame, {"chart_type": "waterfall", "x": "Product line",
                                       "y": ["Change vs prior year"]})
    trace = figure.data[0]
    assert list(trace.x)[-1] == "Net change"
    assert list(trace.text)[-1] == "+$70"


def test_a_long_ranking_is_drawn_sideways():
    frame = pd.DataFrame({"Carrier": [f"Carrier number {i}" for i in range(9)],
                          "Premium": [float(i * 10) for i in range(9)]})
    figure, _ = generate_chart(frame, {"chart_type": "bar", "x": "Carrier", "y": ["Premium"]})
    assert figure.data[0].orientation == "h"


def test_periods_are_never_turned_on_their_side():
    frame = pd.DataFrame({"Quarter": ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"],
                          "Premium": [1.0, 2, 3, 4, 5, 6, 7, 8]})
    figure, _ = generate_chart(frame, {"chart_type": "bar", "x": "Quarter", "y": ["Premium"]})
    assert figure.data[0].orientation != "h"


# ── early answer ─────────────────────────────────────────────────────────────


def test_the_early_transcript_is_marked_running_and_distinct_from_the_final():
    from ui.chat_turn import TurnRequest, early_job_id, provisional_transcript
    from ui.jobs import Job

    job = Job("t1")
    request = TurnRequest("t1", 1, {"messages": [{"type": "HumanMessage", "content": "q"}]}, None)

    def commit(chat, state):
        chat["messages"].append({"type": "AIMessage", "content": state["answer"]})
        return chat

    early = provisional_transcript(request, job, {"answer": "A"}, commit)
    assert early["_running"] is True and early["_job_id"] == early_job_id(job.id)
    assert early["messages"][-1]["content"] == "A"
    assert request.transcript["messages"][-1]["type"] == "HumanMessage", "input not mutated"


def test_poll_sends_the_early_answer_once_then_the_final_one(monkeypatch):
    from ui import callbacks
    from ui.chat_turn import early_job_id
    from ui.jobs import Job, _JOBS

    job = Job("t-early", user_id=3)
    job.early_transcript = {"_job_id": early_job_id(job.id), "messages": ["early"]}
    monkeypatch.setitem(_JOBS, "t-early", job)
    user = {"id": 3}
    cursor = {"thread_id": "t-early", "selection_id": "s1", "job_id": None}
    first = callbacks.poll_job(1, cursor, user)
    assert first["transcript"] == job.early_transcript and not first["done"]
    seen = dict(cursor, job_id=early_job_id(job.id))
    assert callbacks.poll_job(2, seen, user)["transcript"] is None
    job.done, job.transcript = True, {"_job_id": job.id, "messages": ["final"]}
    assert callbacks.poll_job(3, seen, user)["transcript"] == job.transcript


# ── persistence ──────────────────────────────────────────────────────────────


@pytest.fixture()
def repository(monkeypatch):
    from core.store import conversations as repo
    from core.store.db import metadata

    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    metadata.create_all(engine)
    monkeypatch.setattr(repo, "app_engine", engine)
    yield repo
    engine.dispose()


def test_reopening_a_chat_does_not_rewrite_it(repository):
    from sqlalchemy import select

    from core.store.db import conversations, users

    with repository.app_engine.begin() as conn:
        conn.execute(users.insert().values(id=5, username="u"))
    chat = {"thread_id": "c1", "_job_id": "j", "messages": [{"type": "HumanMessage", "content": "q"}]}
    assert repository.save_conversation(5, "c1", chat)
    with repository.app_engine.connect() as conn:
        before = conn.execute(select(conversations.c.updated_at)).scalar_one()
    assert repository.save_chat_edit(5, "c1", json.loads(json.dumps(chat)))
    with repository.app_engine.connect() as conn:
        after = conn.execute(select(conversations.c.updated_at)).scalar_one()
    assert before == after


# ── round 2: markets, subject, charts, deltas, table formats ─────────────────


from core.analytics.markets import best_match, market_scopes, resolve_subject  # noqa: E402


def test_one_carrier_filter_is_the_subject():
    subject, scope = resolve_subject({"Carrier_Group": ["GENERALI"], "Country": "Singapore"})
    assert subject == "GENERALI" and scope["Carrier_Group"] == ["GENERALI"]


def test_several_matching_carriers_narrow_to_the_one_named():
    subject, scope = resolve_subject(
        {"Carrier_Group": ["GENERALI GLOBAL CORPORATE", "GENERALI"]}, ["Generali"])
    assert subject == "GENERALI" and scope["Carrier_Group"] == "GENERALI"


def test_a_carrier_only_mentioned_is_matched_and_added():
    subject, scope = resolve_subject({"Country": "Singapore"}, ["Generali"],
                                     matcher=lambda f, c, t: ["GENERALI"])
    assert subject == "GENERALI" and scope["Carrier_Group"] == "GENERALI"


def test_no_carrier_at_all_is_a_market_question():
    assert resolve_subject({"Country": "Singapore"})[0] == ""


def test_best_match_prefers_the_named_whole_word_then_the_shortest():
    assert best_match(["AXA XL", "AXA"], ["AXA"]) == "AXA"


def test_each_named_country_gets_its_own_scope():
    scopes = market_scopes({"Country": ["Singapore", "Hong Kong"], "Year": 2025})
    assert [(m, s["Country"]) for m, s in scopes] == [("Singapore", "Singapore"),
                                                      ("Hong Kong", "Hong Kong")]
    assert market_scopes({"Country": "Singapore"}) == [("", {"Country": "Singapore"})]


def _pack(subject="GENERALI", scale=1.0):
    from core.analytics.positioning import PositioningPack, SlicePosition

    return PositioningPack(tuple(
        SlicePosition(name, carrier_premium=v * scale, marsh_premium=v * 3,
                      share_of_wallet=w, share_of_portfolio=p, rank=2, rank_of=5,
                      prior_premium=v * 0.9)
        for name, v, w, p in (("Property", 4e6, 31.6, 41.5), ("Casualty", 3e6, 34.4, 30.7),
                              ("Marine", 2e6, 37.0, 18.5), ("Cyber", 1e6, 25.0, 9.3))
    ), "Product_Line", (), subject)


def test_a_multi_market_question_gets_market_charts_not_pooled_ones():
    from core.answers.chart_plan import build_chart_plan

    markets = [("Singapore", _pack()), ("Hong Kong", _pack(scale=0.6))]
    rows = [{"Quarter": "Q1", "Singapore": 1.0, "Hong Kong": 0.5},
            {"Quarter": "Q2", "Singapore": 1.2, "Hong Kong": 0.6}]
    plan = build_chart_plan(_pack(), scope={"Year": 2025}, markets=markets,
                            market_quarterly_rows=rows)
    assert [(c.key, c.chart_type) for c in plan] == [
        ("market_compare", "bar"), ("market_quarterly", "line"), ("position_map", "bubble")]
    bubble = plan[-1]
    assert bubble.series == ("Market",) and {r["Market"] for r in bubble.rows} == {"Singapore", "Hong Kong"}


def test_the_position_map_draws_as_sized_labelled_bubbles():
    from core.answers.chart_plan import ChartInputs, position_map

    view = position_map(ChartInputs(pack=_pack())).as_view()
    frame = pd.DataFrame(view["rows"])
    figure, _ = generate_chart(frame, view["chart_data"])
    trace = figure.data[0]
    assert trace.mode == "markers+text" and list(trace.text) == ["Property", "Casualty", "Marine", "Cyber"]
    assert figure.layout.xaxis.ticksuffix == "%"


def test_market_claims_are_kept_apart_and_named():
    from core.answers.grounded import AnswerRequest, compose_answer

    evidence = tuple(
        {"flow": "gpr", "lens": "positioning", "sql": "-- p",
         "rows": [{"Country": market, **row} for row in pack.numeric_rows()]}
        for market, pack in (("Singapore", _pack()), ("Hong Kong", _pack(scale=0.6)))
    )
    answer = compose_answer(AnswerRequest("How is Generali performing?", evidence))
    assert "### Singapore" in answer.text and "### Hong Kong" in answer.text


def test_signed_changes_become_coloured_arrows():
    from ui.components.deltas import mark_deltas

    out = mark_deltas("- Property ▲ 14.2% and Marine -$20 (-33.3%) over 2024-2025\n|---:|\nx < y")
    assert out.count("delta-up") == 1 and out.count("delta-down") == 2
    assert "2024-2025" in out and "|---:|" in out and "&lt;" in out
    assert out.startswith("- Property")


def test_untyped_columns_are_formatted_by_what_they_hold():
    from ui.components import evidence as ev

    assert ev.inferred_kind("Premium", [12_345_678.9]) == ev.P.MONEY_MILLIONS
    # Millions even below a million: never raw dollars (core.analytics.money_units).
    assert ev.inferred_kind("Premium", [940_000.0]) == ev.P.MONEY_MILLIONS
    assert ev.inferred_kind("Share_of_Wallet", [0.195]) == ev.PERCENT_FRACTION
    assert ev.inferred_kind("YoY_%", [12.34]) == ev.P.PERCENT
    assert ev.inferred_kind("Year", [2024.0]) == ev.NUMBER
    assert ev.inferred_kind("Score", [3.456]) == ev.DECIMAL


def test_new_figures_have_one_decimal_and_old_records_replay_at_two():
    from core.answers.facts import figure_precision, format_value as render

    assert render(54.5454, "percent") == "54.5%"
    assert render(1_254_000, "currency") == "$1.3M"
    assert render(2_480_000_000, "currency") == "$2.5B"
    with figure_precision(2):
        assert render(54.5454, "percent") == "54.55%"
        assert render(1_254_000, "currency") == "$1.25m"


# ── round 3: answer card v3, geography, units ─────────────────────────────────


def test_every_arrow_is_coloured_even_without_a_figure():
    from ui.components.deltas import mark_deltas

    out = mark_deltas("rank ▲ up two, share ▼, premium ▲ +14.2%")
    assert out.count("delta-up") == 2 and out.count("delta-down") == 1
    assert "▲ 14.2%" in out and "+" not in out.replace("delta delta", "")


def test_a_question_naming_no_country_gets_a_country_view_first():
    from core.analytics.markets import build_geography_views
    from core.answers.chart_plan import build_chart_plan

    calls = []

    def build(**kwargs):
        calls.append(kwargs["dimension"])
        return _pack()

    by_country, by_region = build_geography_views({"Carrier_Group": "GENERALI"},
                                                  subject="GENERALI", build=build)
    assert calls == ["Country"] and by_country is not None and by_region is None
    assert build_geography_views({"Country": "Singapore"}, subject="X", build=build) == (None, None)
    plan = build_chart_plan(_pack(), scope={"Year": 2025}, by_country=_pack())
    assert plan[0].key == "country_premium" and plan[0].tab == "Premium by country"


def test_the_kpis_come_from_the_product_table_and_name_the_largest_market():
    from ui.answer_layout import scorecards
    from ui.evidence import EvidenceView

    kinds = {"Carrier premium": "money", "Marsh premium": "money"}
    country = EvidenceView("By country", ["Country", "Marsh premium", "Carrier premium"],
                           [{"Country": "China", "Marsh premium": 30.0, "Carrier premium": 12.0},
                            {"Country": "Canada", "Marsh premium": float("nan"),
                             "Carrier premium": float("nan")}], column_kinds=kinds, unit="M")
    product = EvidenceView("By product", ["Product line", "Marsh premium", "Carrier premium"],
                           [{"Product line": "Property", "Marsh premium": 30.0, "Carrier premium": 12.0}],
                           column_kinds=kinds, unit="M")
    (card,) = scorecards([country, product])
    assert card.market == "" and card.top_line == "Property" and card.premium == 12.0
    assert card.extras["top_market"] == "China"


def test_every_section_is_one_numbered_takeaway():
    from ui.answer_layout import split_sections
    from ui.components.answer_summary import takeaway_list

    body = "### Growth\n" + "\n".join(f"- point {i}" for i in range(7)) + "\n\n### Mix\n- one"
    label, rows = takeaway_list(*split_sections(body))
    assert label.children == "Key takeaways"
    assert [r.children[0].children for r in rows.children] == ["1", "2"]


def test_big_books_read_in_billions_everywhere():
    from core.analytics.positioning import money_scale

    assert money_scale([2.5e9]) == (1e9, "B")
    assert format_value(2.5e9, "money") == "$2.5B"
