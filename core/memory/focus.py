"""The user's working set: what they have been looking at, remembered.

An analyst covering Zurich in Singapore asks about Zurich in Singapore most
days. Making them re-establish that every morning is friction the product can
remove — but only from what they actually asked, never from a guess. So the
working set is DERIVED from the episodic log (`core.memory.episodic`): each
answered question is stored with the scope it resolved to, and this module ranks
those scopes by how often and how recently they came up.

Two consumers:

* the welcome screen — "pick up where you left off" and one-click questions
  about the user's usual carriers and markets;
* clarification — when a question names no scope at all, the user's most recent
  scope is offered FIRST among the options (never applied silently).

Pure ranking over plain dicts (`rank_focus`), plus one thin reader
(`user_focus`) that loads the episodes. Memory is a suggestion surface: nothing
here ever changes an answer's numbers.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

#: How many remembered questions are considered. Recent behaviour is the signal.
WINDOW = 60

#: The scope keys that describe WHAT a user covers (a period is not a focus).
_FOCUS_KEYS = ("carrier", "country")


@dataclass(frozen=True)
class FocusScope:
    """One carrier/market pairing the user keeps returning to."""

    carrier: str = ""
    country: str = ""
    count: int = 0

    @property
    def label(self) -> str:
        return " · ".join(part for part in (self.carrier, self.country) if part)

    def question(self) -> str:
        """A ready-to-edit question about this scope, in the user's own terms."""
        if self.carrier and self.country:
            return f"How is {self.carrier} performing in {self.country} this year?"
        if self.carrier:
            return f"How is {self.carrier} performing this year?"
        return f"What is the premium outlook in {self.country} this year?"


@dataclass(frozen=True)
class UserFocus:
    """Everything the product remembers about what this user works on."""

    scopes: Tuple[FocusScope, ...] = ()
    carriers: Tuple[str, ...] = ()
    countries: Tuple[str, ...] = ()
    recent_questions: Tuple[str, ...] = ()
    total_questions: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.scopes or self.recent_questions)

    @property
    def primary(self) -> Optional[FocusScope]:
        return self.scopes[0] if self.scopes else None


def _scope_of(episode: Mapping[str, Any]) -> Dict[str, str]:
    meta = episode.get("meta") or {}
    scope = meta.get("scope") if isinstance(meta, Mapping) else None
    if not isinstance(scope, Mapping):
        return {}
    return {key: str(scope.get(key) or "").strip() for key in _FOCUS_KEYS
            if str(scope.get(key) or "").strip()}


def rank_focus(episodes: Iterable[Mapping[str, Any]], *, limit: int = 3) -> UserFocus:
    """Rank remembered scopes by frequency, breaking ties by recency.

    `episodes` are newest first (the order the store returns). Pure.
    """
    ordered = [e for e in episodes if (e.get("kind") or "question") == "question"][:WINDOW]
    pair_counts: Counter = Counter()
    first_seen: Dict[Tuple[str, str], int] = {}
    carriers: Counter = Counter()
    countries: Counter = Counter()
    for position, episode in enumerate(ordered):
        scope = _scope_of(episode)
        pair = (scope.get("carrier", ""), scope.get("country", ""))
        if any(pair):
            pair_counts[pair] += 1
            first_seen.setdefault(pair, position)
        if scope.get("carrier"):
            carriers[scope["carrier"]] += 1
        if scope.get("country"):
            countries[scope["country"]] += 1
    ranked = sorted(pair_counts, key=lambda p: (-pair_counts[p], first_seen[p]))
    questions: List[str] = []
    for episode in ordered:
        text = str(episode.get("content") or "").strip()
        if text and text.lower() not in {q.lower() for q in questions}:
            questions.append(text)
        if len(questions) == limit:
            break
    return UserFocus(
        scopes=tuple(FocusScope(c, k, pair_counts[(c, k)]) for c, k in ranked[:limit]),
        carriers=tuple(name for name, _ in carriers.most_common(limit)),
        countries=tuple(name for name, _ in countries.most_common(limit)),
        recent_questions=tuple(questions),
        total_questions=len(ordered),
    )


def scope_from_chips(chips: Iterable[Mapping[str, Any]]) -> Dict[str, str]:
    """The focus keys of one answer's stamped scope chips (`core.scope`).

    A chip holding several values ("Zurich, AXA +1 more") is a comparison, not a
    focus, so only single-valued chips are remembered.
    """
    scope: Dict[str, str] = {}
    for chip in chips or []:
        key = chip.get("key")
        value = str(chip.get("value") or "").strip()
        if key in _FOCUS_KEYS or key == "period":
            if value and "," not in value and "more" not in value:
                scope[str(key)] = value
    return scope


def user_focus(user_id: Any, *, store: Any = None) -> UserFocus:
    """The working set for one user, read from the episodic store. Never raises."""
    if store is None:
        from core.memory.episodic import episodic_store as store
    try:
        episodes = store._recent(user_id, "question", WINDOW)
    except Exception:  # pragma: no cover - memory must never break a page
        return UserFocus()
    return rank_focus(episodes)
