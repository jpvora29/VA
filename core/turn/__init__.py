"""One interpretation of the turn's question, built once (Phase 2, step 1).

Today the question is read separately by the context filler (family, filters),
the intent classifier (depth), a regex (answer shape), the operation detector
and the requirement library — and nothing checks that they agree. `TurnSpec`
gathers those decisions into one frozen record and names every place they
contradict each other.

It runs in SHADOW: built and logged on every turn, read by nothing yet. The
log of disagreements is the evidence for which decisions to unify first.

Step 2 adds the story shadow (`core.analysis.story`, `story_shadow`): which
sections of the answer's shape the turn's evidence can and cannot fill.
"""

from core.turn.build import build_turn_spec
from core.turn.disagreements import Disagreement, find_disagreements
from core.turn.spec import TurnSpec

__all__ = ["TurnSpec", "build_turn_spec", "Disagreement", "find_disagreements"]
