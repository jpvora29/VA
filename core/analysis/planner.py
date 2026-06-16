"""Dynamic analysis planner + lens library.

The lens library is a set of `lenses/*.md` files — composable analytical "moves"
(market context, peer benchmark, temporal trend, dimensional breakdown,
whitespace, opportunity, contradiction). `analyst_principles.md` holds always-on
heuristics. `plan_analysis` asks an LLM to select and order the lenses that add
value for a given query, producing a dependency-aware `AnalysisPlan`.

Lenses GUIDE the agent; they do not gate it. This generalizes beyond any closed
set of named recipes — product-level / industry / whitespace are just some of the
lenses, selected when relevant, never the whole universe of what can be asked.

Frontmatter (parsing mirrors core/skills/loader.py):

```markdown
---
name: market_context
description: How the market (Marsh book) is doing for the queried dimension.
applies_when: any query about a carrier's premium/share where market context helps.
requires: [GPR]
---
(lens body — SQL shape + interpretation, injected verbatim into the agent prompt)
```
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import dspy

from core.schemas.analysis import AnalysisPlan, AnalysisPlannerSignature
from core.schemas.routing import RoutingContext

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_LENSES_DIR = Path(__file__).parent / "lenses"
_PRINCIPLES_FILE = Path(__file__).parent / "analyst_principles.md"


@dataclass(frozen=True)
class LensPrimitive:
    """A deterministic primitive a lens contributes to the evidence bundle.

    `call` is a library primitive name (e.g. 'find_whitespace'); `group_by` are the
    cut columns; `filters` are usually empty (inherited from the turn's scope) but
    may pin a call-specific filter. The frontmatter block that declares these is
    OPTIONAL — a lens without it stays prompt-only, exactly as today.
    """

    call: str
    metric: str = ""
    group_by: Tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Lens:
    name: str
    description: str
    applies_when: str
    body: str
    source: Path
    primitives: Tuple[LensPrimitive, ...] = ()


@dataclass
class LensLibrary:
    """Reads `core/analysis/lenses/*.md` + analyst_principles.md once."""

    lenses_dir: Path = field(default_factory=lambda: _LENSES_DIR)
    principles_file: Path = field(default_factory=lambda: _PRINCIPLES_FILE)
    _lenses: dict[str, Lens] = field(default_factory=dict, init=False)
    _principles: str = field(default="", init=False)

    def __post_init__(self) -> None:
        for md_path in sorted(self.lenses_dir.glob("*.md")):
            if md_path.name.upper() == "README.MD":
                continue
            lens = self._parse(md_path)
            if lens is not None:
                self._lenses[lens.name] = lens
        if self.principles_file.exists():
            self._principles = self.principles_file.read_text(encoding="utf-8").strip()

    @staticmethod
    def _parse(path: Path) -> Optional[Lens]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        try:
            _, fm, body = text.split("---", 2)
        except ValueError:
            return None
        meta = _load_frontmatter(fm)
        name = meta.get("name")
        if not name:
            return None
        return Lens(
            name=str(name),
            description=str(meta.get("description", "")),
            applies_when=str(meta.get("applies_when", "")),
            body=body.strip("\n"),
            source=path,
            primitives=_parse_lens_primitives(meta.get("primitives")),
        )

    def catalog(self) -> str:
        """Compact menu (name / description / applies_when) for lens selection."""
        return "\n\n".join(
            f"- {lens.name}: {lens.description}\n  applies_when: {lens.applies_when}"
            for lens in self._lenses.values()
        )

    def principles(self) -> str:
        return self._principles

    def body(self, name: str) -> str:
        lens = self._lenses.get(name)
        return lens.body if lens else ""

    def bodies(self, names: list[str]) -> str:
        """Full bodies of the named lenses, for the agent's working prompt."""
        parts = [f"## {n}\n\n{self.body(n)}" for n in names if n in self._lenses]
        return "\n\n".join(parts)

    def names(self) -> list[str]:
        return list(self._lenses.keys())

    def lens(self, name: str) -> Optional[Lens]:
        return self._lenses.get(name)

    def primitive_calls(self, names: Sequence[str]) -> List[Dict[str, Any]]:
        """Orchestrator-ready call dicts for every primitive the named lenses declare.

        The bridge between lens selection and the analytics orchestrator: a selected
        lens with a `primitives:` block expands into its calls; lenses without one
        contribute nothing here (they stay prompt-only). Order follows `names`, then
        the order within each lens.
        """
        calls: List[Dict[str, Any]] = []
        for name in names:
            lens = self._lenses.get(name)
            if lens is None:
                continue
            for primitive in lens.primitives:
                calls.append(
                    {
                        "name": primitive.call,
                        "metric": primitive.metric,
                        "group_by": list(primitive.group_by),
                        "filters": dict(primitive.filters),
                    }
                )
        return calls


_default_library: Optional[LensLibrary] = None


def get_lens_library() -> LensLibrary:
    """Module-level singleton so each request reuses the parsed lens cache."""
    global _default_library
    if _default_library is None:
        _default_library = LensLibrary()
    return _default_library


def plan_analysis(
    user_query: str,
    routing_context: RoutingContext,
    mode: str = "chat",
) -> AnalysisPlan:
    """Select and order the analytical lenses relevant to `user_query`.

    `mode` is "chat" (focused, 2-5 lenses) or "comprehensive" (pitch — thorough).
    Returns an empty plan on failure so callers can fall back to the literal query.
    """
    library = get_lens_library()
    predictor = dspy.ChainOfThought(AnalysisPlannerSignature)
    try:
        result = predictor(
            user_query=user_query,
            routing_context=routing_context,
            lens_catalog=library.catalog(),
            analyst_principles=library.principles(),
            mode=mode,
        )
        plan = result.analysis_plan
    except Exception:  # noqa: BLE001 - planning is best-effort; never break the turn
        return AnalysisPlan(derived=[], synthesis_focus="")

    # Drop any hallucinated lens names so downstream body lookup is always valid.
    valid = set(library.names())
    plan.derived = [d for d in plan.derived if d.lens in valid]
    return plan


def _parse_lens_primitives(raw: Any) -> Tuple[LensPrimitive, ...]:
    """Parse the optional `primitives:` frontmatter block into typed specs.

    Each item is ``{call, group_by, [metric], [filters]}``. Malformed/absent
    entries are skipped so a lens degrades to prompt-only rather than erroring.
    (Requires the YAML frontmatter parser; the line-based fallback can't represent
    nested lists, in which case a lens simply contributes no primitives.)
    """
    out: List[LensPrimitive] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        call = item.get("call")
        if not call:
            continue
        out.append(
            LensPrimitive(
                call=str(call),
                metric=str(item.get("metric", "")),
                group_by=tuple(item.get("group_by") or ()),
                filters=dict(item.get("filters") or {}),
            )
        )
    return tuple(out)


def _load_frontmatter(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by lens frontmatter (mirrors SkillLoader)."""
    if yaml is not None:
        return yaml.safe_load(text) or {}

    meta: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = (
                [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]
                if inner
                else []
            )
        elif value.lower() in {"true", "false"}:
            meta[key] = value.lower() == "true"
        else:
            meta[key] = value.strip("'\"")
    return meta
