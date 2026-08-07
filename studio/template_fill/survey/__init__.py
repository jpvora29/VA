"""The Carrier Survey page — the per-country slide built from ``survey_template.pptx``.

Split by responsibility so each piece stays testable on its own:

  * :mod:`bands`  — pure: a year-on-year score change → the legend's cell colour;
  * :mod:`ribbon` — pure: a ranking spec → the chart PNG;
  * :mod:`facts`  — the deterministic survey queries behind both;
  * :mod:`page`   — detection, slot binding and the fill payload (the module
    :mod:`studio.template_fill.assemble` actually calls).

Deliberately re-exports nothing: ``page`` imports its siblings from this package, so an
``__init__`` that imported ``page`` would close a cycle. Import the submodule you want.
"""
