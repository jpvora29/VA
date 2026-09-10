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
        conn.execute(text("INSERT INTO GPR VALUES (:a,:b,:c,:d,:e,:f)"),
                     [dict(zip("abcdef", (*row, f"{row[3]}-06-15"))) for row in ROWS if row[0] != "CHUBB"])
        conn.execute(text("INSERT INTO GPR VALUES ('CHUBB','Canada',:Product_Line,:Year,:Premium,:Billing_Date)"),
                     [dict(row, Billing_Date=f"{row['Year']}-06-15") for row in growth_evidence()[0]["rows"]])
    return engine


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
