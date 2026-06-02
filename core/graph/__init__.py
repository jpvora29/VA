"""LangGraph workflows.

`main.LangGraph` is the chat workflow. `pitch_question_graph.PitchQuestionGraph`
is the pitch-builder analytical workflow. They currently share analytical nodes
but have separate state schemas, graph topology classes, and checkpointers.
"""
