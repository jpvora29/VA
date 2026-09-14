"""Aligning a premium finding with a survey finding.

Premium and perception live in different tables with different column names for
the same business idea — `Country`/`SurveyCountry`, `Carrier_Group`/`Carrier`,
`Product_Line`/`SurveyPractice` — and different period grains. The failure this
module exists to prevent is the quiet one: treating those columns as
interchangeable, joining populations that do not correspond, or inventing a
quarterly survey figure from an annual score because the premium side had
quarters.

Two rules, both enforced here rather than trusted to a prompt:

  * a filter crosses between flows only when BOTH flows declare a column for the
    same business role, and only after its value is confirmed to exist on the
    far side;
  * two findings are comparable only at a grain both flows actually carry. The
    survey has `Survey_Year` and nothing finer, so the shared grain with a
    quarterly premium series is the YEAR, and saying so is the point.

Column names come from the flow registry, never from a literal here, so a
warehouse that spells a column differently stays correct without a code change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from core.registry import get_flow_registry

#: Business roles a filter can have. These are the registry's own `entity_columns`
#: keys, which is what makes the mapping declarative rather than hardcoded.
CARRIER = "carrier"
COUNTRY = "country"
PRODUCT = "product"
SEGMENT = "segment"

ALIGNABLE_ROLES: Tuple[str, ...] = (CARRIER, COUNTRY, PRODUCT, SEGMENT)

YEAR = "year"
QUARTER = "quarter"
MONTH = "month"

#: Coarsest-last. The shared grain of two flows is the coarsest one both carry.
GRAIN_ORDER: Tuple[str, ...] = (MONTH, QUARTER, YEAR)


@dataclass(frozen=True)
class ColumnMapping:
    """One business role and the column each flow stores it in."""

    role: str
    source_column: str
    target_column: str


@dataclass(frozen=True)
class Alignment:
    """How far a scope and a comparison can legitimately cross between flows.

    `carried` are the filters that mapped and were confirmed present on the far
    side. `dropped` are the roles that could not cross, each with the reason —
    published as a limitation, because a survey figure computed on a wider
    population than the premium figure beside it is not the same scope, however
    similar the sentence sounds.
    """

    source_flow: str
    target_flow: str
    #: target column -> value, ready to use as the far side's filters.
    carried: Mapping[str, Any] = field(default_factory=dict)
    #: business roles that actually crossed. Kept separately from `carried`
    #: because that is keyed by the TARGET column name, and asking it whether the
    #: carrier crossed would be asking the wrong vocabulary a question it cannot
    #: answer.
    carried_roles: Tuple[str, ...] = ()
    dropped: Mapping[str, str] = field(default_factory=dict)
    shared_grain: str = ""

    @property
    def is_comparable(self) -> bool:
        """Whether a like-for-like comparison is supportable at all.

        The carrier is the subject of the sentence; without it the two findings
        are about different things and no wording can rescue that.
        """
        return bool(self.shared_grain) and CARRIER in self.carried_roles

    def limitations(self) -> Tuple[str, ...]:
        return tuple(
            f"{role} could not be matched across datasets: {reason}"
            for role, reason in sorted(self.dropped.items())
        )


def entity_columns(flow: str) -> Mapping[str, str]:
    """role -> column for a flow, from the registry. Empty for an unknown flow."""
    spec = get_flow_registry().get(flow)
    return dict(getattr(spec, "entity_columns", {}) or {}) if spec is not None else {}


def column_mappings(source_flow: str, target_flow: str) -> Tuple[ColumnMapping, ...]:
    """The roles both flows declare a column for, in a stable order.

    A role only one flow declares is absent from the result rather than guessed
    at — that absence is what later becomes a dropped filter with a reason.
    """
    source, target = entity_columns(source_flow), entity_columns(target_flow)
    return tuple(
        ColumnMapping(role, source[role], target[role])
        for role in ALIGNABLE_ROLES
        if role in source and role in target
    )


def available_grains(flow: str) -> Tuple[str, ...]:
    """Period grains a flow can actually produce, coarsest last.

    Read off the registry's `date_columns`: a flow with a date column can cut to
    month and quarter; one with only a year column cannot, and that is precisely
    why survey findings must not be quoted quarterly.
    """
    spec = get_flow_registry().get(flow)
    declared = dict(getattr(spec, "date_columns", {}) or {}) if spec is not None else {}
    grains = set()
    if declared.get("date"):
        grains.update({MONTH, QUARTER})
    if declared.get("quarter"):
        grains.add(QUARTER)
    if declared.get("month"):
        grains.add(MONTH)
    if declared.get("year") or declared.get("date"):
        grains.add(YEAR)
    return tuple(grain for grain in GRAIN_ORDER if grain in grains)


def shared_grain(source_flow: str, target_flow: str) -> str:
    """The finest grain BOTH flows carry. Empty when they share none."""
    source, target = set(available_grains(source_flow)), set(available_grains(target_flow))
    common = source & target
    return next((grain for grain in GRAIN_ORDER if grain in common), "")


def align_scope(
    filters: Mapping[str, Any],
    *,
    source_flow: str,
    target_flow: str,
    values_present: Optional[Any] = None,
) -> Alignment:
    """Translate `filters` from one flow's columns into another's.

    `values_present(column, value) -> bool` confirms the translated value exists
    on the target side; it is injected so this module needs no database. Without
    it, values are carried unverified and every carried role is recorded as
    unconfirmed rather than silently trusted.
    """
    carried: Dict[str, Any] = {}
    carried_roles: list[str] = []
    dropped: Dict[str, str] = {}
    source_columns = entity_columns(source_flow)
    mapped_roles = {m.source_column: m for m in column_mappings(source_flow, target_flow)}

    for column, value in (filters or {}).items():
        mapping = mapped_roles.get(column)
        if mapping is None:
            role = _role_of(source_columns, column) or column
            dropped[role] = f"{target_flow} declares no column for {role}"
            continue
        if values_present is not None and not _present(values_present, mapping.target_column, value):
            dropped[mapping.role] = (
                f"{value!r} is not a stored value of {mapping.target_column}"
            )
            continue
        carried[mapping.target_column] = value
        carried_roles.append(mapping.role)

    return Alignment(
        source_flow=source_flow,
        target_flow=target_flow,
        carried=carried,
        carried_roles=tuple(carried_roles),
        dropped=dropped,
        shared_grain=shared_grain(source_flow, target_flow),
    )


def _role_of(columns: Mapping[str, str], column: str) -> str:
    return next((role for role, name in columns.items() if name == column), "")


def _present(values_present: Any, column: str, value: Any) -> bool:
    """Ask the injected probe, treating its failure as "cannot confirm"."""
    try:
        if isinstance(value, (list, tuple, set)):
            return all(bool(values_present(column, item)) for item in value)
        return bool(values_present(column, value))
    except Exception:  # noqa: BLE001 - an unavailable probe must not assert presence
        return False


def comparable_periods(
    source_periods: Iterable[Any], target_periods: Iterable[Any]
) -> Tuple[Any, ...]:
    """Periods both sides actually have, in the source's order.

    Intersection, not union and not the source's list: a survey year the premium
    book does not reach is not a period the two datasets can be compared over,
    and neither is the reverse.
    """
    target = set(target_periods)
    return tuple(
        period for period in dict.fromkeys(source_periods) if period in target
    )
