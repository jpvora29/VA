"""Minutes of Meeting — a QBR meeting note plus its deck become a written DOCX.

The engine is a five-phase pipeline, readable top to bottom in :mod:`mom.pipeline`:

    notes (PDF/DOCX) ─┐
                      ├─► tag against the ICG tag list ─► score priorities
    QBR deck (PPTX) ──┘        ─► verify ─► write the minutes DOCX

Two output shapes exist (:mod:`mom.modes`); everything before the last phase is
identical, which is why the mode is data rather than a second code path.

Nothing here imports Dash. ``ui.mom`` is the workspace that drives it.
"""
