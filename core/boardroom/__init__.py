"""Deterministic Boardroom rules — everything the model is not allowed to decide.

The language model extracts *facts* (a premium, a movement, the periods being
compared). Completing those facts into the measures they imply
(:mod:`core.boardroom.derive`) and printing them (:mod:`core.boardroom.money`)
happens here, so two widgets built from the same rows can never disagree.
"""
