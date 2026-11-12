"""The turn's single interpretation, as a frozen data contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple

#: Scope as ordered (column, values) pairs, so the spec stays hashable.
Scope = Tuple[Tuple[str, Tuple[str, ...]], ...]


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
    sources: Tuple[str, ...] = ()
    requirements: Tuple[str, ...] = ()
    deferred: Tuple[str, ...] = ()
    scope: Scope = ()
    inherited: Tuple[Tuple[str, str], ...] = ()
    unresolved: Tuple[str, ...] = ()
    period_named: bool = False
    disagreements: Tuple[Dict[str, str], ...] = field(default_factory=tuple)

    def scope_dict(self) -> Dict[str, Tuple[str, ...]]:
        return dict(self.scope)

    def as_dict(self) -> Dict[str, Any]:
        """Plain JSON-safe form, for state and logs (the checkpoint stores dicts)."""
        data = asdict(self)
        data["scope"] = {column: list(values) for column, values in self.scope}
        data["inherited"] = dict(self.inherited)
        return data
