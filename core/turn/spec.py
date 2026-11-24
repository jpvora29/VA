"""The turn's single interpretation, as a frozen data contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Scope as ordered (column, values) pairs, so the spec stays hashable.
Scope = tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class TurnSpec:
    """Every decision about what the question asks, in one place.

    Each field names the component that decided it today, so a disagreement
    can be traced to its source:

    - `family`, `scope`, `inherited`, `unresolved` — context filler
    - `depth` — intent classifier (rule floor, then fast model)
    - `shape`, `presentation` — output directives (regex overlay)
    - `operation`, `sources`, `requirements` — operation detector + requirement library
    """

    question: str
    family: str
    depth: str
    operation: str
    shape: str
    presentation: str
    sources: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    deferred: tuple[str, ...] = ()
    scope: Scope = ()
    inherited: tuple[tuple[str, str], ...] = ()
    unresolved: tuple[str, ...] = ()
    period_named: bool = False
    disagreements: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def scope_dict(self) -> dict[str, tuple[str, ...]]:
        return dict(self.scope)

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON-safe form, for state and logs (the checkpoint stores dicts)."""
        data = asdict(self)
        data["scope"] = {column: list(values) for column, values in self.scope}
        data["inherited"] = dict(self.inherited)
        return data
