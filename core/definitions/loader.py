"""Glossary loader — parses ``terms.yaml`` into immutable :class:`Term`s.

Module-level singleton mirroring :func:`core.registry.loader.get_flow_registry`, so the
glossary is parsed once per process. :func:`get_glossary` is the read-only entry point.

:meth:`Glossary.brief` is what the commentary writer actually consumes: the terms a page
is about to use, rendered as one prompt block. Everything else here exists to build that
honestly — ``validate()`` is the CI guard that stops a term shipping without the ban that
makes it safe to hand to a model.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import yaml

from core.definitions.spec import UNITS, Term
from logger import get_logger

logger = get_logger(__name__)

_TERMS_PATH = Path(__file__).parent / "terms.yaml"


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def _clean(value: Any) -> str:
    """YAML folded scalars keep their trailing newline; prompts do not want it."""
    return str(value or "").strip()


def _parse_term(key: str, raw: Mapping[str, Any]) -> Term:
    return Term(
        key=key,
        label=_clean(raw.get("label")) or key.replace("_", " ").title(),
        definition=_clean(raw.get("definition")),
        aliases=_as_tuple(raw.get("aliases")),
        formula=_clean(raw.get("formula")),
        say=_clean(raw.get("say")),
        never=_clean(raw.get("never")),
        unit=_clean(raw.get("unit")),
    )


@dataclass(frozen=True)
class Glossary:
    """Every ICG business term, by key and by alias."""

    terms: Tuple[Term, ...]

    def get(self, name: str) -> Optional[Term]:
        """The term for a key or any of its aliases, case-insensitively."""
        return self._index().get(str(name or "").strip().lower())

    def keys(self) -> Tuple[str, ...]:
        return tuple(t.key for t in self.terms)

    def brief(self, names: Iterable[str] = ()) -> str:
        """The named terms as one prompt block; every term when ``names`` is empty.

        Unknown names are skipped rather than raised on: a caller naming the terms its page
        uses must not be able to break deck generation with a typo.
        """
        wanted = [t for t in (self.get(n) for n in names) if t is not None] or (
            list(self.terms) if not list(names) else [])
        if not wanted:
            return ""
        seen: Dict[str, Term] = {t.key: t for t in wanted}
        return "\n".join(t.as_brief() for t in seen.values())

    def validate(self) -> List[str]:
        """Problems that should fail CI — an unusable term is worse than a missing one."""
        problems: List[str] = []
        for term in self.terms:
            if not term.definition:
                problems.append(f"{term.key}: no definition")
            if not term.never:
                problems.append(f"{term.key}: no `never` — the overstatement it attracts "
                                f"is the reason this file exists")
            if term.unit not in UNITS:
                problems.append(f"{term.key}: unknown unit {term.unit!r}")
        for name, owners in self._collisions().items():
            problems.append(f"{name!r} resolves to several terms: {sorted(owners)}")
        return problems

    def _index(self) -> Dict[str, Term]:
        out: Dict[str, Term] = {}
        for term in self.terms:
            for name in (term.key, term.label, *term.aliases):
                out.setdefault(str(name).strip().lower(), term)
        return out

    def _collisions(self) -> Dict[str, List[str]]:
        """Names that resolve to more than one TERM.

        A term naming itself twice (``key: premium`` and ``label: Premium``) is not a
        collision — only two different terms claiming one name is, because then
        :meth:`get` silently answers with whichever was parsed first.
        """
        owners: Dict[str, set] = {}
        for term in self.terms:
            for name in (term.key, term.label, *term.aliases):
                owners.setdefault(str(name).strip().lower(), set()).add(term.key)
        return {name: sorted(keys) for name, keys in owners.items() if len(keys) > 1}


def load_glossary(path: Path = _TERMS_PATH) -> Glossary:
    """Parse ``terms.yaml``. A broken file yields an EMPTY glossary, never an exception.

    The glossary sharpens commentary; it does not gate it. A deck must still build when
    somebody leaves a tab in the YAML, so the failure is logged loudly and the writer falls
    back to working without definitions.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 — a glossary must never break deck generation
        logger.warning("definitions: %s could not be read (%s) — running without it", path, exc)
        return Glossary(terms=())
    terms = tuple(_parse_term(key, block or {}) for key, block in raw.items()
                  if isinstance(block, Mapping))
    logger.info("definitions: loaded %d ICG term(s)", len(terms))
    return Glossary(terms=terms)


_GLOSSARY: Optional[Glossary] = None


def get_glossary() -> Glossary:
    """The process-wide glossary singleton."""
    global _GLOSSARY
    if _GLOSSARY is None:
        _GLOSSARY = load_glossary()
    return _GLOSSARY
