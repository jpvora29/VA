"""How many commentary fields a template asks a model to write.

A build's runtime is set by the number of model calls it makes, and that number is decided
long before Generate is pressed — by which sub-decks the scope assembles and how many prose
columns each of their templates carries. Counting them is therefore something Setup can
show the author *before* they wait, and something a benchmark can assert against.

Counted the way the providers actually WRITE, which is not the same as the number of boxes
on the slides:

* :func:`studio.template_fill.commentary.values` answers one QUESTION per topic and puts
  that answer in every box asking it, so two Challenges columns on two pages are one call.
* :func:`studio.template_fill.feedback.values` caches on ``(country, kind)``, so a feedback
  table's rows cost one call per kind PER COUNTRY IN SCOPE, and its quadrant panels — which
  belong to the sub-deck rather than to a row — cost one each.

Counting boxes instead reported 24 written fields for a product template that makes three
calls, which is the sort of estimate that is worse than none.

Pure and template-only: a ``Template`` in, an integer out. No result, no data, no model.
The per-entity multiplication (a product block per product, a country block per country)
belongs to the caller, which is the only place that knows the selection.
"""
from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from typing import Mapping, Sequence, Tuple

from studio.template_fill.analyze import Template


def without(template: Template, hidden: Sequence[int] = ()) -> Template:
    """``template`` minus the slides an author unticked in Setup.

    Counting is what tells an author how long a build will take, so it has to be counted
    over the pages the build will actually write — a deck with its SWOT page removed does
    not pay for SWOT commentary.
    """
    if not hidden:
        return template
    drop = {int(i) for i in hidden}
    return replace(template, slides=[s for s in template.slides if s.index not in drop])


def commentary_fields(template: Template) -> int:
    """Prose columns bound by :mod:`studio.template_fill.commentary` (Trading Summary…).

    One per distinct TOPIC — the module's own cache key — because a topic heading a column
    on two pages is the template asking one question twice and is answered once.
    """
    from studio.template_fill import commentary

    return len({t["topic"] for t in commentary.prose_targets(template)})


def feedback_fields(template: Template, *, countries: int = 1) -> int:
    """Feedback cells and quadrant panels a model writes for ``countries`` markets.

    Only kinds with a composer are written — a KPI callout is a formatted number and never
    reaches a model — and ``highlights`` is excluded because
    :func:`studio.template_fill.feedback._polish` leaves it deterministic.
    """
    from studio.template_fill import feedback

    written = set(feedback._COMPOSERS) - {"highlights"}
    targets = [t for t in feedback._targets(template) if t["kind"] in written]
    panels = {t["kind"] for t in targets if t["country_ord"] is None}
    rows = {t["kind"] for t in targets if t["country_ord"] is not None}
    return len(panels) + len(rows) * max(0, int(countries))


def fields(template: Template, *, countries: int = 1) -> int:
    """Every commentary field on one template — the two families above, summed."""
    return commentary_fields(template) + feedback_fields(template, countries=countries)


def fields_for_axis(axis: str, *, countries: int = 1, hidden: Sequence[int] = ()) -> int:
    """The commentary-field count of a registered axis's template, or 0 if unreadable.

    A template that will not parse must not stop Setup from drawing a form, so this
    answers 0 rather than raising — the panel then simply says nothing about that axis.
    """
    return _axis_fields(axis, int(countries), tuple(sorted(int(i) for i in hidden)))


@lru_cache(maxsize=64)
def _axis_fields(axis: str, countries: int, hidden: Tuple[int, ...]) -> int:
    """:func:`fields_for_axis` with hashable arguments, cached.

    Cached because Setup asks it on every repaint of the page list — once per axis, and
    again each time a page is ticked — and answering means parsing a ``.pptx``. The
    templates are a fixed, author-made set that does not change while the app runs, which
    is the same assumption :func:`studio.template_fill.deck_slides.catalog` makes.
    """
    from studio.template_fill.analyze import analyze
    from studio.template_fill.binding_map import template_path

    try:
        return fields(without(analyze(template_path(axis)), hidden), countries=countries)
    except Exception:  # noqa: BLE001 — a count is an aid, never a gate
        return 0


def deck_fields(entities: Mapping[str, int], *, countries: int = 1,
                hidden: Mapping[str, Sequence[int]] = ()) -> int:
    """Total commentary fields for ``{axis: how many blocks of it}``.

    The plan's formula — overall + per-product + per-country — read off the templates
    themselves rather than written down, so re-authoring a template moves the estimate
    with it. ``countries`` is how many markets a single block reports on, which is what
    decides how many rows of a feedback table are filled rather than blanked.
    """
    dropped = dict(hidden or {})
    return sum(fields_for_axis(axis, countries=countries, hidden=dropped.get(axis, ()))
               * int(count)
               for axis, count in entities.items())


def axis_field_counts(axes: Tuple[str, ...],
                      hidden: Mapping[str, Sequence[int]] = ()) -> Tuple[Tuple[str, int], ...]:
    """``(axis, fields)`` for each axis that has any — for the Setup preview panel."""
    dropped = dict(hidden or {})
    counted = ((axis, fields_for_axis(axis, hidden=dropped.get(axis, ()))) for axis in axes)
    return tuple((axis, n) for axis, n in counted if n)
