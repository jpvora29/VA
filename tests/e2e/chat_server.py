"""Isolated browser test host. Only routing/model choices are fixtures.

Run with APP_DB_PATH pointing to a disposable database:
    python -m tests.e2e.chat_server
Questions containing 'slow', 'failure', or 'clarify' exercise those paths.
All successful turns execute the real analytics tool against the fixture SQL DB.
"""
import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from tests.test_analytics_tool_path import ROWS, runner_with, state
from tests.test_answer_insights import growth_evidence


def fixture_engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE GPR (Carrier_Group TEXT, Country TEXT, Product_Line TEXT, Year INTEGER, Premium REAL, Billing_Date TEXT)"))
        # The positioning table needs a peer group to rank against.
        conn.execute(text("CREATE TABLE Peers (Carrier_Group TEXT, Overall_Peer_Group TEXT, Country TEXT)"))
        conn.execute(text("INSERT INTO Peers VALUES ('CHUBB','AIG','Canada'),"
                          "('CHUBB','ZURICH GROUP','Canada')"))
        conn.execute(text("INSERT INTO GPR VALUES (:a,:b,:c,:d,:e,:f)"),
                     [dict(zip("abcdef", (*row, f"{row[3]}-06-15"))) for row in ROWS if row[0] != "CHUBB"])
        conn.execute(text("INSERT INTO GPR VALUES ('CHUBB','Canada',:Product_Line,:Year,:Premium,:Billing_Date)"),
                     [dict(row, Billing_Date=f"{row['Year']}-06-15") for row in growth_evidence()[0]["rows"]])
        conn.execute(text("INSERT INTO GPR VALUES (:a,:b,:c,:d,:e,:f)"), asia_rows())
    return engine


ASIA_MARKETS = ("Singapore", "Hong Kong", "China")


def asia_rows():
    """Three carriers, three markets, four lines, two years, four quarters.

    Deterministic arithmetic rather than random numbers, so the rendered page
    is the same on every run. GENERALI grows in Singapore, shrinks in Hong Kong
    and is mixed in China — so the per-market tables disagree, which is the
    point of showing them separately.
    """
    base = {"Property": 4.0e6, "Casualty": 2.6e6, "Marine": 1.4e6, "Cyber": 0.9e6}
    carrier_weight = {"GENERALI": 1.0, "AIG": 1.3, "AXA": 0.8}
    market_weight = {"Singapore": 1.0, "Hong Kong": 0.7, "China": 1.6}
    growth = {("GENERALI", "Singapore"): 1.18, ("GENERALI", "Hong Kong"): 0.86,
              ("GENERALI", "China"): 1.04}
    rows = []
    for carrier, cw in carrier_weight.items():
        for market, mw in market_weight.items():
            for product_index, (product, value) in enumerate(base.items()):
                for year in (2024, 2025):
                    lift = growth.get((carrier, market), 1.07) if year == 2025 else 1.0
                    tilt = 1.0 + 0.12 * ((product_index + len(market)) % 3 - 1)
                    annual = value * cw * mw * lift * (tilt if carrier == "GENERALI" else 1.0)
                    for quarter, month in enumerate(("02", "05", "08", "11"), start=1):
                        share = (0.22, 0.24, 0.26, 0.28)[quarter - 1]
                        rows.append(dict(zip("abcdef", (carrier, market, product, year,
                                                        round(annual * share, 2),
                                                        f"{year}-{month}-15"))))
    return rows


class OfflineSelection:
    def bind_tools(self, *args, **kwargs):
        raise RuntimeError("Use deterministic claim order in browser fixtures")


def fixture_turn(query):
    turn = state(query)
    primitive, measure = "compute_breakdown", "Premium"
    if "chubb" in query.lower():
        turn["routing_context"] = {"resolved_filters": {"Carrier_Group": ["CHUBB"], "Country": ["Canada"], "Year": [2024, 2025]}}
        turn["gpr_reasoning"] = json.dumps({"metric": "premium", "filters": {}, "timeframe": "2024-2025"})
        primitive, measure = "compute_yoy_to_date", "YoY_%_through_Q2"
    return turn, primitive, measure


def split_tool_evidence(engine):
    """Same comparison returned by two real SQL-backed tool calls."""
    from core.analytics.library import compute_breakdown
    from core.analytics.tools.rows import facts_digest, facts_to_rows
    from core.analytics.types import PrimitiveArgs
    evidence = []
    for year in (2024, 2025):
        scope = {"Carrier_Group": "CHUBB", "Country": "Canada", "Year": year}
        args = PrimitiveArgs("gpr", "premium", ("Product_Line",), scope)
        facts = compute_breakdown(args, engine=engine)
        evidence.append({"flow": "gpr", "lens": "growth", "scope": scope,
                         "sql": f"-- compute_breakdown premium for {year}",
                         "rows": facts_to_rows(facts), "facts": facts_digest(facts)})
    return evidence


def positioning_turn(engine, query):
    """A turn that runs the REAL positioning path against the fixture warehouse.

    Everything below the model is production code: the dimension ladder, the
    positioning pack, the chart plan and the claim compiler. Only the model
    calls — planning, solving, narration — are absent, which is what makes this
    runnable without credentials. It exists so the rendered page can be checked
    against the code that actually builds it, rather than against a hand-written
    fixture that would pass whatever the page happened to do.
    """
    from core.analysis.operation import detect_operation
    from core.analytics.dimensions import choose_dimension
    from core.analytics.positioning import build_positioning_comparison
    from core.answers.chart_plan import build_chart_plan, quarterly_rows_from
    from core.answers.grounded import AnswerRequest, compose_answer
    from core.answers.movement_bridge import aligned_rows   # see below
    from core.graph.analyst_subgraph import _positioning_view

    scope = {"Carrier_Group": "CHUBB", "Country": "Canada", "Year": 2025}
    dimension = choose_dimension(scope, flow="gpr", engine=engine)
    pack = build_positioning_comparison(
        dimension=dimension, filters=scope, subject=scope["Carrier_Group"], engine=engine
    )
    # Same order production uses: the figures first, then the charts — and the
    # same chart ORDER, which production reads off the question's operation.
    views = [_positioning_view(pack, scope), *(
        s.as_view() for s in build_chart_plan(
            pack, quarterly_rows=aligned_rows(scope, engine), scope=scope,
            operation=detect_operation(query))
    )]

    answer = compose_answer(AnswerRequest(
        query, tuple({"flow": "gpr", "lens": "positioning", "sql": "-- positioning",
                      "rows": pack.numeric_rows()} for _ in (1,)),
    ))
    return {
        "current_route": "premium",
        "gpr_response": answer.text,
        "gpr_response_record": answer.as_dict(),
        "gpr_query_result": pack.rows(),
        "analyst_charts": views,
        "analyst_evidence": [],
    }


def markets_turn(engine, query):
    """A multi-market performance turn through the REAL per-market path.

    The same `build_market_positions` and `chart_views_for` the analyst graph
    calls — one position table per market, market-aware charts — against the
    fixture warehouse. Only the model calls are absent.
    """
    from core.analytics.markets import build_market_positions
    from core.answers.grounded import AnswerRequest, compose_answer
    from core.graph.analyst_subgraph import _with_market, chart_views_for

    from core.analytics.markets import build_geography_views

    named = [m for m in ASIA_MARKETS if m.lower() in query.lower()]
    scope = {"Carrier_Group": "GENERALI", "Year": 2025}
    if named:
        scope["Country"] = named if len(named) > 1 else named[0]
    packs = build_market_positions(scope, dimension="Product_Line", subject="GENERALI",
                                   engine=engine)
    by_country, by_region = (build_geography_views(scope, subject="GENERALI", engine=engine)
                             if len(packs) == 1 else (None, None))
    views = chart_views_for(packs, scope, question=query, engine=engine,
                            by_country=by_country, by_region=by_region)
    evidence = tuple(
        {"flow": "gpr", "lens": "positioning", "sql": "-- positioning", "scope": market_scope,
         "rows": _with_market(pack.numeric_rows(), market)}
        for market, pack, market_scope in packs
    ) + tuple(
        {"flow": "gpr", "lens": "positioning", "sql": "-- positioning", "scope": scope,
         "rows": geography.numeric_rows()}
        for geography in (by_country, by_region) if geography is not None
    )
    answer = compose_answer(AnswerRequest(query, evidence))
    return {
        "current_route": "premium",
        "gpr_response": answer.text,
        "gpr_response_record": answer.as_dict(),
        "gpr_query_result": packs[0][1].rows() if packs else [],
        "analyst_charts": views,
        "analyst_evidence": [],
    }


#: An answer written the way the live writer is contracted to write one
#: (core/agents/common/answer_shape.py): executive insight, finding-headed ###
#: groups led by their takeaway, a per-line "By product" list, what it means and
#: watch-outs. Lets the card be checked against a real answer's SHAPE without a
#: model. Figures are illustrative; the evidence beside it is the real path's.
CONTRACT_ANSWER = """GENERALI's Singapore premium grew **18.0%** to **$11.8M**, and the growth is concentrated in Property.

### Property is the growth engine
- **Property** — $5.2M ▲ 18.0%, adding $0.8M of the $1.8M increase, so one line now carries 44% of the book.
- Casualty added $0.5M (▲ 18.0%), the second engine, growing in step with Property.
- Cyber is small at $1.2M but grew at the same rate, so the mix is not shifting toward it.

### The book is more concentrated
- Property and Casualty now make up 72.6% of premium, up from 70.1%, so the carrier's result follows two lines.
- Marine is 13.6% of the book and Cyber 10.2%.

### By product
- **Property** — $5.2M ▲ 18.0% · rank #1 of 3 · 44.1% of the book · 38.5% share of wallet
- **Casualty** — $3.4M ▲ 18.0% · rank #2 of 3 · 28.8% of the book · 33.2% share of wallet
- **Marine** — $1.6M ▲ 18.0% · rank #2 of 3 · 13.6% of the book · 30.1% share of wallet
- **Cyber** — $1.2M ▲ 18.0% · rank #2 of 3 · 10.2% of the book · 31.0% share of wallet

### Share of wallet is held, not gained
- Share of wallet is 34.6%, ▼ 0.4pp on the year: the Marsh book grew slightly faster than GENERALI.
- GENERALI ranks #1 in Property and #2 elsewhere among 3 carriers.

### What it means
- **Defend** Property: it carries the growth and the #1 rank, so renewal terms there matter most.
- **Investigate** why share of wallet slipped while premium grew 18.0%.

### Watch-outs
- 2025 is compared with 2024 on the same quarters; a late-year renewal could still move the totals.
"""


#: The fixture's stand-in for the shared head of a real solver prompt: the
#: real head needs the warehouse schema, which this offline host does not have.
_FIXTURE_HEAD = """You are one evidence-gathering step of a multi-step analysis.

[PRIMARY FLOW] gpr  (route="premium"). Query this flow.

[SCHEMA for flow="gpr" — columns available beyond the grounded slice]
{"GPR": ["Carrier_Group", "Country", "Product_Line", "Year", "Premium", "Billing_Date"],
 "Peers": ["Carrier_Group", "Overall_Peer_Group", "Country"]}
"""


def metered_model_calls(callbacks, query):
    """Feed the turn's usage meter the model calls a live analyst turn makes.

    No model runs here, so the calls are fixtures — but their PROMPTS are the
    real ones: the real solver tail (rules, lens, sub-question) and the real
    tool schemas, so the context chip shows a true split. Usage is reported as
    four characters per token, the way a provider would report it.
    """
    from uuid import uuid4

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, LLMResult
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from core.agents.analyst.common import build_tools, solver_prompt_tail
    from core.agents.analyst.generic_solver import _ROLE

    tools = [convert_to_openai_tool(t) for t in build_tools([], query, "temporal_trend", flow="gpr")]
    system = _FIXTURE_HEAD + "\n" + solver_prompt_tail(
        role=_ROLE, question=query, sub_question=query, lens="temporal_trend",
        flow="gpr", route="premium", prior_digest="")
    call = AIMessage(content="", tool_calls=[{"id": "c1", "name": "compute_metric",
                     "args": {"flow": "gpr", "name": "compute_yoy_to_date"}}])
    rows = ToolMessage(content=json.dumps([{"Product_Line": p, "YoY_%": 4.2} for p in
                                           ("Property", "Casualty", "Marine", "Cyber")] * 6),
                       tool_call_id="c1")
    prompts = [
        ("context_filler", [SystemMessage(content="Decide the route and inherited filters."),
                            HumanMessage(content=f"[CURRENT_USER_QUERY]\n{query}\n\n"
                                         "[CONVERSATION_HISTORY]\n[]")], None),
        ("model", [SystemMessage(content=system), HumanMessage(content=query)], tools),
        ("model", [SystemMessage(content=system), HumanMessage(content=query), call, rows], tools),
    ]
    meters = [cb for cb in callbacks or [] if hasattr(cb, "on_chat_model_start")]
    for node, messages, tool_defs in prompts:
        chars = sum(len(str(m.content)) for m in messages) + len(json.dumps(tool_defs or []))
        usage = {"input_tokens": chars // 4, "output_tokens": 60,
                 "total_tokens": chars // 4 + 60}
        for meter in meters:
            run_id = uuid4()
            meter.on_chat_model_start({"kwargs": {"deployment_name": "gpt-4.1-mini"}}, [messages],
                                      run_id=run_id, metadata={"langgraph_node": node},
                                      invocation_params={"tools": tool_defs} if tool_defs else {})
            message = AIMessage(content="", usage_metadata=usage)
            meter.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]),
                             run_id=run_id)


class FixtureWorkflow:
    def __init__(self):
        self.engine = fixture_engine()
        self.states = {}

    def stream_workflow(self, input_obj, *, thread_id, cancel, callbacks):
        from core.agents.common.analytics_tools import run_analytics_tools
        from core.answers.response_pipeline import write_response
        query = input_obj["messages"][-1].content if isinstance(input_obj, dict) else "resumed"
        yield {"node": "context_filler_node"}
        if "failure" in query.lower():
            raise RuntimeError("Intentional fixture failure")
        if "clarify" in query.lower():
            yield {"interrupt": {"id": "period", "question": "Which period should I use?",
                "options": [{"label": "2024"}, {"label": "2023"}]}}
            return
        if "slow" in query.lower():
            cancel.wait(8)
        if cancel.is_set():
            return
        metered_model_calls(callbacks, query)
        if "review" in query.lower():
            # The live writer's shape over the real evidence path.
            state = markets_turn(self.engine, "generali in singapore")
            state["gpr_response"] = CONTRACT_ANSWER
            state.pop("gpr_response_record", None)
            self.states[thread_id] = state
            yield {"node": "gpr_insight"}
            yield from self._tail(query, thread_id, cancel)
            return
        if "generali" in query.lower():
            self.states[thread_id] = markets_turn(self.engine, query)
            yield {"node": "gpr_insight"}
            yield from self._tail(query, thread_id, cancel)
            return
        if "position" in query.lower() or "performance" in query.lower():
            self.states[thread_id] = positioning_turn(self.engine, query)
            yield {"node": "gpr_insight"}
            yield from self._tail(query, thread_id, cancel)
            return
        turn, primitive, measure = fixture_turn(query)
        turn.update(run_analytics_tools(turn, flow="gpr", engine=self.engine,
            runner=runner_with([{"name": primitive, "args": {"group_by": ["Product_Line"]}}])))
        if "split" in query.lower() and "chubb" in query.lower():
            turn["analyst_evidence"] = split_tool_evidence(self.engine)
        turn["current_route"] = "premium"
        yield {"node": "gpr_analytics_tools"}
        turn.update(write_response(turn, "gpr_response", ("gpr",), client=OfflineSelection()))
        turn["gpr_chart"] = {"chart_type": "bar", "x": "Product_Line", "y": [measure],
                             "title": "Chubb premium growth by product" if "chubb" in query.lower() else "Marsh-placed premium by product",
                             "y_agg": "none"}
        self.states[thread_id] = turn
        yield {"node": "gpr_insight"}
        yield from self._tail(query, thread_id, cancel)

    def _tail(self, query, thread_id, cancel):
        """The production tail: follow-ups are written AFTER the answer.

        'tail' in a question makes the follow-up step take a few seconds, so the
        early publish (the answer shown before the tail finishes) is visible.
        """
        yield {"node": "followup_node"}
        if "tail" in query.lower():
            cancel.wait(3)
        state = self.states.get(thread_id) or {}
        state["followup_questions"] = [
            "What drove the change in Property?",
            "How does this compare with the peer average?",
        ]

    def get_state_values(self, thread_id):
        return self.states.get(thread_id, {})


def main():
    if not os.environ.get("APP_DB_PATH"):
        raise RuntimeError("Set APP_DB_PATH to a disposable test database")
    from app import app
    from ui import callbacks
    callbacks.langgraph = FixtureWorkflow()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8093")), debug=False, threaded=True)


if __name__ == "__main__":
    main()
