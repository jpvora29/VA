"""Dev tool — draft a binding map from a fixed ``.pptx`` for hand-curation.

Runs the *legacy* dynamic engine (``analyze → slots.detect → roles.infer``) ONCE over an
author-made template and writes ``studio/template_fill/maps/<name>.json``. That draft is
then reviewed/edited by hand and checked in; at runtime nothing detects or infers — the
curated JSON is the single source of truth (see ``binding_map.py``).

So ``analyze.py`` / ``slots.py`` / ``roles.py`` stay in the tree as *dev tools only*; they
are no longer on the runtime fill path.

The first arg is the logical AXIS NAME (the registry key: overall / product / country);
the second is the .pptx FILE (whatever it's actually called). They need not match.

Usage::

    python -m tools.generate_binding_map overall template/overall_template.pptx
    python -m tools.generate_binding_map product template/product_template.pptx
    python -m tools.generate_binding_map country template/country_template.pptx
"""
from __future__ import annotations

import sys
from typing import List

from studio.template_fill import grids
from studio.template_fill import roles as R
from studio.template_fill import slots as S
from studio.template_fill.analyze import analyze
from studio.template_fill.binding_map import BindingMap, SlotBinding


def draft_map(name: str, path: str) -> BindingMap:
    """Build a draft :class:`BindingMap` for ``path`` from the legacy inference engine.

    Runs ``grids.augment`` too, so a "Carrier breakdown" table's cells get positional
    ``grid:<slide>:<row>:<metric>`` roles (each row its own product) rather than the same
    flat role repeated down the column.
    """
    template = analyze(path)
    bindings = R.infer(S.detect(template))
    bindings = grids.augment(template, bindings)
    slot_bindings: List[SlotBinding] = [
        SlotBinding(
            slide_idx=b.slot.slide_idx,
            shape_id=b.slot.shape_id,
            where=tuple(b.slot.where),
            value_kind=b.slot.value_kind,
            token=b.slot.token,
            role=b.role,
        )
        for b in bindings
    ]
    return BindingMap(name=name, path=path, bindings=tuple(slot_bindings))


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    name, path = argv
    bmap = draft_map(name, path)
    out = bmap.write_json()
    mapped = sum(1 for b in bmap.bindings if not b.placeholder)
    print(f"wrote {out}: {len(bmap.bindings)} slot(s), {mapped} mapped, "
          f"{len(bmap.bindings) - mapped} left as placeholder — REVIEW BEFORE COMMIT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
