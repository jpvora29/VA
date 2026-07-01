"""Assembly — fill the split sub-templates per entity and merge into one deck.

The split-template pipeline (axis name → its .pptx, e.g. ``overall`` → ``overall_template.pptx``):

    overall   filled once (subject-level roles)
    product   filled once per selected product
    country   filled once per selected country
        ↓
    merge_pptx([overall, product₁ … productₙ, country₁ … countryₘ])  → one .pptx

Each sub-deck is filled by the *existing* :func:`studio.template_fill.fill.fill_template`
driven by a **static** :class:`~studio.template_fill.binding_map.BindingMap` (no inference),
with values from :mod:`studio.template_fill.bindings` re-scoped to the entity. A product/
country axis is only built when that template is registered, so the pipeline runs today
(overall-only) and grows automatically as the author adds ``product``/``country`` templates
and their curated maps.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from studio.template_fill import grids, prune
from studio.template_fill.analyze import analyze
from studio.template_fill.binding_map import BindingMap, available, get_binding_map
from studio.template_fill.bindings import (
    carrier_countries,
    product_vocab,
    resolve_roles,
    resolve_roles_for_country,
    resolve_roles_for_product,
    scope_to_country,
    scope_to_product,
    selected_countries,
    selected_products,
)
from studio.template_fill.fill import fill_template
from studio.template_fill.merge import merge_to_file

logger = get_logger(__name__)

OVERALL = "overall"
PRODUCT = "product"
COUNTRY = "country"


@dataclass(frozen=True)
class SubDeck:
    """One sub-template to fill: which registered template, its values, and any pages to drop."""

    template: str
    values: Dict[str, Any]
    label: str = ""                     # the product/country name, for filenames + logs
    hidden: Tuple[int, ...] = ()        # slide indices to drop (surplus country pages)


def _country_count(values: Dict[str, Any]) -> int:
    """How many countries this deck fills — its ``country_name[i]`` count."""
    return sum(1 for k in values if k.startswith("country_name["))


def _build_subdeck(template_name: str, scoped_result, values: Dict[str, Any], label: str) -> SubDeck:
    """Finish a sub-deck: fold in breakdown-grid rows and drop surplus country pages.

    The template is analysed once here (reused for both). Any failure is swallowed — neither
    the grid nor the pruning may break assembly (a full deck beats a broken one).
    """
    hidden: Tuple[int, ...] = ()
    try:
        template = analyze(get_binding_map(template_name).path)
        grid = grids.grid_values(template, scoped_result)
        if grid:
            values = {**values, **grid}
        hidden = tuple(prune.hidden_country_pages(template, _country_count(values)))
    except Exception as exc:  # noqa: BLE001 — grid/pruning must never break assembly
        logger.warning("assemble: grid/prune failed for %s: %s", template_name, exc)
    return SubDeck(template_name, values, label=label, hidden=hidden)


def plan_subdecks(result) -> List[SubDeck]:
    """The ordered sub-decks for ``result``: overall, then per product, then per country.

    Product/country axes are included only when their template is registered. The entities
    are the user's selection when they pin any, ELSE every product/country the carrier writes
    in (so an unfiltered run produces the carrier's full book, one block each). Each deck's
    values carry the entity roles, breakdown-grid rows, and (for products) the product
    vocabulary the fill engine rewrites; surplus per-country pages are pruned to the country
    count so a 2-country run doesn't leave empty feedback pages.
    """
    names = set(available())
    vocab = product_vocab(result) if PRODUCT in names else ()
    products = (selected_products(result) or vocab) if PRODUCT in names else ()
    countries = (selected_countries(result) or carrier_countries(result)) if COUNTRY in names else ()

    decks: List[SubDeck] = [
        _build_subdeck(OVERALL, result, resolve_roles(result), "overall")
    ]
    for product in products:
        values = resolve_roles_for_product(result, product)
        values["product_vocab"] = vocab
        decks.append(_build_subdeck(PRODUCT, scope_to_product(result, product), values, str(product)))
    for country in countries:
        decks.append(_build_subdeck(COUNTRY, scope_to_country(result, country),
                                    resolve_roles_for_country(result, country), str(country)))
    return decks


def _doc_from_map(bmap: BindingMap, sub: SubDeck) -> Dict[str, Any]:
    """A minimal TemplateDoc that ``fill.fill_template`` consumes (manifest from the static map)."""
    return {
        "template_path": bmap.path,
        "values": sub.values,
        "manifest": bmap.manifest(),
        "overrides": {},
        "map_overrides": {},
        "added": {},
        "hidden": list(sub.hidden),
    }


def _fill_subdeck(sub: SubDeck, work_dir: str, idx: int) -> str:
    bmap = get_binding_map(sub.template)
    safe_label = "".join(c if c.isalnum() else "_" for c in sub.label)[:24]
    out = str(Path(work_dir) / f"{idx:02d}_{sub.template}_{safe_label}.pptx")
    return fill_template(_doc_from_map(bmap, sub), out_path=out)


def assemble_deck(result, *, out_path: Optional[str] = None, work_dir: Optional[str] = None) -> str:
    """Fill every sub-deck for ``result`` and merge them, in order, into ``out_path``.

    ``work_dir`` holds the intermediate filled sub-decks (a temp dir by default).
    """
    decks = plan_subdecks(result)
    tmp = work_dir or tempfile.mkdtemp(prefix="qbr_assemble_")
    Path(tmp).mkdir(parents=True, exist_ok=True)
    filled = [_fill_subdeck(sub, tmp, i) for i, sub in enumerate(decks)]
    out = out_path or str(Path.cwd() / "qbr_assembled.pptx")
    merge_to_file(filled, out)
    logger.info("assemble_deck: %d sub-deck(s) [%s] -> %s",
                len(decks), ", ".join(d.label for d in decks), out)
    return out
