"""Prune enumerated country pages a sub-template has but the selection doesn't fill.

A template can carry more per-country pages than a given run needs — e.g. the product
template has four feedback slides covering countries 1-2, 3-4, 5-6, 7-8. When the carrier
(or the user's selection) has fewer countries, the surplus *whole pages* are dropped, so a
2-country run keeps only the first feedback page. A page that is only *partly* beyond the
count is kept — its extra country columns are blanked by ``fill._label_subs`` instead.

Deterministic and generic: a page is a country page if it carries ``Country (n)`` /
``Region (n)`` tokens; it is dropped when the LOWEST ``n`` on it exceeds the country count
(so a page enumerating countries 1-4 is never dropped, only blanked).
"""
from __future__ import annotations

import re
from typing import List

from studio.template_fill.analyze import Template

_COUNTRY_IDX = re.compile(r"(?:Country\s*/\s*)?(?:Country|Region)\s*\(\s*(\d+)\s*\)", re.I)


def _country_indices(slide) -> List[int]:
    """Every 1-based country index enumerated anywhere on ``slide`` (paras + table cells)."""
    idxs: List[int] = []
    for shape in slide.shapes:
        for para in shape.paragraphs:
            idxs += [int(m) for m in _COUNTRY_IDX.findall(para)]
        if shape.kind == "table" and shape.table:
            for row in shape.table:
                for cell in row:
                    idxs += [int(m) for m in _COUNTRY_IDX.findall(cell)]
    return idxs


def hidden_country_pages(template: Template, country_count: int) -> List[int]:
    """Slide indices of ``template`` whose country pages are wholly beyond ``country_count``.

    ``country_count`` is how many countries this deck actually fills (its ``country_name[i]``
    count). A page is hidden only when *all* its country indices exceed that — a partially
    used page stays and gets its surplus columns blanked downstream.
    """
    hidden: List[int] = []
    for slide in template.slides:
        idxs = _country_indices(slide)
        if idxs and min(idxs) > country_count:
            hidden.append(slide.index)
    return hidden
