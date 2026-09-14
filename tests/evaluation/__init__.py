"""Deterministic evaluation harness for chatbot analytical quality.

Runs the real evidence + answer pipeline over a hand-checked fixture warehouse
with no model and no credentials, and scores the result against reference
calculations written independently of the code under test.

See `docs/chatbot-improvements-implementation-plan.md` Phase 0.
"""
