"""Per-session fact store — the v1 stand-in for the deferred knowledge graph.

Every cut emits ``AnalyticsFact``s (value + provenance). They land here, indexed
so the renderers, the SWOT/cross-ref rules, and the faithfulness verifier can look
facts up cheaply by metric name, by cut, and by dimension slice — without a graph
DB. See ``studio/DESIGN.md`` §2 (KG deferred to v2; this store covers v1
cross-references).

The store is deliberately tiny and pure (no DB, no LLM): facts are immutable
frozen dataclasses, so this is just typed indexing over a list.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from core.analytics.types import AnalyticsFact


@dataclass
class FactStore:
    """Holds a turn's facts and the indexes needed for fast lookup.

    Indexes are maintained on insert:
      - ``_by_name``   : fact.name        -> facts   (e.g. all "whitespace" facts)
      - ``_by_cut``    : originating cut  -> facts   (e.g. all "industry_top5")
      - ``_by_dims``   : dims_key         -> facts   (align facts about one slice)
    """

    facts: List[AnalyticsFact] = field(default_factory=list)
    _by_name: Dict[str, List[AnalyticsFact]] = field(default_factory=lambda: defaultdict(list))
    _by_cut: Dict[str, List[AnalyticsFact]] = field(default_factory=lambda: defaultdict(list))
    _by_dims: Dict[Tuple[Tuple[str, str], ...], List[AnalyticsFact]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def add(self, fact: AnalyticsFact, *, cut: Optional[str] = None) -> None:
        self.facts.append(fact)
        self._by_name[fact.name].append(fact)
        if cut:
            self._by_cut[cut].append(fact)
        self._by_dims[fact.dims_key].append(fact)

    def extend(self, facts: Iterable[AnalyticsFact], *, cut: Optional[str] = None) -> None:
        for fact in facts:
            self.add(fact, cut=cut)

    def ingest(self, by_cut: Mapping[str, Iterable[AnalyticsFact]]) -> None:
        """Load a ``{cut_name: facts}`` map (the shape ``ScopedRegistry.run_all`` returns)."""
        for cut_name, facts in by_cut.items():
            self.extend(facts, cut=cut_name)

    # ── lookups ─────────────────────────────────────────────────────────────

    def by_name(self, name: str) -> List[AnalyticsFact]:
        return list(self._by_name.get(name, ()))

    def by_cut(self, cut: str) -> List[AnalyticsFact]:
        return list(self._by_cut.get(cut, ()))

    def for_slice(self, dims: Mapping[str, Any]) -> List[AnalyticsFact]:
        """Every fact whose cut exactly matches ``dims`` — used to align Premium and
        Survey facts about the same (carrier, country, period) for cross-refs."""
        key = tuple(sorted((str(k), str(v)) for k, v in dims.items()))
        return list(self._by_dims.get(key, ()))

    def values(self) -> List[Any]:
        """Flat list of computed values — handy for the faithfulness verifier."""
        return [fact.value for fact in self.facts]

    def __len__(self) -> int:
        return len(self.facts)
