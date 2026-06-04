"""Specialized analyst sub-agents for the multi-agent analyst subgraph.

Each module is one role the old monolithic ReAct loop used to play in a single
context:

  - ``schema_identifier``  resolve the minimal grounded schema slice once.
  - ``peer_solver``        peer-comparison specialist (bounded ReAct, peer tools).
  - ``generic_solver``     per-lens evidence gatherer (bounded ReAct).
  - ``insight_writer``     single-shot synthesis into the output contract.

Shared building blocks (read-only tools, SQL auto-repair, the bounded solver
runner, domain-rule loading) live in ``common``.
"""
