"""Fresh per-turn outputs, shared by the UI and the golden workflow harness."""
from langgraph.types import Overwrite


def fresh_turn_outputs() -> dict:
    """Clear previous outputs while preserving conversation context and messages.

    Retry counters and the SQL error log have additive reducers. Writing zero or
    an empty list would preserve their previous values; Overwrite resets them.
    Never apply this when resuming an interrupted turn.
    """
    outputs = {
        "analyst_charts": [], "analyst_evidence": [], "boardroom": {},
        "followup_questions": [], "combined_result": [],
        "combined_chart": {}, "combined_response": "", "combined_response_record": {},
        "combined_sql_query": "", "out_of_scope_answer": "",
        "sql_error_log": Overwrite([]), "clarify_questions": [], "clarification": "",
    }
    for flow in ("gpr", "survey", "gimmi"):
        outputs.update({
            f"{flow}_query_result": [], f"{flow}_response": "",
            f"{flow}_response_record": {}, f"{flow}_sql_query": "",
            f"{flow}_sql_error": False, f"{flow}_attempts": Overwrite(0),
        })
    for flow in ("gpr", "survey"):
        outputs.update({
            f"{flow}_chart": {}, f"{flow}_analytics": None,
            f"{flow}_reasoning": "", f"{flow}_overflow": False,
            f"{flow}_data_overflow_msg": "", f"{flow}_cols": [],
        })
    return outputs
