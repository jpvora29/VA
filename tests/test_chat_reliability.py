"""Turn lifecycle and analytical publication regressions, without model calls."""
from copy import deepcopy
from functools import partial
import json
import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from core.answers.grounded import AnswerRequest, compose_answer, validate_record
from core.answers.response_pipeline import response_evidence, write_response
from core.answers import provenance
from ui.chat_turn import TurnRequest, finalize_turn
from ui.jobs import Job, start_job, get_job, discard_job


def wait_done(job):
    deadline = time.monotonic() + 3
    while not job.done and time.monotonic() < deadline:
        time.sleep(.01)
    assert job.done


@pytest.fixture
def repository(monkeypatch):
    from core.store import conversations as repo
    from core.store.db import metadata
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    metadata.create_all(engine)
    monkeypatch.setattr(repo, "app_engine", engine)
    yield repo
    engine.dispose()


def commit(chat, state):
    chat["messages"].append({"type": "AIMessage", "content": state["answer"]})
    return chat


def request():
    thread = uuid.uuid4().hex
    return TurnRequest(thread, 7, {"thread_id": thread, "messages": [{"type": "HumanMessage", "content": "q"}]}, None)


@pytest.mark.parametrize("outcome", ["success", "cancel", "error", "clarify"])
def test_worker_persists_every_terminal_state_without_browser_polling(repository, outcome):
    req = request()
    def work(job):
        if outcome == "error":
            raise RuntimeError("fixture failure")
        job.cancelled = outcome == "cancel"
        job.partial_text = "An unverified $999bn"
        job.interrupt = {"question": "Which year?"} if outcome == "clarify" else None
        job.state = {"answer": "Verified answer"}
    job = start_job(req.thread_id, work, user_id=req.user_id,
                    finalize=partial(finalize_turn, req, commit=commit, persist=repository.save_conversation))
    wait_done(job)
    saved = repository.load_conversation(7, req.thread_id)
    assert saved == job.transcript
    assert saved["_running"] is False
    assert len(saved["messages"]) == 2
    assert "$999bn" not in json.dumps(saved["messages"])
    assert saved["awaiting_clarification"] == (outcome == "clarify")


def test_duplicate_launch_cannot_replace_a_running_checkpoint_writer():
    entered, release = threading.Event(), threading.Event()
    def work(job):
        entered.set()
        release.wait(2)
    thread = uuid.uuid4().hex
    first = start_job(thread, work)
    assert entered.wait(1)
    second = start_job(thread, lambda job: pytest.fail("overlapping writer"))
    assert first is second
    assert not first.cancel.is_set()
    release.set()
    wait_done(first)


def test_duplicate_launch_does_not_save_another_pending_snapshot():
    prepared, entered, release = [], threading.Event(), threading.Event()
    def prepare(job):
        prepared.append(job.id)
        entered.set()
        release.wait(2)
    thread = uuid.uuid4().hex
    first = start_job(thread, lambda job: None, prepare=prepare)
    assert entered.wait(1)
    second = start_job(thread, lambda job: None, prepare=prepare)
    assert first is second and prepared == [first.id]
    release.set()
    wait_done(first)


def test_deleting_a_running_chat_cannot_resurrect_it(repository):
    req = request()
    release = threading.Event()
    repository.save_conversation(7, req.thread_id, req.transcript)
    job = start_job(req.thread_id, lambda job: release.wait(2),
                    finalize=partial(finalize_turn, req, commit=commit, persist=repository.save_conversation))
    discard_job(req.thread_id, partial(repository.delete_conversation, 7, req.thread_id))
    release.set()
    wait_done(job)
    assert repository.load_conversation(7, req.thread_id) is None


def test_stale_edit_cannot_replace_a_completed_new_turn(repository):
    req = request()
    older = dict(req.transcript, _job_id="old")
    newer = deepcopy(older)
    newer.update(_job_id="new")
    newer["messages"].append({"type": "AIMessage", "content": "new"})
    repository.save_conversation(7, req.thread_id, newer)
    assert repository.save_chat_edit(7, req.thread_id, older) is False
    assert repository.load_conversation(7, req.thread_id) == newer
    repository.delete_conversation(7, req.thread_id)
    assert repository.save_chat_edit(7, req.thread_id, newer) is False


def test_store_cannot_overwrite_another_users_conversation(repository):
    req = request()
    repository.save_conversation(7, req.thread_id, req.transcript)
    assert not repository.save_conversation(8, req.thread_id, {"messages": [{"content": "overwrite"}]})
    assert repository.load_conversation(7, req.thread_id) == req.transcript
    assert repository.load_conversation(8, req.thread_id) is None


def test_verification_rechecks_fact_identity_against_source_rows():
    evidence = ({"flow": "gpr", "lens": "gpr", "scope": {}, "sql": "select", "rows": [{"Carrier": "A", "Premium": 100}]},)
    answer = compose_answer(AnswerRequest("premium", evidence))
    record = json.loads(json.dumps(answer.as_dict()))
    assert validate_record(record, answer.text, evidence)
    wrong_carrier = deepcopy(evidence)
    wrong_carrier[0]["rows"][0]["Carrier"] = "B"
    assert not validate_record(record, answer.text, wrong_carrier)
    assert not validate_record(record, answer.text.replace("$100", "$200"), evidence)


@pytest.mark.parametrize("field,value", [("formula", "100 + 999 = 1099"), ("fact_ids", ["invented"])])
def test_calculation_details_cannot_be_changed_while_keeping_a_verified_badge(field, value):
    evidence = ({"flow": "gpr", "rows": [{"Premium": 100}]},)
    answer = compose_answer(AnswerRequest("premium", evidence))
    record = answer.as_dict()
    record["claims"][0][field] = value
    assert not validate_record(record, answer.text, evidence)


@pytest.mark.parametrize("raises", [False, True])
def test_storage_failure_preserves_answer_with_a_visible_unsaved_notice(raises):
    req = request()
    def persist(*args):
        if raises:
            raise OSError("fixture storage unavailable")
        return False
    def work(job):
        job.state = {"answer": "Completed result"}
    job = start_job(req.thread_id, work,
        finalize=partial(finalize_turn, req, commit=commit, persist=persist))
    wait_done(job)
    assert job.transcript["messages"][1]["content"] == "Completed result"
    assert "could not be saved" in job.transcript["messages"][-1]["content"]
    assert job.transcript["_save_failed"] and job.error


def test_new_turn_clears_stale_outputs_and_resets_additive_retry_channels():
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import StateGraph, START, END
    from core.state.agent_state import AgentState
    from core.state.turn import fresh_turn_outputs
    graph = StateGraph(AgentState)
    graph.add_node("work", lambda state: {"gpr_attempts": 1})
    graph.add_edge(START, "work")
    graph.add_edge("work", END)
    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "reset-test"}}
    app.invoke({"messages": [HumanMessage(content="first")], "gpr_attempts": 2,
                "gimmi_response": "stale", "gpr_response_record": {"stale": True}}, config)
    result = app.invoke(dict(fresh_turn_outputs(), messages=[HumanMessage(content="next")]), config)
    assert result["gpr_attempts"] == 1
    assert result["gimmi_response"] == "" and result["gpr_response_record"] == {}
    assert len(result["messages"]) == 2


@pytest.mark.parametrize("cursor", [{"thread_id": "new", "loading": True},
                                    {"thread_id": "new", "loading": False}])
def test_send_during_conversation_switch_cannot_append_to_the_old_chat(cursor):
    from dash import no_update
    from ui.callbacks import update_chat, ask_suggested_question
    chat = {"thread_id": "old", "messages": []}
    assert update_chat(1, "new question", chat, cursor) == (no_update,) * 4
    assert ask_suggested_question([1], chat, cursor) == (no_update,) * 3
    assert chat["messages"] == []


def test_real_tool_to_answer_to_provenance_to_saved_render(repository):
    from tests.test_analytics_tool_path import engine as engine_fixture, runner_with, state
    from core.agents.common.analytics_tools import run_analytics_tools
    from ui.callbacks import _commit_turn, render_chat
    from types import SimpleNamespace
    eng = engine_fixture.__wrapped__()
    turn = state()
    turn.update(run_analytics_tools(turn, flow="gpr", engine=eng,
        runner=runner_with([{"name": "compute_breakdown", "args": {"group_by": ["Product_Line"]}}])))
    turn["current_route"] = "premium"
    class Offline:
        def bind_tools(self, *args, **kwargs):
            raise RuntimeError("offline")
    turn.update(write_response(turn, "gpr_response", ("gpr",), client=Offline()))
    with eng.connect() as connection:
        expected = connection.execute(text("SELECT SUM(Premium) FROM GPR WHERE Carrier_Group='ZURICH GROUP' AND Country='Canada' AND Year=2024 AND Product_Line='Property'")).scalar_one()
    assert expected == 150
    assert "$150" in turn["gpr_response"] and "$50" in turn["gpr_response"]
    prov = provenance.build(turn, turn["gpr_response"])
    assert prov.state == provenance.VERIFIED
    assert prov.facts and all(f["support"] for f in prov.facts)
    req = request()
    job = Job(req.thread_id, state=turn)
    finalize_turn(req, job, commit=_commit_turn, persist=repository.save_conversation)
    saved = repository.load_conversation(7, req.thread_id)
    assert saved["messages"][1]["provenance"]["state"] == "verified"
    rendered = str(render_chat(saved, False, False, None, {}, {"username": "test"}))
    assert "$150" in rendered and "Verified against the data" in rendered
    assert "not in the data" not in rendered.lower()


def test_quarter_order_uses_year_before_quarter():
    evidence = ({"flow": "gpr", "lens": "trend", "rows": [
        {"Year": 2024, "Quarter": 4, "Premium": 100},
        {"Year": 2025, "Quarter": 1, "Premium": 120}]},)
    answer = compose_answer(AnswerRequest("premium trend", evidence))
    assert "20% increase" in answer.text
    assert validate_record(answer.as_dict(), answer.text, evidence)


def test_chart_only_analyst_result_stays_empty_and_combined_rows_are_not_prose(monkeypatch):
    from types import SimpleNamespace
    from langchain_core.messages import HumanMessage
    from core.agents import analyst_agent
    from core.schemas.routing import RoutingContext, OutputDirectives
    from ui.callbacks import _update_chat_history
    context = RoutingContext(table_family="both", intent_type="new_question",
        output_directives=OutputDirectives(presentation="chart_only"))
    monkeypatch.setattr(analyst_agent, "_subgraph", SimpleNamespace(
        AnalystAgent=SimpleNamespace(invoke=lambda state: {"answer": "", "evidence": []})))
    result = analyst_agent.analyst_agent_node({"current_route": "both",
        "messages": [HumanMessage(content="just a chart")], "routing_context": context})
    assert result["combined_response"] == ""
    result["combined_result"] = [{"Premium": 100}]
    chat = _update_chat_history({"messages": []}, result, "both")
    assert chat["messages"][0]["content"] == ""


def test_peer_gap_is_calculated_once_and_observations_do_not_repeat_it():
    evidence = ({"flow": "survey", "rows": [{"Country": "UK", "Score": 8, "Peer_Avg_Score": 7}]},)
    answer = compose_answer(AnswerRequest("compare score with peers", evidence))
    assert len(answer.claims) == 1
    assert "above the peer average of 7 by 1" in answer.text
    assert validate_record(answer.as_dict(), answer.text, evidence)


def test_lens_dependency_indices_are_remapped_and_invalid_branches_removed():
    from core.analysis.validation import validate_plan
    from core.schemas.analysis import AnalysisPlan, DerivedAnalysis
    plan = AnalysisPlan(derived=[DerivedAnalysis(lens=l, sub_question=q, depends_on=d) for l,q,d in [
        ("bad", "x", []), ("trend", "a", []), ("mix", "b", [1]), ("mix", "c", [0]), ("trend", "a", [])]])
    checked = validate_plan(plan, {"trend", "mix"}, limit=3)
    assert [s.sub_question for s in checked.derived] == ["a", "b"]
    assert checked.derived[1].depends_on == [0]


@pytest.mark.parametrize("aggregation", ["none", "sum"])
def test_chart_cannot_silently_sum_percentage_rows(aggregation):
    import pandas as pd
    from ui.chart_functions import generate_chart
    fig, _ = generate_chart(pd.DataFrame([
        {"Product": "A", "Share_pct": 20}, {"Product": "A", "Share_pct": 30},
        {"Product": "B", "Share_pct": 40}]),
        {"chart_type": "bar", "x": "Product", "y": ["Share_pct"], "y_agg": aggregation})
    assert fig is None
