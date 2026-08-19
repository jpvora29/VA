"""Assembly — fill the split sub-templates per entity and merge into one deck.

The split-template pipeline (axis name → its .pptx, e.g. ``overall`` → ``overall_template.pptx``):

    overall   filled once (subject-level roles)
    product   filled once per selected product
    country   filled once per selected country
    end       appended once (the closing back cover; nothing to fill)
        ↓
    merge_pptx([overall, product₁ … productₙ, country₁ … countryₘ, end])  → one .pptx

Each sub-deck is filled by the *existing* :func:`studio.template_fill.fill.fill_template`
driven by a **static** :class:`~studio.template_fill.binding_map.BindingMap` (no inference),
with values from :mod:`studio.template_fill.bindings` re-scoped to the entity. A product/
country axis is only built when that template is registered, so the pipeline runs today
(overall-only) and grows automatically as the author adds ``product``/``country`` templates
and their curated maps.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from studio.compute import DATA_BASIS_PREMIUM, DATA_BASIS_WITH_SURVEY
from studio.template_fill import (
    commentary, commentary_metrics, commentary_qa, feedback, grids, gwp_page, kpi_band,
    lc_page, prune,
)
from studio.template_fill import roles as R
from studio.template_fill.survey import facts as survey_facts
from studio.template_fill.survey import kpi as survey_kpi
from studio.template_fill.survey import page as survey_page
from studio.template_fill.analyze import analyze
from studio.template_fill.binding_map import BindingMap, available, get_binding_map
from studio.template_fill.bindings import (
    carrier_countries,
    carrier_vocab,
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
from studio.template_fill.ledger import ClaimLedger
from studio.template_fill.merge import merge_to_file
from studio.template_fill.model import _template_year

logger = get_logger(__name__)

OVERALL = "overall"
PRODUCT = "product"
COUNTRY = "country"
END = "end"

# The Carrier Survey page. NOT a member of _SCOPE_AXES: it is not a scope choice but a
# DATA BASIS one — the Setup form's "Premium + survey" — so it is gated separately, and
# rides along with whichever country blocks the chosen scope already builds. The same
# choice also decides whether the summary page keeps its overall survey-score tile
# (:mod:`studio.template_fill.survey.kpi`); both read it off the result.
SURVEY = "survey"

# Which sub-deck axes each Setup "scope" choice assembles, in deck order. "all" is the full
# deck; the single-axis choices let the author generate just the overall, product or country
# pages. Every choice still gets the closing back cover.
_SCOPE_AXES: Dict[str, Tuple[str, ...]] = {
    "all": (OVERALL, PRODUCT, COUNTRY, END),
    OVERALL: (OVERALL, END),
    PRODUCT: (OVERALL, PRODUCT, END),
    COUNTRY: (OVERALL, COUNTRY, END),
}


def _axes_for(scope: Optional[str]) -> Tuple[str, ...]:
    return _SCOPE_AXES.get((scope or "all"), _SCOPE_AXES["all"])


def _buildable() -> set:
    """Registered axes whose ``.pptx`` is actually on disk.

    A map is registered by filename, so an axis survives in the registry after its template
    is removed from ``template/``. Checking the file here means a partial template set (say
    no back cover yet) simply produces a shorter deck instead of failing the export.
    """
    names = set()
    for name in available():
        try:
            if Path(get_binding_map(name).path).exists():
                names.add(name)
            else:
                logger.warning("assemble: axis %r skipped — template file missing", name)
        except KeyError:                    # noqa: PERF203 — a broken map must not stop the rest
            logger.warning("assemble: axis %r skipped — no binding map", name)
    return names


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


# What each sub-deck's values are enriched with, in order. The survey page shares none of
# the premium providers — its numbers come from a different book entirely — so giving it
# its own list keeps it off five queries that could only ever return nothing.
_PREMIUM_PROVIDERS = (grids.grid_values, gwp_page.values, lc_page.values,
                      feedback.values, commentary.values, survey_kpi.values)
_SURVEY_PROVIDERS = (survey_page.values,)


def _premium_providers(ledger, narratives=None):
    """The premium providers with the deck's claim ledger bound into the two that write
    prose, so a claim made on one page is not made again on the next.

    The ledger is per-deck and threaded from :func:`assemble_deck` rather than kept in a
    module global: two decks generated in the same process must not share a memory of
    what has already been said.
    """
    return tuple(
        {feedback.values: feedback.with_ledger(ledger),          # extras loaded per scope
         commentary.values: commentary.with_ledger(ledger, narratives)}.get(provider, provider)
        for provider in _PREMIUM_PROVIDERS
    )

# The fill-engine payloads more than one provider can write. Everything else a provider
# returns is one role's own text and belongs to that provider alone; these are addressed by
# SHAPE, so any page can contribute to them — and a plain dict update would let whichever
# provider ran last silently erase the others' entries.
#
# Two providers already emit `drop_shapes`: the survey tile drops itself off a premium-basis
# summary page, and the GWP page drops the country chart a one-country run cannot fill. The
# shipped templates keep them apart (the overall deck has the tile and no GWP page; the
# country deck the reverse), so the clash is latent rather than live — but it is one
# re-authored template away, and it would fail silently.
_SHARED_PAYLOADS = ("drop_shapes", "resize_shapes", "cell_fills", "pictures",
                    "picture_crops", "drop_table_lines", "gwp_bars")


def _merge_values(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """``base`` updated with ``extra``, COMBINING the payloads providers share."""
    merged = {**base, **extra}
    for key in _SHARED_PAYLOADS:
        mine, theirs = base.get(key), extra.get(key)
        if not mine or not theirs:
            continue
        if isinstance(mine, dict) and isinstance(theirs, dict):
            merged[key] = {**mine, **theirs}
        elif isinstance(mine, list) and isinstance(theirs, list):
            merged[key] = list(dict.fromkeys(mine + theirs))
    return merged


def _build_subdeck(template_name: str, scoped_result, values: Dict[str, Any], label: str,
                   *, providers=_PREMIUM_PROVIDERS) -> SubDeck:
    """Finish a sub-deck: fold in grid rows, table commentary/KPIs and prose commentary,
    then drop surplus country pages.

    The template is analysed once here (reused for all). Any failure is swallowed — no
    enrichment may break assembly (a full deck beats a broken one).
    """
    hidden: Tuple[int, ...] = ()
    try:
        template = analyze(get_binding_map(template_name).path)
        for provider in providers:
            try:
                extra = provider(template, scoped_result)
            except Exception as exc:  # noqa: BLE001 — one provider must not sink the rest
                logger.warning("assemble: %s failed for %s: %s",
                               getattr(provider, "__module__", provider), template_name, exc)
                extra = None
            if extra:
                values = _merge_values(values, extra)
        tyear = _template_year(template)
        if tyear is not None:
            values.setdefault("template_year", tyear)
        # Report-only: the prose is already written and already faithful, and a judgement
        # rule must never be allowed to delete a sentence (that is how a cell ends blank).
        commentary_qa.log_issues(commentary_qa.check(values), label=label)
        # …and the same text scored on how it READS, so a commentary change is judged on a
        # number rather than on a feeling (studio.template_fill.commentary_metrics).
        commentary_metrics.log_score(
            values, subject=str(getattr(scoped_result, "subject", "") or ""), label=label)
        hidden = tuple(prune.hidden_country_pages(template, _country_count(values)))
    except Exception as exc:  # noqa: BLE001 — grid/pruning must never break assembly
        logger.warning("assemble: grid/prune failed for %s: %s", template_name, exc)
    return SubDeck(template_name, values, label=label, hidden=hidden)


def plan_subdecks(result, *, scope: Optional[str] = None,
                  data_basis: Optional[str] = None) -> List[SubDeck]:
    """The ordered sub-decks for ``result``: overall, then per product, then per country.

    ``scope`` (from the Setup "scope" control) selects which axes to build — the full deck
    ("all"), or just the overall / product / country pages. Every axis is also gated on its
    template being registered AND present on disk. The product/country entities are the user's
    selection when they pin any, ELSE every product/country the carrier writes in (so an
    unfiltered run produces the carrier's full book, one block each).

    ``data_basis`` (the Setup form's DATA BASIS control) decides whether the run draws on the
    survey book at all. Only ``"premium_survey"`` follows each country block with its Carrier
    Survey page (and only for a country that actually has one) and keeps the summary page's
    overall survey-score tile; a premium-basis run gets today's five-slide blocks and a
    summary page with that tile removed. It is put on the result so every page reads the one
    answer rather than being handed it separately.

    The OVERALL block reports on the SETUP SELECTION, filters and all: a run pinned to
    Aviation and Marine summarises Aviation + Marine premium, SoW and rank, not the
    carrier's whole book. The pinned products additionally decide how many product pages
    follow it. Each deck's values carry the entity roles, breakdown-grid rows, and (for
    products) the product vocabulary the fill engine rewrites; surplus per-country pages
    are pruned to the country count.
    """
    axes = _axes_for(scope)
    names = _buildable()
    basis = str(data_basis or DATA_BASIS_PREMIUM)
    vocab = product_vocab(result) if PRODUCT in names else ()
    want_products = PRODUCT in axes and PRODUCT in names
    want_countries = COUNTRY in axes and COUNTRY in names
    products = (selected_products(result) or vocab) if want_products else ()
    countries = (selected_countries(result) or carrier_countries(result)) if want_countries else ()
    want_survey = basis == DATA_BASIS_WITH_SURVEY and SURVEY in names and want_countries

    # Every sub-deck sees the run's whole country and product set, so a page can tell a
    # single-country run from a multi-country one — and a portfolio page can widen a
    # sub-deck's one-product pin back to the SELECTION — after its own filters are narrowed.
    # The data basis rides along too: a page sourced from the survey book asks the result.
    result = replace(result,
                     scope_countries=tuple(str(c) for c in countries),
                     scope_products=tuple(str(p) for p in selected_products(result)),
                     data_basis=basis)
    carriers = carrier_vocab(result)

    def with_context(values: Dict[str, Any]) -> Dict[str, Any]:
        """Fold in the vocabulary the fill engine rewrites authored example names from."""
        return {**values, "carrier_vocab": carriers}

    # One ledger for the whole deck, built here so it spans every sub-deck: the pages that
    # repeated each other sit in DIFFERENT sub-decks (the overall block's highlights,
    # trading summary and ranking pages all describe the same book), so a per-sub-deck
    # memory would not have caught them.
    # The narratives are collected across every sub-deck and checked ONCE at the end:
    # "two slides doing the same job" is a whole-deck question, and the overall block's
    # pages and a country block's pages can collide on it.
    narratives: List[Any] = []
    providers = _premium_providers(ClaimLedger(), narratives)

    decks: List[SubDeck] = []
    if OVERALL in axes and OVERALL in names:
        decks.append(_build_subdeck(OVERALL, result,
                                    with_context(resolve_roles(result)), "overall",
                                    providers=providers))
    for product in products:
        values = with_context(resolve_roles_for_product(result, product))
        values["product_vocab"] = vocab
        decks.append(_build_subdeck(PRODUCT, scope_to_product(result, product), values,
                                    str(product), providers=providers))
    for country in countries:
        decks.append(_build_subdeck(COUNTRY, scope_to_country(result, country),
                                    with_context(resolve_roles_for_country(result, country)),
                                    str(country), providers=providers))
        if want_survey and survey_facts.has_survey_data(result, country):
            decks.append(_build_subdeck(
                SURVEY, scope_to_country(result, country),
                # The page needs no premium roles — only its own country label, which the
                # fill engine's "Country (1)" substitution reads.
                {"country_name[0]": str(country)}, f"{country} survey",
                providers=_SURVEY_PROVIDERS))
    if END in axes and END in names:
        decks.append(SubDeck(END, {}, label="end"))
    commentary_qa.log_issues(commentary_qa.check_narratives(narratives), label="deck")
    return decks


_manifest_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}


def _augmented_manifest(bmap: BindingMap) -> List[Dict[str, Any]]:
    """The static map's manifest + the dynamic re-binders (cached per template file).

    The curated maps stay about scalar KPIs; everything positional or narrative is
    recognised generically, in this order:

      * ``grids.augment`` — the per-product breakdown grid's cells (one row per product);
      * ``gwp_page.augment`` — the GWP-performance page's TTM table and panel totals;
      * ``kpi_band.augment`` — the headline "Marsh GWP · Carrier GWP · SoW% · Rank" band;
      * ``commentary.augment`` — the prose slots (Trading Summary etc.);
      * ``feedback.augment`` — the feedback/quadrant/highlight cells and panels.
      * ``survey_page.augment`` — the Carrier Survey table's score cells.
    """
    key = (bmap.name, bmap.path)
    cached = _manifest_cache.get(key)
    if cached is None:
        template = analyze(bmap.path)
        bindings = R.manifest_from_dicts(bmap.manifest())
        for augment in (grids.augment, gwp_page.augment, kpi_band.augment,
                        commentary.augment, feedback.augment, survey_page.augment):
            bindings = augment(template, bindings)
        cached = _manifest_cache[key] = R.manifest_to_dicts(bindings)
    return cached


def _doc_from_map(bmap: BindingMap, sub: SubDeck) -> Dict[str, Any]:
    """A minimal TemplateDoc that ``fill.fill_template`` consumes (manifest from the static map)."""
    return {
        "template_path": bmap.path,
        "values": sub.values,
        "manifest": _augmented_manifest(bmap),
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


def assemble_deck(result, *, out_path: Optional[str] = None, work_dir: Optional[str] = None,
                  scope: Optional[str] = None, data_basis: Optional[str] = None) -> str:
    """Fill every sub-deck for ``result`` and merge them, in order, into ``out_path``.

    ``scope`` picks which axes to assemble (see :func:`plan_subdecks`); ``work_dir`` holds
    the intermediate filled sub-decks (a temp dir by default).
    """
    decks = plan_subdecks(result, scope=scope, data_basis=data_basis)
    tmp = work_dir or tempfile.mkdtemp(prefix="qbr_assemble_")
    Path(tmp).mkdir(parents=True, exist_ok=True)
    filled = [_fill_subdeck(sub, tmp, i) for i, sub in enumerate(decks)]
    out = out_path or str(Path.cwd() / "qbr_assembled.pptx")
    merge_to_file(filled, out)
    logger.info("assemble_deck: %d sub-deck(s) [%s] -> %s",
                len(decks), ", ".join(d.label for d in decks), out)
    return out
