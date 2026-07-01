"""Assembly — fill the split sub-templates per entity and merge into one deck.

The split-template pipeline:

    overall.pptx           filled once (subject-level roles)
    product.pptx           filled once per selected product
    country.pptx           filled once per selected country
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
from typing import Any, Dict, List, Optional

from logger import get_logger
from studio.template_fill import grids
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
    """One sub-template to fill: which registered template, with which role values."""

    template: str
    values: Dict[str, Any]
    label: str = ""             # e.g. the product/country name, for filenames + logs


def _with_grid_values(template_name: str, scoped_result, values: Dict[str, Any]) -> Dict[str, Any]:
    """``values`` plus the per-row breakdown-grid values for this sub-deck.

    A no-op for a deck without a "Carrier breakdown" grid (``grid_values`` detects the grid
    and returns ``{}`` otherwise). Failures are swallowed — a grid must never break the deck.
    """
    try:
        template = analyze(get_binding_map(template_name).path)
        grid = grids.grid_values(template, scoped_result)
    except Exception as exc:  # noqa: BLE001 — a failing grid must not break assembly
        logger.warning("assemble: grid values failed for %s: %s", template_name, exc)
        grid = {}
    return {**values, **grid} if grid else values


def plan_subdecks(result) -> List[SubDeck]:
    """The ordered sub-decks for ``result``: overall, then per product, then per country.

    Product/country axes are included only when their template is registered. The entities
    are the user's selection when they pin any, ELSE every product/country the carrier writes
    in (so an unfiltered run produces the carrier's full book, one block each). Each deck's
    values carry the entity roles, the breakdown-grid rows, and (for products) the product
    vocabulary the fill engine rewrites to the deck's product.
    """
    names = set(available())
    vocab = product_vocab(result) if PRODUCT in names else ()
    products = (selected_products(result) or vocab) if PRODUCT in names else ()
    countries = (selected_countries(result) or carrier_countries(result)) if COUNTRY in names else ()

    decks: List[SubDeck] = [
        SubDeck(OVERALL, _with_grid_values(OVERALL, result, resolve_roles(result)), label="overall")
    ]
    for product in products:
        values = resolve_roles_for_product(result, product)
        values["product_vocab"] = vocab
        values = _with_grid_values(PRODUCT, scope_to_product(result, product), values)
        decks.append(SubDeck(PRODUCT, values, label=str(product)))
    for country in countries:
        values = _with_grid_values(COUNTRY, scope_to_country(result, country),
                                   resolve_roles_for_country(result, country))
        decks.append(SubDeck(COUNTRY, values, label=str(country)))
    return decks


def _doc_from_map(bmap: BindingMap, values: Dict[str, Any]) -> Dict[str, Any]:
    """A minimal TemplateDoc that ``fill.fill_template`` consumes (manifest from the static map)."""
    return {
        "template_path": bmap.path,
        "values": values,
        "manifest": bmap.manifest(),
        "overrides": {},
        "map_overrides": {},
        "added": {},
    }


def _fill_subdeck(sub: SubDeck, work_dir: str, idx: int) -> str:
    bmap = get_binding_map(sub.template)
    safe_label = "".join(c if c.isalnum() else "_" for c in sub.label)[:24]
    out = str(Path(work_dir) / f"{idx:02d}_{sub.template}_{safe_label}.pptx")
    return fill_template(_doc_from_map(bmap, sub.values), out_path=out)


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
