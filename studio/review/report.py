"""Assemble the Review report, one section at a time.

The builder is the specification: reading :func:`build_review_report` tells you what a
Review contains without opening a single step. Each ``add_*`` owns the whole answer for
its section, including "there is nothing to say here" — so the caller never checks.

Pure throughout. The report is computed from the document already on screen, so it costs
one pass over the manifest and can never disagree with the deck it describes.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Mapping, Optional, Tuple

from studio.review.assembled import assembled_commentary, diagnose_assembled, is_assembled
from studio.review.capability import probe, reporting_year
from studio.review.causes import cause as cause_of
from studio.review.commentary import diagnose_commentary
from studio.review.model import (
    ASSEMBLED,
    TEMPLATE,
    Capability,
    CauseGroup,
    ReviewReport,
    SlotFinding,
)
from studio.review.slots import diagnose_slots
from studio.template_fill.model import materialize_fields

#: Cause order on the page: what the author must fix, then what the data cannot give,
#: then what the template never said. A cause not named here sorts after these, by size.
_CAUSE_ORDER: Tuple[str, ...] = (
    "stale", "blanked", "commentary_empty",
    "no_reporting_year", "no_prior_year", "no_peer_benchmark", "no_market_rank",
    "no_share_of_wallet", "no_survey_book", "no_spotlight", "no_country_breakdown",
    "no_chart_series", "no_data",
    "unmapped_figure", "unmapped_text", "unmapped_chart",
)


class ReviewReportBuilder:
    """Builds a :class:`ReviewReport` for one filled TemplateDoc."""

    def __init__(self, doc: Mapping[str, Any]) -> None:
        self._doc: Dict[str, Any] = dict(doc or {})
        # The merged deliverable is already written, so there is nothing to materialize:
        # its manifest IS the list of placeholders that survived the fill.
        self._assembled = is_assembled(self._doc)
        self._fields = {} if self._assembled else materialize_fields(self._doc)
        self._values: Mapping[str, Any] = self._doc.get("values") or {}
        self._capabilities: Tuple[Capability, ...] = ()
        self._findings: List[SlotFinding] = []
        self._commentary: Tuple[Any, ...] = ()

    def add_capabilities(self) -> "ReviewReportBuilder":
        """What the data behind this deck can and cannot support."""
        self._capabilities = probe(self._values)
        return self

    def add_slot_findings(self) -> "ReviewReportBuilder":
        """Every slot that will not carry this deck's data, and why.

        Runs after :meth:`add_capabilities` because the "why" IS the capabilities — a
        blank year-on-year box is only explained by there being no prior year in scope.
        """
        self._findings = (
            diagnose_assembled(self._doc, self._capabilities) if self._assembled
            else diagnose_slots(self._fields, self._doc, self._capabilities)
        )
        return self

    def add_commentary(self) -> "ReviewReportBuilder":
        """Every prose box, and whether the writer filled it."""
        self._commentary = tuple(
            assembled_commentary(self._doc) if self._assembled
            else diagnose_commentary(self._fields, self._doc)
        )
        return self

    def build(self) -> ReviewReport:
        return ReviewReport(
            source=ASSEMBLED if self._assembled else TEMPLATE,
            subject=str(self._values.get("subject_name") or ""),
            period_year=reporting_year(self._values),
            slides_total=int(self._doc.get("n_slides") or 0),
            slides_hidden=len(self._doc.get("hidden") or []),
            slots_total=self._countable(),
            slots_filled=self._filled(),
            capabilities=self._capabilities,
            groups=_group(self._findings + list(self._empty_commentary())),
            commentary=self._commentary,
        )

    # ── the two figures the header reports ───────────────────────────────────

    def _countable(self) -> int:
        """Slots on pages the deck actually ships — a hidden page cannot be coverage.

        Zero for the assembled deck: what filled there is a number in a file now, not a
        slot, so there is no denominator to be a fraction of and the report says how many
        placeholders remain instead (see :data:`studio.review.model.ASSEMBLED`).
        """
        hidden = {int(i) for i in (self._doc.get("hidden") or [])}
        return sum(1 for f in self._fields.values() if int(f.get("slide_idx", 0)) not in hidden)

    def _filled(self) -> int:
        hidden = {int(i) for i in (self._doc.get("hidden") or [])}
        return sum(1 for f in self._fields.values()
                   if f.get("filled") and int(f.get("slide_idx", 0)) not in hidden)

    def _empty_commentary(self) -> List[SlotFinding]:
        """Unwritten prose boxes, as slot findings so they group with everything else.

        A box that kept the template's example commentary is the most dangerous thing on
        the page — it reads as finished work about the wrong carrier — so it belongs in
        the same list the author works down, not in a footnote of its own.
        """
        return [
            SlotFinding(slot_key=c.slot_key, slide_no=c.slide_no, role=None,
                        token="", context="", value_kind="text", cause_id=c.cause_id)
            for c in self._commentary if c.cause_id
        ]


def build_review_report(doc: Optional[Mapping[str, Any]]) -> ReviewReport:
    """The Review for ``doc`` — an empty report when there is no document yet."""
    if not doc:
        return ReviewReport()
    return (
        ReviewReportBuilder(doc)
        .add_capabilities()
        .add_slot_findings()
        .add_commentary()
        .build()
    )


def _group(findings: List[SlotFinding]) -> Tuple[CauseGroup, ...]:
    """Findings folded into one group per cause, in the order the page shows them."""
    by_cause: "OrderedDict[str, List[SlotFinding]]" = OrderedDict()
    for finding in findings:
        by_cause.setdefault(finding.cause_id, []).append(finding)
    groups = [
        CauseGroup(cause=cause_of(cause_id),
                   findings=tuple(sorted(items, key=lambda f: (f.slide_no, f.slot_key))))
        for cause_id, items in by_cause.items()
    ]
    return tuple(sorted(groups, key=_rank))


def _rank(group: CauseGroup) -> Tuple[int, int]:
    """Declared order first; anything unrecognised falls to the end, biggest first."""
    try:
        return (_CAUSE_ORDER.index(group.cause.id), 0)
    except ValueError:
        return (len(_CAUSE_ORDER), -group.count)


__all__ = ["ReviewReportBuilder", "build_review_report"]
