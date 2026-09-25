"""
recap/generation/recap_generator.py

Stage 14 — Recap Generation.

Queries the InsightStore for a given deck/client/period and:

1. Groups insights by (umbrella, sub_category) pair.
2. Calls the LLM once per group to produce a titled bullet takeaway.
3. Calls the LLM once to synthesise an executive summary from all bullets.
4. Calls the LLM once to rank and cap action items to the top 3–4.

Each titled takeaway has the format:
  • <title>: <narrative sentence>

e.g.  • Country Priorities: Germany remains the anchor market, Spain is
        outperforming plan, and the Netherlands shows the strongest growth.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from recap.config import settings
from recap.schemas.enrichment import Urgency
from recap.schemas.insight_store import StructuredInsight
from recap.schemas.recap import (
    ActionItemSummary,
    CountrySummary,
    TitledTakeaway,
    RecapOutput,
)
from recap.store.insight_store import InsightStore
from recap.taxonomy.taxonomy_definitions import UMBRELLA_DEFINITIONS
from recap.llm.llm_client import PROSE_TIER, STRUCTURED_TIER, LLMClient
from recap.prompts.prompts import (
    RECAP_GENERATION_SYSTEM_PROMPT,
    RECAP_GENERATION_USER_TEMPLATE,
    RECAP_EXEC_SUMMARY_SYSTEM_PROMPT,
    RECAP_EXEC_SUMMARY_USER_TEMPLATE,
    RECAP_ACTION_RANKER_SYSTEM_PROMPT,
    RECAP_ACTION_RANKER_USER_TEMPLATE,
    COUNTRY_SUMMARY_SYSTEM_PROMPT,
    COUNTRY_SUMMARY_USER_TEMPLATE,
    TAKEAWAY_DEDUP_SYSTEM_PROMPT,
    TAKEAWAY_DEDUP_USER_TEMPLATE,
    TAKEAWAY_FORCE_COMPRESS_SYSTEM_PROMPT,
    TAKEAWAY_FORCE_COMPRESS_USER_TEMPLATE,
    RECAP_OVERLAP_SYSTEM_PROMPT,
    RECAP_OVERLAP_USER_TEMPLATE,
    FACT_CHECKER_SLIDE1_SYSTEM_PROMPT,
    FACT_CHECKER_SLIDE1_USER_TEMPLATE,
    FACT_CHECKER_SLIDE2_SYSTEM_PROMPT,
    FACT_CHECKER_SLIDE2_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)

# Urgency priority order for sorting / scoring action items
_URGENCY_ORDER = {
    Urgency.HIGH:    0,
    Urgency.MEDIUM:  1,
    Urgency.LOW:     2,
    Urgency.UNKNOWN: 3,
    Urgency.NONE:    4,
}
_URGENCY_SCORE = {
    Urgency.HIGH:    3.0,
    Urgency.MEDIUM:  2.0,
    Urgency.LOW:     1.0,
    Urgency.UNKNOWN: 0.5,
    Urgency.NONE:    0.0,
}

# Cap on how many insights are sent per group to control token usage
MAX_INSIGHTS_PER_GROUP = 20
# Hard ceiling on the number of key-takeaway bullets shown on the final
# slide. The dedup pass merges thematically-overlapping bullets first;
# if more than this many remain afterward, _force_compress_takeaways()
# repeatedly merges the most-similar remaining pair (no information
# loss) until the list is at or below this cap.
MAX_KEY_TAKEAWAYS = 6
# Safety limit on force-compress merge iterations so a stuck/failing
# LLM call can never spin the pipeline in an infinite loop.
MAX_FORCE_COMPRESS_ITERATIONS = 20
# Maximum total insights sent to the action ranker
MAX_ACTION_CANDIDATES = 20
# Number of action items to keep in the final output
TOP_N_ACTIONS = 5
# Maximum number of countries shown on the Country Feedback slide.
# When more unique countries are found, they are ranked by importance
# (volume of information + breadth of tags discussed) and only the
# top N are summarised and rendered.
MAX_COUNTRIES_ON_SLIDE = 10
# Minimum number of substantive (prose) mentions a country needs across the
# deck to earn a place on the Country Feedback slide at all. A country that
# is only name-checked in a single point buried in a large tabular deck
# carries no real narrative and is dropped rather than padded onto the slide.
MIN_MENTIONS_TO_INCLUDE = 2


import re as _re

# ---------------------------------------------------------------------------
# Structural markup stripping — removes raw table/chart block content so the
# LLM never sees bare data rows, cell fragments, or block headers.
# ---------------------------------------------------------------------------

# [TABLE DATA] / [CHART DATA] / [TABLE CONTEXT] / [CHART CONTEXT] block headers
_RE_BLOCK_HEADER = _re.compile(
    r"^\[(TABLE DATA|TABLE CONTEXT|CHART DATA|CHART CONTEXT)\]$", _re.M
)
# Labelled table rows: "Row 1: ...", "Table (N rows, ...)".
# Only strips the dimension/row-index label itself — NOT "Headers:" lines,
# because Headers: lines commonly carry the primary metric value
# (e.g. "Headers: GWP\x0b60,909,659") and must survive to preserve the number.
_RE_TABLE_ROW = _re.compile(
    r"^(?:Table\s*\(\d+\s*rows[^)]*\)|Row\s+\d+:)[^\n]*$", _re.M
)
# "Headers:" / "Row N:" label PREFIX only — strips the leading label text
# but keeps the rest of the line (which usually holds the metric value),
# instead of deleting the whole line as the old _RE_TABLE_ROW did.
_RE_ROW_LABEL_PREFIX = _re.compile(
    r"^\s*(?:Headers?|Row\s+\d+):\s*", _re.M
)
# Pipe-delimited lines — table rows serialised as "cell | cell | cell".
# A line with ANY pipe character is structurally a table row, not prose.
_RE_PIPE_ROW = _re.compile(
    r"^[^\n]*\|[^\n]*$", _re.M
)
# Raw data cell lines — lines that are pure noise: no prose (3+ consecutive
# alpha words) AND no digit at all (i.e. pure labels/codes with no number
# and no sentence structure, e.g. a bare section header fragment).
# A line is KEPT if it has prose OR contains any digit — so numeric metric
# lines like "% Change+21.9%", "Rank6", "SoW4.3%" are never deleted just
# because they lack 3 consecutive alphabetic words.
_RE_DATA_CELL = _re.compile(
    r"^(?!(?:.*?\b[A-Za-z]+\b\s+){2}[A-Za-z]+\b)(?!.*\d)[^\n]{1,120}$",
    _re.M
)

# Minimum prose characters remaining after stripping structural markup
# for an insight to contribute to key-takeaway generation.
_MIN_PROSE_CHARS = 20

def _is_prose_sentence(text: str) -> bool:
    """
    Return True if `text` contains at least one run of 5 consecutive tokens
    where 3 or more are alphabetic words of ≥ 3 characters.

    This distinguishes genuine prose ("2025 focuses on rebuilding SRCS UK
    Global after loss") from label fragments ("Marsh Book % Change+10.2%",
    "GWP94,665,505", "SoW2.9%") that look like data-cell content.
    """
    # Reject lines that contain any pipe character — these are table rows
    if "|" in text:
        return False
    tokens = text.split()
    if len(tokens) < 5:
        return False
    for i in range(len(tokens) - 4):
        window = tokens[i:i + 5]
        alpha_words = sum(1 for t in window if _re.match(r'^[A-Za-z]{3,}', t))
        if alpha_words >= 3:
            return True
    return False


def _strip_structural_markup(content: str) -> str:
    """
    Remove raw structured-data markup from an insight's content string.

    Strips in order:
      1. [TABLE DATA] / [CHART DATA] / context block headers
      2. Labelled table rows (Row N: / Headers: / Table(N rows))
      3. Bare data-cell lines — lines with no alphabetic word ≥ 4 chars,
         which are raw cell values that leaked through without Row/Header labels
         (e.g. "GWP94,665,505", "% Change-16.1%", "SoW2.9%", "Rank12")

    Leaves only prose sentences and inline numbers that are part of context.
    """
    text = _RE_BLOCK_HEADER.sub("", content)
    text = _RE_TABLE_ROW.sub("", text)
    # Strip "Headers:" / "Row N:" label prefixes but KEEP the rest of the
    # line — this is what preserves the metric value that used to be
    # deleted wholesale by the old _RE_TABLE_ROW (e.g. "Headers: GWP...60,909,659").
    text = _RE_ROW_LABEL_PREFIX.sub("", text)
    # Strip pipe-delimited table rows (cell | cell | cell)
    text = _RE_PIPE_ROW.sub("", text)
    # Strip lines that are pure noise: no prose AND no digit at all
    text = _RE_DATA_CELL.sub("", text)
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _format_metric_entry(entry) -> str:
    """
    Render one metadata.metrics / metadata.kpis list entry as a clean
    "label: value" string for prompt injection.

    Entries are normally plain strings (e.g. "GWP: 60,909,659"), but the
    enrichment LLM sometimes emits a dict for a single metric (e.g.
    {"name": "GWP", "value": "60,909,659"} or {"label": ..., "value": ...}).
    Pydantic's List[str] coerces that dict to its Python repr string
    (e.g. "{\'name\': \'GWP\', \'value\': \'60,909,659\'}"), which is unreadable
    noise if passed straight through. This reconstructs "name: value"
    (falling back to str(entry)) for both shapes so no numeric figure is
    lost or garbled on the way into the LLM prompt.
    """
    if isinstance(entry, dict):
        label = entry.get("name") or entry.get("label") or entry.get("metric")
        value = entry.get("value")
        extra = entry.get("direction") or entry.get("context")
        if label and value is not None:
            base = f"{label}: {value}"
            return f"{base} ({extra})" if extra else base
        return str(entry)
    text = str(entry).strip()
    # Defensive: some entries may already be a stringified dict repr
    # (e.g. produced upstream before coercion) rather than a real dict.
    if text.startswith("{") and "'value'" in text:
        try:
            import ast
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return _format_metric_entry(parsed)
        except (ValueError, SyntaxError):
            pass
    return text


def _has_sufficient_prose(content: str) -> bool:
    """
    Return True if the insight has genuine prose content after stripping all
    structural markup.  Two conditions must both hold:
      1. At least _MIN_PROSE_CHARS characters remain.
      2. At least one line reads as a prose sentence (two words each ≥ 4 chars).
    This prevents short label fragments like "Country / Regional Performance:"
    from masquerading as meaningful prose.
    """
    stripped = _strip_structural_markup(content)
    if len(stripped) < _MIN_PROSE_CHARS:
        return False
    return any(_is_prose_sentence(line) for line in stripped.splitlines() if line.strip()) or _is_prose_sentence(stripped)


def _country_importance_score(insights: List[StructuredInsight]) -> float:
    """
    Score a country's importance for the Country Feedback slide.

    Combines two signals:
      1. Volume of substantive information — number of insights with
         genuine prose content, plus total prose character length.
      2. Breadth of tags discussed — distinct lines of business, KPIs,
         metrics, regions, umbrella/sub-category classifications, plus
         a bonus for opportunity/concern flags and action items, which
         signal the country carries decision-relevant content.

    Only insights with sufficient prose contribute — table/list-only
    mentions of a country carry no weight.
    """
    prose_insights = [i for i in insights if _has_sufficient_prose(i.content)]
    if not prose_insights:
        return 0.0

    volume_score = float(len(prose_insights))
    content_len_score = sum(
        len(_strip_structural_markup(i.content)) for i in prose_insights
    ) / 200.0

    tags: set = set()
    flag_score = 0.0
    for ins in prose_insights:
        md = ins.metadata
        tags.update(md.lines_of_business)
        tags.update(md.kpis)
        tags.update(md.metrics)
        tags.update(md.regions)
        tags.update(ins.umbrella_labels)
        tags.update(ins.sub_category_labels)
        if md.is_opportunity:
            flag_score += 1.0
        if md.is_concern:
            flag_score += 1.0
        if ins.action_item.is_action_item:
            flag_score += 1.0

    tag_score = float(len(tags))

    return (volume_score * 2.0) + content_len_score + (tag_score * 1.5) + flag_score


def _country_mention_count(insights: List[StructuredInsight]) -> int:
    """Number of insights for a country that carry genuine prose content."""
    return sum(1 for i in insights if _has_sufficient_prose(i.content))


def _country_target_sentences(insights: List[StructuredInsight]) -> int:
    """
    Decide how many sentences a country's summary should contain,
    proportional to how much that country is actually discussed in the deck.

      1 sentence  — light coverage: the minimum 2 substantive mentions,
                    scattered and not concentrated on any one slide.
      2 sentences — moderate coverage: 3-4 substantive mentions, or spread
                    across 2+ slides (a recurring but not headline topic).
      3 sentences — heavy coverage: 5+ substantive mentions, or a clearly
                    dedicated slide (3+ substantive content units on the
                    same slide) — e.g. a whole slide devoted to the country.

    Countries below MIN_MENTIONS_TO_INCLUDE are filtered out upstream and
    never reach this function.
    """
    prose_insights = [i for i in insights if _has_sufficient_prose(i.content)]
    mention_count = len(prose_insights)
    slide_counts = Counter(i.slide_number for i in prose_insights)
    dedicated_slide = any(c >= 3 for c in slide_counts.values())
    distinct_slides = len(slide_counts)

    if dedicated_slide or mention_count >= 5:
        return 3
    if mention_count >= 3 or distinct_slides >= 2:
        return 2
    return 1


def _sub_category_label(umbrella_key: str, sub_cat_key: Optional[str]) -> str:
    """Return a human-readable label for a sub-category key."""
    if not sub_cat_key:
        return UMBRELLA_DEFINITIONS[umbrella_key]["label"]
    sub_cats = UMBRELLA_DEFINITIONS[umbrella_key].get("sub_categories", {})
    entry = sub_cats.get(sub_cat_key)
    if entry:
        return entry["label"]
    return sub_cat_key.replace("_", " ").title()


def _priority_score(ai: ActionItemSummary) -> float:
    """
    Composite priority score for ranking action items.
    Higher = more important.
    Components:
      - urgency  : 0–3
      - confidence: 0–1
      - specificity bonus: +0.5 per filled field (owner, deadline, lob, geo)
    """
    score = _URGENCY_SCORE.get(ai.urgency, 0.0)
    score += ai.confidence
    if ai.owner:
        score += 0.5
    if ai.deadline:
        score += 0.5
    if ai.line_of_business:
        score += 0.25
    if ai.geography:
        score += 0.25
    return score


class RecapGenerator:
    """
    Generates a structured recap from the InsightStore.

    For each (umbrella, sub_category) group found in the insights the LLM
    is asked to produce ONE titled bullet.  A second LLM call synthesises
    the executive summary.  A third LLM call ranks and caps action items.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        # The recap is the one stage whose output a person reads as prose, so it
        # runs on the prose tier by default. The mechanical passes (dedup,
        # force-compress, overlap, fact-checks, action ranking) ask for the
        # structured tier per call. Every pass goes through this ONE client: it owns
        # the semaphore that bounds the run's fan-out, and it is the seam a test
        # stubs — a fresh LLMClient() per pass would escape both.
        self._llm = llm_client or LLMClient(PROSE_TIER)

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    async def generate(
        self,
        store: InsightStore,
        deck_id: str,
        client_name: Optional[str] = None,
        period_label: Optional[str] = None,
        meeting_date: Optional[str] = None,
        meeting_type: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> RecapOutput:
        """
        Generate a recap for a specific deck.
        """
        insights = store.query(deck_id=deck_id, min_confidence=min_confidence)

        # Sanity check: all insights must belong to this deck.
        # Foreign deck_ids indicate possible InsightStore contamination.
        foreign_ids = [i.deck_id for i in insights if i.deck_id != deck_id]
        if foreign_ids:
            logger.error(
                "generate(): %d insight(s) from foreign deck_id(s) found in "
                "store for deck_id=%s — possible store contamination. "
                "Foreign deck_ids: %s — these insights will be excluded.",
                len(foreign_ids), deck_id, set(foreign_ids),
            )
            insights = [i for i in insights if i.deck_id == deck_id]

        if not insights:
            logger.warning("No insights found for deck_id=%s", deck_id)
            return self._empty_recap(deck_id, client_name, period_label)

        logger.info(
            "Generating recap for deck_id=%s | insights=%d",
            deck_id, len(insights),
        )

        # 1. Group insights by (umbrella, sub_category)
        groups = self._group_insights(insights)
        logger.info("Insight groups (umbrella × sub_category): %d", len(groups))

        # 2. Generate one titled bullet per group — all groups run concurrently
        takeaway_tasks = [
            self._generate_takeaway(umbrella_key, sub_cat_key, group_insights,
                                    client_name, period_label, meeting_type)
            for (umbrella_key, sub_cat_key), group_insights in groups.items()
        ]
        takeaway_results = await asyncio.gather(*takeaway_tasks, return_exceptions=True)

        key_takeaways: List[TitledTakeaway] = []
        for result in takeaway_results:
            if isinstance(result, Exception):
                logger.error("Takeaway generation failed: %s", result)
            elif result is not None:
                key_takeaways.append(result)

        # Sort takeaways by umbrella order for consistent output
        _umbrella_order = {
            "performance_and_position": 0,
            "opportunity_and_growth": 1,
            "market_and_external_context": 2,
            "relationship_and_collaboration": 3,
        }
        key_takeaways.sort(key=lambda t: (
            _umbrella_order.get(t.umbrella, 9),
            t.sub_category or "",
        ))

        # 3. Executive summary — sourced ONLY from the Performance & Position
        #    umbrella (excluding the Line of Business Performance sub-category,
        #    which is LoB-specific detail that does not belong in the
        #    umbrella-level executive summary).
        #
        #    IMPORTANT: this filter runs on the PRE-dedup takeaways, where each
        #    bullet's umbrella/sub_category tag corresponds exactly to the
        #    single (umbrella, sub_category) group it was generated from. The
        #    dedup step below merges bullets across umbrellas/sub-categories
        #    purely on thematic similarity (it explicitly ignores umbrella
        #    labels when deciding what to merge), so a post-dedup bullet
        #    tagged performance_and_position could otherwise silently absorb
        #    LoB-specific or segment-specific narrative from a merged Line of
        #    Business Performance or Opportunity & Growth bullet. Filtering
        #    before dedup guarantees the executive summary is built exclusively
        #    from untainted performance_and_position-only content.
        exec_summary_source_takeaways = self._filter_exec_summary_source(key_takeaways)
        executive_summary = await self._generate_exec_summary(
            exec_summary_source_takeaways, client_name, period_label, meeting_type
        )

        # 3b. Deduplication checkpoint — merge or drop bullets that carry the
        #     same core commercial claim before anything is passed downstream.
        #     Runs AFTER exec summary generation so the merge step cannot
        #     contaminate the umbrella-pure source material used above.
        key_takeaways = await self._dedup_takeaways(
            key_takeaways, client_name, period_label
        )
        logger.info("Takeaways after dedup: %d", len(key_takeaways))

        # 3c. Hard-cap enforcement — if more than MAX_KEY_TAKEAWAYS bullets
        #     survive the 65%-overlap dedup pass, repeatedly merge the most
        #     similar remaining pair (no information loss) until the list
        #     is at or below the cap.
        key_takeaways = await self._force_compress_takeaways(
            key_takeaways, client_name, period_label
        )
        logger.info(
            "Takeaways after force-compress cap (<=%d): %d",
            MAX_KEY_TAKEAWAYS, len(key_takeaways),
        )

        # 4b. Remove overlap between the executive summary and the key
        #     takeaways — the point used for the executive summary should
        #     not also appear as (essentially) the first key takeaway.
        key_takeaways = await self._remove_exec_summary_overlap(
            executive_summary, key_takeaways, client_name, period_label
        )
        logger.info("Takeaways after exec-summary overlap removal: %d", len(key_takeaways))

        # 5. Fact-check Pass 1 — verify exec summary, takeaways BEFORE
        #    ranking so only fact-checked content enters the ranker.
        #    Action items are not yet generated here; we pass an empty list
        #    and rank afterward so the ranker works on clean, checked inputs.
        executive_summary, key_takeaways, _ = (
            await self._fact_check_slide1(
                insights, executive_summary, key_takeaways,
                [], client_name, period_label,
            )
        )
        logger.info(
            "Fact-check pass 1 complete: %d takeaways",
            len(key_takeaways),
        )

        # 6. Rank and cap action items — runs on fact-checked takeaways.
        action_items = await self._rank_action_items(
            insights, client_name, period_label, meeting_date
        )

        # 7. Fact-check Pass 1b — re-verify exec summary + takeaways +
        #    action items together now that action items are available.
        executive_summary, key_takeaways, action_items = (
            await self._fact_check_slide1(
                insights, executive_summary, key_takeaways,
                action_items, client_name, period_label,
            )
        )
        logger.info(
            "Fact-check pass 1b complete: %d takeaways, %d actions",
            len(key_takeaways), len(action_items),
        )

        # 7b. Re-run action-item dedup AFTER the fact-checker rewrite.
        #     The fact-checker is allowed to rewrite action text (e.g. to fix
        #     geographic scope or metric conflation), and that rewrite can
        #     pull two previously-distinct items back into near-duplicate
        #     wording (both ending up describing the same pipeline goal, for
        #     example). Dedup only ran once, before this rewrite, so it must
        #     run again on the post-fact-check text to catch duplicates that
        #     the rewrite itself introduced.
        _pre_dedup_count = len(action_items)
        action_items = self._dedup_action_items(action_items)
        if len(action_items) != _pre_dedup_count:
            logger.info(
                "Post-fact-check action dedup: %d -> %d",
                _pre_dedup_count, len(action_items),
            )

        # 8. Per-country summaries (only when 2+ unique countries present)
        country_summaries = await self._generate_country_summaries(
            insights, client_name, period_label
        )

        # 9. Fact-check Pass 2 — verify country summaries immediately after
        #    generation, before they are written to the output object / PPTX.
        country_summaries = await self._fact_check_slide2(
            insights, country_summaries, client_name, period_label,
        )
        logger.info(
            "Fact-check pass 2 complete: %d countries", len(country_summaries),
        )

        # 9b. Deterministic safety net: strip any raw line-of-business name
        #     that slipped into a takeaway title despite the LLM prompt's
        #     instruction not to (e.g. "Property-Led Portfolio Shift"). This
        #     is a pure-Python check against the canonical LoB list so it
        #     cannot be bypassed by an LLM that ignores the prompt rule.
        key_takeaways = self._neutralise_takeaway_titles(key_takeaways)

        # Overall confidence
        conf_scores = [
            i.metadata.overall_confidence
            for i in insights if i.metadata.overall_confidence > 0
        ]
        overall_conf = statistics.mean(conf_scores) if conf_scores else 0.0

        return RecapOutput(
            deck_id=deck_id,
            period_label=period_label,
            client_name=client_name,
            executive_summary=executive_summary,
            key_takeaways=key_takeaways,
            action_items=action_items,
            country_summaries=country_summaries,
            overall_confidence=round(overall_conf, 3),
            contributing_insight_ids=[i.insight_id for i in insights],
        )

    # ----------------------------------------------------------------
    # Grouping
    # ----------------------------------------------------------------

    def _group_insights(
        self, insights: List[StructuredInsight]
    ) -> Dict[Tuple[str, Optional[str]], List[StructuredInsight]]:
        """
        Group insights by (umbrella_key, sub_category_key).

        An insight may appear in multiple groups if it belongs to multiple
        umbrellas.  Within each group, keep the highest-confidence insights
        up to MAX_INSIGHTS_PER_GROUP.
        """
        # umbrella_key → sub_category attr name on ClassificationBundle
        _sub_cat_attr = {
            "performance_and_position":      "performance_sub_category",
            "opportunity_and_growth":        "growth_sub_category",
            "market_and_external_context":   "market_sub_category",
            "relationship_and_collaboration": "relationship_sub_category",
        }

        raw: Dict[Tuple[str, Optional[str]], List[StructuredInsight]] = defaultdict(list)

        for ins in insights:
            # Skip insights whose content is purely structural markup
            # (bare [TABLE DATA] / [CHART DATA] blocks with no prose).
            # These are used as supporting evidence elsewhere but must not
            # drive key takeaway bullets.
            if not _has_sufficient_prose(ins.content):
                logger.debug(
                    "Skipping structural-only insight %s from key takeaway grouping",
                    ins.content_unit_id,
                )
                continue

            for umbrella_key in ins.umbrella_labels:
                sub_cat_attr = _sub_cat_attr.get(umbrella_key)
                sub_cat_key: Optional[str] = None
                if sub_cat_attr:
                    sc_result = getattr(ins.classification, sub_cat_attr, None)
                    if sc_result and sc_result.sub_category:
                        sub_cat_key = sc_result.sub_category
                raw[(umbrella_key, sub_cat_key)].append(ins)

        # Sort each group by confidence desc, cap at MAX_INSIGHTS_PER_GROUP
        grouped: Dict[Tuple[str, Optional[str]], List[StructuredInsight]] = {}
        for key, group in raw.items():
            sorted_group = sorted(
                group,
                key=lambda i: -i.metadata.overall_confidence,
            )
            grouped[key] = sorted_group[:MAX_INSIGHTS_PER_GROUP]

        return grouped

    # ----------------------------------------------------------------
    # Per-group takeaway generation
    # ----------------------------------------------------------------

    async def _generate_takeaway(
        self,
        umbrella_key: str,
        sub_cat_key: Optional[str],
        group_insights: List[StructuredInsight],
        client_name: Optional[str],
        period_label: Optional[str],
        meeting_type: Optional[str] = None,
    ) -> Optional[TitledTakeaway]:
        """Call the LLM once to produce a titled bullet for one group."""
        umbrella_label = UMBRELLA_DEFINITIONS[umbrella_key]["label"]
        sub_cat_label = _sub_category_label(umbrella_key, sub_cat_key)
        insights_block = self._build_insights_block(group_insights)

        user_message = RECAP_GENERATION_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            meeting_type=meeting_type or "(not detected)",
            umbrella_label=umbrella_label,
            sub_category_label=sub_cat_label,
            insight_count=len(group_insights),
            insights_block=insights_block,
        )

        try:
            raw = await self._llm.call(
                system_prompt=RECAP_GENERATION_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=settings.token_budget("recap_takeaway"),
                reasoning_effort=settings.reasoning_effort_for("recap_takeaway"),
                stage="recap_takeaway",
            )
            d = json.loads(raw) if isinstance(raw, str) else raw
            title = str(d.get("title", sub_cat_label)).strip()
            narrative = str(d.get("narrative", "")).strip()
            if not narrative:
                return None
            return TitledTakeaway(
                title=title,
                narrative=narrative,
                umbrella=umbrella_key,
                sub_category=sub_cat_key,
                source_content_unit_ids=d.get("source_content_unit_ids", [
                    i.content_unit_id for i in group_insights
                ]),
            )
        except Exception as exc:
            logger.error(
                "Takeaway LLM failed for (%s, %s): %s", umbrella_key, sub_cat_key, exc
            )
            # Fallback: use highest-confidence insight content directly
            # (stripped of structural markup so no raw table rows appear)
            best = group_insights[0]
            return TitledTakeaway(
                title=sub_cat_label,
                narrative=_strip_structural_markup(best.content)[:500],
                umbrella=umbrella_key,
                sub_category=sub_cat_key,
                source_content_unit_ids=[best.content_unit_id],
            )

    # ----------------------------------------------------------------
    # Takeaway deduplication checkpoint
    # ----------------------------------------------------------------

    def _derive_merged_fields(
        self,
        source_bullet_numbers: List[int],
        original_takeaways: List["TitledTakeaway"],
    ) -> Tuple[str, Optional[str], List[str]]:
        """
        Deterministically derive (umbrella, sub_category, source_content_unit_ids)
        for a merged bullet from the original bullets it was built from.

        The dedup/force-compress LLMs are deliberately shown ONLY each
        bullet's title/narrative (no umbrella or sub_category tag), so they
        cannot be asked to output umbrella/sub_category themselves without
        inventing a taxonomy key blind. Instead they reference source
        bullets by number, and this helper maps that back to real schema
        values:
          - umbrella: majority vote across the source bullets' original
            umbrellas (ties broken by earliest-appearing bullet).
          - sub_category: the shared sub_category if all source bullets
            that contributed to the winning umbrella agree; otherwise None
            (a merged bullet spanning sub-categories is umbrella-level).
          - source_content_unit_ids: union of all source bullets' IDs.
        """
        valid_indices = [
            n - 1 for n in source_bullet_numbers
            if isinstance(n, int) and 1 <= n <= len(original_takeaways)
        ]
        if not valid_indices:
            # Defensive fallback — should not happen with a well-formed
            # response, but never let a bad index list crash the pipeline.
            return (
                original_takeaways[0].umbrella if original_takeaways else "",
                None,
                [],
            )

        sources = [original_takeaways[i] for i in valid_indices]

        umbrella_counts = Counter(t.umbrella for t in sources)
        top_count = max(umbrella_counts.values())
        # Earliest-appearing bullet's umbrella wins ties, for determinism.
        winning_umbrella = next(
            t.umbrella for t in sources if umbrella_counts[t.umbrella] == top_count
        )

        sub_cats_for_winner = {
            t.sub_category for t in sources if t.umbrella == winning_umbrella
        }
        winning_sub_category = (
            next(iter(sub_cats_for_winner))
            if len(sub_cats_for_winner) == 1
            else None
        )

        source_ids: List[str] = []
        for t in sources:
            source_ids.extend(t.source_content_unit_ids)

        return winning_umbrella, winning_sub_category, source_ids

    async def _dedup_takeaways(
        self,
        takeaways: List[TitledTakeaway],
        client_name: Optional[str],
        period_label: Optional[str],
    ) -> List[TitledTakeaway]:
        """
        Post-generation deduplication checkpoint.

        Sends the full list of drafted takeaways to a separate LLM call
        whose sole job is to identify bullets that substantially overlap
        in theme/content (~65% similarity — see TAKEAWAY_DEDUP_SYSTEM_PROMPT)
        and merge them. The comparison is deliberately BLIND to each
        bullet's source umbrella/sub_category: only title + narrative text
        is shown to the LLM, so a bullet from "country_regional_performance"
        and one from "overall_trading_performance" that both restate the
        same country's GWP decline are compared purely on what they say,
        not on which taxonomy bucket produced them. The original list is
        returned unchanged on any failure so the pipeline is never blocked.
        """
        if len(takeaways) <= 1:
            return takeaways

        # Serialise bullets for the LLM — numbered for easy reference.
        # Deliberately omits umbrella/sub_category so the merge decision
        # is based solely on the bullet's actual content (per requirement:
        # dedup should treat points independently of their umbrella/
        # sub-category label).
        bullets_lines: List[str] = []
        for i, t in enumerate(takeaways, 1):
            bullets_lines.append(
                f"{i}. Title: {t.title}\n"
                f"   Narrative: {t.narrative}"
            )
        bullets_block = "\n\n".join(bullets_lines)

        user_message = TAKEAWAY_DEDUP_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            bullet_count=len(takeaways),
            bullets_block=bullets_block,
        )

        try:
            raw = await self._llm.call(
                system_prompt=TAKEAWAY_DEDUP_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=settings.token_budget("recap_dedup"),
                reasoning_effort=settings.reasoning_effort_for("recap_dedup"),
                stage="recap_dedup",
                tier=STRUCTURED_TIER,
            )
            d = json.loads(raw) if isinstance(raw, str) else raw
            deduped_raw = d.get("deduped_takeaways", [])
            if not deduped_raw:
                logger.warning("Dedup LLM returned empty list — keeping originals")
                return takeaways

            deduped: List[TitledTakeaway] = []
            for item in deduped_raw:
                title     = str(item.get("title", "")).strip()
                narrative = str(item.get("narrative", "")).strip()
                source_nums = item.get("source_bullet_numbers", []) or []
                if not title or not narrative or not source_nums:
                    continue
                umbrella, sub_cat, source_ids = self._derive_merged_fields(
                    source_nums, takeaways
                )
                if not umbrella:
                    continue
                deduped.append(TitledTakeaway(
                    title=title,
                    narrative=narrative,
                    umbrella=umbrella,
                    sub_category=sub_cat,
                    source_content_unit_ids=source_ids,
                ))

            if not deduped:
                logger.warning("Dedup produced no valid bullets — keeping originals")
                return takeaways

            logger.info(
                "Dedup: %d bullets → %d bullets",
                len(takeaways), len(deduped),
            )
            return deduped

        except Exception as exc:
            logger.error("Takeaway dedup LLM failed: %s — keeping originals", exc)
            return takeaways

    async def _force_compress_takeaways(
        self,
        takeaways: List[TitledTakeaway],
        client_name: Optional[str],
        period_label: Optional[str],
        max_takeaways: int = MAX_KEY_TAKEAWAYS,
    ) -> List[TitledTakeaway]:
        """
        Hard-cap enforcement checkpoint that runs AFTER _dedup_takeaways().

        The 65%-overlap dedup pass merges thematically redundant bullets,
        but a deck with many genuinely distinct points can still exceed
        the presentation's hard limit of `max_takeaways` bullets. This
        step repeatedly merges whichever single pair of remaining bullets
        is MOST similar to each other (even below the usual 65% overlap
        bar), preserving every fact from both, until the list is at or
        below the cap. Like _dedup_takeaways(), each call is blind to
        umbrella/sub_category — comparison is by title/narrative content
        only.

        Runs one LLM call per merge (removes exactly one bullet per
        call) rather than one big call, so each merge decision is easy
        to verify and a failure partway through simply stops further
        compression rather than corrupting the whole list. Falls back to
        returning the list as-is (uncapped) if a compression call fails,
        so the pipeline is never blocked.
        """
        iterations = 0
        while len(takeaways) > max_takeaways:
            iterations += 1
            if iterations > MAX_FORCE_COMPRESS_ITERATIONS:
                logger.warning(
                    "Force-compress: hit iteration safety limit (%d) with "
                    "%d bullets still remaining (target %d) — stopping",
                    MAX_FORCE_COMPRESS_ITERATIONS, len(takeaways), max_takeaways,
                )
                break

            bullets_lines: List[str] = []
            for i, t in enumerate(takeaways, 1):
                bullets_lines.append(
                    f"{i}. Title: {t.title}\n"
                    f"   Narrative: {t.narrative}"
                )
            bullets_block = "\n\n".join(bullets_lines)

            user_message = TAKEAWAY_FORCE_COMPRESS_USER_TEMPLATE.format(
                client_name=client_name or "the client",
                period_label=period_label or "",
                bullet_count=len(takeaways),
                max_takeaways=max_takeaways,
                bullets_block=bullets_block,
            )

            try:
                raw = await self._llm.call(
                    system_prompt=TAKEAWAY_FORCE_COMPRESS_SYSTEM_PROMPT.format(
                        max_takeaways=max_takeaways
                    ),
                    user_message=user_message,
                    max_completion_tokens=settings.token_budget("recap_force_compress"),
                    reasoning_effort=settings.reasoning_effort_for("recap_force_compress"),
                    stage="recap_force_compress",
                    tier=STRUCTURED_TIER,
                )
                d = json.loads(raw) if isinstance(raw, str) else raw
                compressed_raw = d.get("compressed_takeaways", [])
                if not compressed_raw:
                    logger.warning(
                        "Force-compress LLM returned empty list — stopping "
                        "compression with %d bullets remaining",
                        len(takeaways),
                    )
                    break

                compressed: List[TitledTakeaway] = []
                for item in compressed_raw:
                    title     = str(item.get("title", "")).strip()
                    narrative = str(item.get("narrative", "")).strip()
                    source_nums = item.get("source_bullet_numbers", []) or []
                    if not title or not narrative or not source_nums:
                        continue
                    umbrella, sub_cat, source_ids = self._derive_merged_fields(
                        source_nums, takeaways
                    )
                    if not umbrella:
                        continue
                    compressed.append(TitledTakeaway(
                        title=title,
                        narrative=narrative,
                        umbrella=umbrella,
                        sub_category=sub_cat,
                        source_content_unit_ids=source_ids,
                    ))

                if not compressed or len(compressed) >= len(takeaways):
                    logger.warning(
                        "Force-compress produced no valid reduction (%d -> %d) "
                        "— stopping compression",
                        len(takeaways), len(compressed),
                    )
                    break

                logger.info(
                    "Force-compress: %d bullets -> %d bullets (target <= %d)",
                    len(takeaways), len(compressed), max_takeaways,
                )
                takeaways = compressed

            except Exception as exc:
                logger.error(
                    "Force-compress LLM failed: %s — stopping compression "
                    "with %d bullets remaining", exc, len(takeaways),
                )
                break

        return takeaways


    # ----------------------------------------------------------------
    # Executive summary generation
    # ----------------------------------------------------------------

    # Umbrellas allowed to feed the executive summary. Opportunity & Growth
    # and Relationship & Collaboration are included (alongside Performance &
    # Position) so the summary has enough narrative substance to synthesise
    # a real story rather than reading off bare metric rows. Market &
    # External Context stays excluded — it is backdrop/context, not the
    # client's own commercial story.
    _EXEC_SUMMARY_ALLOWED_UMBRELLAS = {
        "performance_and_position",
        "opportunity_and_growth",
        "relationship_and_collaboration",
    }

    # Sub-categories that must NOT feed the executive summary because they
    # carry LoB-specific or segment-specific detail rather than
    # umbrella-level commercial position. Excluded regardless of which
    # allowed umbrella they fall under (line_of_business_performance sits
    # under Performance & Position; segment_focus sits under Opportunity &
    # Growth) so no line-of-business or segment name can leak into the
    # executive summary even though the umbrellas themselves are now wider.
    _EXEC_SUMMARY_EXCLUDED_SUB_CATEGORIES = {
        "line_of_business_performance",
        "segment_focus",
    }

    def _filter_exec_summary_source(
        self, takeaways: List[TitledTakeaway]
    ) -> List[TitledTakeaway]:
        """
        Restrict the executive summary's source material to
        Performance & Position, Opportunity & Growth, and Relationship &
        Collaboration takeaways — excluding Market & External Context
        (backdrop, not the client's own story) and excluding any
        LoB-specific or segment-specific sub-category so no individual
        line of business or segment name can leak into the executive
        summary.
        """
        filtered = [
            t for t in takeaways
            if t.umbrella in self._EXEC_SUMMARY_ALLOWED_UMBRELLAS
            and t.sub_category not in self._EXEC_SUMMARY_EXCLUDED_SUB_CATEGORIES
        ]
        logger.info(
            "Executive summary source filter: %d takeaways (of %d total) "
            "after restricting to allowed umbrellas and excluding "
            "LoB/segment-specific sub-categories",
            len(filtered), len(takeaways),
        )
        return filtered

    async def _generate_exec_summary(
        self,
        takeaways: List[TitledTakeaway],
        client_name: Optional[str],
        period_label: Optional[str],
        meeting_type: Optional[str] = None,
    ) -> str:
        if not takeaways:
            return "No insights available for this review period."

        takeaways_block = "\n".join(
            f"• {t.title}: {t.narrative}" for t in takeaways
        )
        user_message = RECAP_EXEC_SUMMARY_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            meeting_type=meeting_type or "(not detected)",
            takeaways_block=takeaways_block,
        )
        try:
            raw = await self._llm.call(
                system_prompt=RECAP_EXEC_SUMMARY_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=settings.token_budget("recap_exec_summary"),
                reasoning_effort=settings.reasoning_effort_for("recap_exec_summary"),
                stage="recap_exec_summary",
            )
            d = json.loads(raw) if isinstance(raw, str) else raw
            return str(d.get("executive_summary", "")).strip()
        except Exception as exc:
            logger.error("Executive summary LLM failed: %s", exc)
            # Fallback: first takeaway narrative
            return takeaways[0].narrative if takeaways else ""

    # ----------------------------------------------------------------
    # Executive summary / key takeaway overlap removal
    # ----------------------------------------------------------------

    async def _remove_exec_summary_overlap(
        self,
        executive_summary: str,
        takeaways: List[TitledTakeaway],
        client_name: Optional[str],
        period_label: Optional[str],
    ) -> List[TitledTakeaway]:
        """
        Post-processing checkpoint that runs after the executive summary
        has been finalised.

        The executive summary is synthesised from the takeaway bullets, so
        without this step the first key takeaway (and sometimes others)
        tends to restate almost exactly the same claim as the executive
        summary. This call sends the finalised executive summary plus all
        takeaway bullets to the LLM, which rewrites or drops any bullet
        that is substantially a repeat of the executive summary's claim.

        On any failure or empty/invalid response, the original takeaways
        are returned unchanged so the pipeline is never blocked.
        """
        if not takeaways or not executive_summary:
            return takeaways

        bullets_lines: List[str] = []
        for i, t in enumerate(takeaways, 1):
            sub = f" / {t.sub_category}" if t.sub_category else ""
            bullets_lines.append(
                f"{i}. [{t.umbrella}{sub}]\n"
                f"   Title: {t.title}\n"
                f"   Narrative: {t.narrative}"
            )
        bullets_block = "\n\n".join(bullets_lines)

        user_message = RECAP_OVERLAP_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            executive_summary=executive_summary,
            bullet_count=len(takeaways),
            bullets_block=bullets_block,
        )

        try:
            raw = await self._llm.call(
                system_prompt=RECAP_OVERLAP_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=settings.token_budget("recap_overlap"),
                reasoning_effort=settings.reasoning_effort_for("recap_overlap"),
                stage="recap_overlap",
            )
            d = json.loads(raw) if isinstance(raw, str) else raw
            revised_raw = d.get("takeaways", [])
            if not revised_raw:
                logger.warning(
                    "Exec-summary overlap LLM returned empty list — keeping originals"
                )
                return takeaways

            revised: List[TitledTakeaway] = []
            for item in revised_raw:
                title     = str(item.get("title", "")).strip()
                narrative = str(item.get("narrative", "")).strip()
                umbrella  = str(item.get("umbrella", "")).strip()
                sub_cat   = item.get("sub_category") or None
                if not title or not narrative or not umbrella:
                    continue
                # Carry source IDs from the first original bullet that shares
                # this umbrella/sub_cat so provenance is not lost.
                source_ids: List[str] = []
                for orig in takeaways:
                    if orig.umbrella == umbrella and orig.sub_category == sub_cat:
                        source_ids.extend(orig.source_content_unit_ids)
                revised.append(TitledTakeaway(
                    title=title,
                    narrative=narrative,
                    umbrella=umbrella,
                    sub_category=sub_cat,
                    source_content_unit_ids=source_ids,
                ))

            if not revised:
                logger.warning(
                    "Exec-summary overlap removal produced no valid bullets — "
                    "keeping originals"
                )
                return takeaways

            logger.info(
                "Exec-summary overlap removal: %d bullets → %d bullets",
                len(takeaways), len(revised),
            )
            return revised

        except Exception as exc:
            logger.error(
                "Exec-summary overlap removal LLM failed: %s — keeping originals", exc
            )
            return takeaways


    # ----------------------------------------------------------------
    # Fact-checker
    # ----------------------------------------------------------------

    async def _fact_check_slide1(
        self,
        insights: List[StructuredInsight],
        executive_summary: str,
        takeaways: List[TitledTakeaway],
        action_items: List[ActionItemSummary],
        client_name: Optional[str],
        period_label: Optional[str],
    ) -> tuple:
        """
        Fact-check Pass 1 — Slide 1 content only.

        Verifies the executive summary, key takeaway bullets, and action items
        against the source insights. Uses a focused prompt that contains no
        country-summary content, so the LLM can concentrate entirely on
        Slide 1 accuracy.

        On any failure the original content is returned unchanged.
        """
        if not takeaways and not executive_summary:
            return executive_summary, takeaways, action_items

        # Compact source block (all insights, stripped of markup).
        # Includes a Metrics: line from structured metadata (same fields
        # used in _build_insights_block) so the fact-checker's own view of
        # "the source" contains every number the takeaway/exec-summary LLM
        # was given — otherwise the fact-checker can flag a correctly
        # sourced figure as unsupported (because it only appears in
        # structured metadata, not in the stripped prose) and strip it
        # back out of the takeaway/exec-summary text.
        source_lines: List[str] = []
        for ins in insights[:60]:
            clean = _strip_structural_markup(ins.content)
            md = ins.metadata
            metric_entries = [_format_metric_entry(m) for m in (md.metrics or md.kpis)]
            growth_bits = []
            if md.growth_value:
                growth_bits.append(f"Growth: {md.growth_value}")
            if md.baseline_value:
                growth_bits.append(f"Baseline: {md.baseline_value}")
            if md.current_value:
                growth_bits.append(f"Current: {md.current_value}")
            metrics_line = " | ".join(metric_entries + growth_bits)
            if not clean.strip() and not metrics_line:
                continue
            block = f"[Slide {ins.slide_number} | {ins.slide_title or 'no title'}]\n{clean.strip()}"
            if metrics_line:
                block += f"\nMetrics: {metrics_line}"
            source_lines.append(block)
        source_block = "\n\n".join(source_lines)

        # Serialise takeaways
        takeaway_lines: List[str] = []
        for i, t in enumerate(takeaways, 1):
            sub = f" / {t.sub_category}" if t.sub_category else ""
            takeaway_lines.append(
                f"{i}. [{t.umbrella}{sub}]\n"
                f"   Title: {t.title}\n"
                f"   Narrative: {t.narrative}"
            )
        takeaways_block = "\n\n".join(takeaway_lines)

        # Serialise action items
        action_lines: List[str] = []
        for i, ai in enumerate(action_items, 1):
            parts = [f"{i}. {ai.action}"]
            if ai.owner:            parts.append(f"   Owner: {ai.owner}")
            if ai.deadline:         parts.append(f"   Deadline: {ai.deadline}")
            if ai.geography:        parts.append(f"   Geography: {ai.geography}")
            if ai.line_of_business: parts.append(f"   LoB: {ai.line_of_business}")
            action_lines.append("\n".join(parts))
        actions_block = "\n\n".join(action_lines)

        user_message = FACT_CHECKER_SLIDE1_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            source_block=source_block,
            executive_summary=executive_summary,
            takeaway_count=len(takeaways),
            takeaways_block=takeaways_block,
            action_count=len(action_items),
            actions_block=actions_block,
        )

        try:
            raw = await self._llm.call(
                system_prompt=FACT_CHECKER_SLIDE1_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=settings.token_budget("recap_fact_check_slide1"),
                reasoning_effort=settings.reasoning_effort_for("recap_fact_check_slide1"),
                stage="recap_fact_check_slide1",
                tier=STRUCTURED_TIER,
            )
            d = json.loads(raw) if isinstance(raw, str) else raw

            # Executive summary
            checked_summary = str(d.get("executive_summary", "")).strip()
            if not checked_summary:
                checked_summary = executive_summary

            # Key takeaways
            checked_takeaways: List[TitledTakeaway] = []
            for item in d.get("takeaways", []):
                title     = str(item.get("title", "")).strip()
                narrative = str(item.get("narrative", "")).strip()
                umbrella  = str(item.get("umbrella", "")).strip()
                sub_cat   = item.get("sub_category") or None
                if not title or not narrative or not umbrella:
                    continue
                source_ids: List[str] = []
                for orig in takeaways:
                    if orig.umbrella == umbrella and orig.sub_category == sub_cat:
                        source_ids.extend(orig.source_content_unit_ids)
                checked_takeaways.append(TitledTakeaway(
                    title=title, narrative=narrative,
                    umbrella=umbrella, sub_category=sub_cat,
                    source_content_unit_ids=source_ids,
                ))
            if not checked_takeaways:
                checked_takeaways = takeaways

            # Action items
            def _str_or_none(v) -> Optional[str]:
                return None if v in (None, "null", "unknown", "") else str(v)

            def _urgency_val(v) -> str:
                try:
                    return Urgency(str(v).lower()).value
                except Exception:
                    return Urgency.UNKNOWN.value

            checked_actions: List[ActionItemSummary] = []
            for i, item in enumerate(d.get("action_items", [])):
                action_text = str(item.get("action", "")).strip()
                if not action_text:
                    continue
                orig_ai = action_items[i] if i < len(action_items) else None
                checked_actions.append(ActionItemSummary(
                    action=action_text,
                    owner=_str_or_none(item.get("owner")),
                    deadline=_str_or_none(item.get("deadline")),
                    line_of_business=_str_or_none(item.get("line_of_business")),
                    geography=_str_or_none(item.get("geography")),
                    urgency=Urgency(_urgency_val(item.get("urgency", "unknown"))),
                    source_slide_number=orig_ai.source_slide_number if orig_ai else None,
                    source_content_unit_id=orig_ai.source_content_unit_id if orig_ai else None,
                    confidence=float(item.get("confidence", orig_ai.confidence if orig_ai else 0.0)),
                ))
            if not checked_actions:
                checked_actions = action_items

            logger.info(
                "Fact-check pass 1: summary=%s, takeaways %d->%d, actions %d->%d",
                "changed" if checked_summary != executive_summary else "unchanged",
                len(takeaways), len(checked_takeaways),
                len(action_items), len(checked_actions),
            )
            return checked_summary, checked_takeaways, checked_actions

        except Exception as exc:
            logger.error("Fact-check pass 1 failed: %s — returning unchecked", exc)
            return executive_summary, takeaways, action_items

    async def _fact_check_slide2(
        self,
        insights: List[StructuredInsight],
        country_summaries: List[CountrySummary],
        client_name: Optional[str],
        period_label: Optional[str],
    ) -> List[CountrySummary]:
        """
        Fact-check Pass 2 — Slide 2 country summaries only.

        Each country summary is checked against source insights tagged to
        that country. Uses a focused prompt with no Slide 1 content, so the
        LLM can concentrate entirely on country-level accuracy.

        On any failure the original summaries are returned unchanged.
        """
        if not country_summaries:
            return country_summaries

        # Build source block grouped by country for clearer attribution.
        # Includes a Metrics: line from structured metadata so the
        # fact-checker's source view contains every number the country
        # summary LLM was given (see _build_insights_block) — otherwise it
        # can flag a correctly sourced figure as unsupported and strip it.
        from collections import defaultdict as _dd
        country_insights: dict = _dd(list)
        for ins in insights:
            for country in (ins.metadata.countries or []):
                clean = _strip_structural_markup(ins.content)
                md = ins.metadata
                metric_entries = [_format_metric_entry(m) for m in (md.metrics or md.kpis)]
                growth_bits = []
                if md.growth_value:
                    growth_bits.append(f"Growth: {md.growth_value}")
                if md.baseline_value:
                    growth_bits.append(f"Baseline: {md.baseline_value}")
                if md.current_value:
                    growth_bits.append(f"Current: {md.current_value}")
                metrics_line = " | ".join(metric_entries + growth_bits)
                if clean.strip() or metrics_line:
                    block = f"[Slide {ins.slide_number} | {ins.slide_title or 'no title'}]\n{clean.strip()}"
                    if metrics_line:
                        block += f"\nMetrics: {metrics_line}"
                    country_insights[country].append(block)

        source_parts: List[str] = []
        for cs in country_summaries:
            evidence = country_insights.get(cs.country, [])
            if evidence:
                source_parts.append(
                    f"=== {cs.country} ===\n" + "\n\n".join(evidence[:10])
                )
        source_block = "\n\n".join(source_parts) if source_parts else "(no country-tagged evidence found)"

        # Serialise country summaries
        country_lines: List[str] = []
        for i, cs in enumerate(country_summaries, 1):
            country_lines.append(f"{i}. {cs.country}:\n   {cs.summary}")
        countries_block = "\n\n".join(country_lines)

        user_message = FACT_CHECKER_SLIDE2_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            source_block=source_block,
            country_count=len(country_summaries),
            countries_block=countries_block,
        )

        try:
            raw = await self._llm.call(
                system_prompt=FACT_CHECKER_SLIDE2_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=settings.token_budget("recap_fact_check_slide2"),
                reasoning_effort=settings.reasoning_effort_for("recap_fact_check_slide2"),
                stage="recap_fact_check_slide2",
                tier=STRUCTURED_TIER,
            )
            d = json.loads(raw) if isinstance(raw, str) else raw

            checked_countries: List[CountrySummary] = []
            for item in d.get("country_summaries", []):
                country_name = str(item.get("country", "")).strip()
                summary_text = item.get("summary")
                if not country_name:
                    continue
                if not summary_text or str(summary_text).lower() in ("null", "none", ""):
                    continue   # drop empty — country had no valid evidence
                source_ids: List[str] = []
                for orig in country_summaries:
                    if orig.country == country_name:
                        source_ids.extend(orig.source_content_unit_ids)
                checked_countries.append(CountrySummary(
                    country=country_name,
                    summary=str(summary_text).strip(),
                    source_content_unit_ids=source_ids,
                ))
            if not checked_countries:
                checked_countries = country_summaries

            logger.info(
                "Fact-check pass 2: countries %d->%d",
                len(country_summaries), len(checked_countries),
            )
            return checked_countries

        except Exception as exc:
            logger.error("Fact-check pass 2 failed: %s — returning unchecked", exc)
            return country_summaries


    # ----------------------------------------------------------------
    # Action item ranking
    # ----------------------------------------------------------------

    async def _rank_action_items(
        self,
        insights: List[StructuredInsight],
        client_name: Optional[str],
        period_label: Optional[str],
        meeting_date: Optional[str] = None,
    ) -> List[ActionItemSummary]:
        """
        Collect all action items, pre-rank them, send top candidates to the
        LLM ranker, return top TOP_N_ACTIONS items.
        """
        # Collect raw action items from insights
        candidates: List[ActionItemSummary] = []
        for ins in insights:
            if not ins.action_item.is_action_item:
                continue
            ai = ins.action_item
            item = ActionItemSummary(
                action=ai.action_description or ins.content[:160],
                owner=ai.owner,
                deadline=ai.deadline,
                line_of_business=ai.line_of_business,
                geography=ai.geography,
                urgency=ai.urgency,
                source_slide_number=ins.slide_number,
                source_content_unit_id=ins.content_unit_id,
                confidence=ai.confidence,
            )
            item.priority_score = _priority_score(item)
            candidates.append(item)

        if not candidates:
            return []

        # Pre-sort by composite score desc, cap before sending to LLM
        candidates.sort(key=lambda a: -a.priority_score)
        top_candidates = candidates[:MAX_ACTION_CANDIDATES]

        # If we already have ≤ TOP_N_ACTIONS, skip the LLM ranker
        if len(top_candidates) <= TOP_N_ACTIONS:
            return self._dedup_action_items(top_candidates[:TOP_N_ACTIONS])

        # Build actions block for LLM
        actions_block = self._build_actions_block(top_candidates)
        user_message = RECAP_ACTION_RANKER_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            meeting_date=meeting_date or "(not provided)",
            action_count=len(top_candidates),
            actions_block=actions_block,
        )

        try:
            raw = await self._llm.call(
                system_prompt=RECAP_ACTION_RANKER_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=settings.token_budget("recap_action_ranker"),
                reasoning_effort=settings.reasoning_effort_for("recap_action_ranker"),
                stage="recap_action_ranker",
                tier=STRUCTURED_TIER,
            )
            d = json.loads(raw) if isinstance(raw, str) else raw
            ranked_raw = d.get("ranked_action_items", [])
            ranked: List[ActionItemSummary] = []
            for ai in ranked_raw[:TOP_N_ACTIONS]:
                try:
                    urgency_val = ai.get("urgency", "unknown")
                    try:
                        urgency = Urgency(urgency_val)
                    except Exception:
                        urgency = Urgency.UNKNOWN
                    item = ActionItemSummary(
                        action=str(ai.get("action", "")),
                        owner=ai.get("owner") or None,
                        deadline=ai.get("deadline") or None,
                        line_of_business=ai.get("line_of_business") or None,
                        geography=ai.get("geography") or None,
                        urgency=urgency,
                        source_slide_number=ai.get("source_slide_number"),
                        source_content_unit_id=ai.get("source_content_unit_id") or None,
                        confidence=float(ai.get("confidence", 0.0)),
                    )
                    item.priority_score = _priority_score(item)
                    ranked.append(item)
                except Exception as exc:
                    logger.debug("Skipping malformed ranked action item: %s", exc)
            if ranked:
                return self._dedup_action_items(ranked)
        except Exception as exc:
            logger.error("Action ranker LLM failed: %s", exc)

        # Fallback: return pre-sorted top N (deduped)
        return self._dedup_action_items(top_candidates[:TOP_N_ACTIONS])

    # ----------------------------------------------------------------
    # Action item deduplication (pure-Python, no LLM)
    # ----------------------------------------------------------------

    @staticmethod
    def _dedup_action_items(
        items: List[ActionItemSummary],
    ) -> List[ActionItemSummary]:
        """
        Remove near-duplicate action items using token-overlap similarity.

        Two items are considered duplicates when their normalised action
        texts share ≥ 60% of their word tokens (Jaccard similarity).
        The higher-priority item (earlier in the list) is kept; the
        lower-priority duplicate is dropped.
        """
        def _normalise(text: str) -> set:
            """Lowercase, strip punctuation, return word token set."""
            tokens = _re.sub(r"[^\w\s]", " ", text.lower()).split()
            # Remove very common stop words so they don't inflate similarity
            stops = {"to", "the", "a", "an", "and", "or", "in", "for",
                     "of", "with", "on", "at", "by", "is", "are", "be"}
            return {t for t in tokens if t not in stops and len(t) > 1}

        def _jaccard(a: set, b: set) -> float:
            if not a or not b:
                return 0.0
            return len(a & b) / len(a | b)

        kept: List[ActionItemSummary] = []
        for item in items:
            tokens_item = _normalise(item.action)
            is_dup = False
            for existing in kept:
                tokens_existing = _normalise(existing.action)
                if _jaccard(tokens_item, tokens_existing) >= 0.60:
                    logger.info(
                        "Action dedup: dropped near-duplicate\n  kept: %s\n  dropped: %s",
                        existing.action, item.action,
                    )
                    is_dup = True
                    break
            if not is_dup:
                kept.append(item)
        return kept

    # ----------------------------------------------------------------
    # Prompt construction helpers
    # ----------------------------------------------------------------

    async def _generate_country_summaries(
        self,
        insights: List[StructuredInsight],
        client_name: Optional[str],
        period_label: Optional[str],
    ) -> List[CountrySummary]:
        """
        Group insights by country tag and produce an LLM summary per
        country, sized proportionally to how much that country is actually
        discussed in the deck (see `_country_target_sentences`) — a country
        with a whole slide devoted to it gets 2-3 sentences, a country with
        only light, scattered coverage gets 1. Countries mentioned fewer
        than MIN_MENTIONS_TO_INCLUDE times are dropped entirely rather than
        padded onto the slide. Only runs when 2 or more qualifying countries
        remain; returns an empty list otherwise.

        The slide has limited space, so rather than listing every country
        mentioned anywhere in the deck, countries are ranked by importance
        (`_country_importance_score` — volume of substantive information
        plus breadth of tags/topics discussed for that country) and only
        the top MAX_COUNTRIES_ON_SLIDE are summarised and rendered.
        """
        # Build country → insights map (normalise country name to title-case)
        country_map: Dict[str, List[StructuredInsight]] = defaultdict(list)
        for ins in insights:
            for country in ins.metadata.countries:
                normalised = country.strip().title()
                if normalised:
                    country_map[normalised].append(ins)

        # Only keep countries that clear the minimum substantive-mention bar.
        # A country appearing only in geography lists, structural slides, or
        # a single buried point in a large tabular deck (e.g. India mentioned
        # once) has no real narrative and is dropped rather than padded onto
        # the slide.
        country_map = {
            c: ins_list
            for c, ins_list in country_map.items()
            if _country_mention_count(ins_list) >= MIN_MENTIONS_TO_INCLUDE
        }

        if len(country_map) < 2:
            logger.info(
                "Country summaries skipped: only %d unique country/countries found",
                len(country_map),
            )
            return []

        # Rank all qualifying countries by importance score, descending.
        # Ties broken alphabetically for deterministic output.
        ranked_countries = sorted(
            country_map.keys(),
            key=lambda c: (-_country_importance_score(country_map[c]), c),
        )

        if len(ranked_countries) > MAX_COUNTRIES_ON_SLIDE:
            logger.info(
                "Country ranking: %d unique countries found — keeping top %d "
                "by importance score. Dropped: %s",
                len(ranked_countries), MAX_COUNTRIES_ON_SLIDE,
                ranked_countries[MAX_COUNTRIES_ON_SLIDE:],
            )
        unique_countries = ranked_countries[:MAX_COUNTRIES_ON_SLIDE]

        logger.info(
            "Generating country summaries for %d countries (ranked by importance): %s",
            len(unique_countries), unique_countries,
        )

        # Run all countries concurrently. Each country's summary length is
        # sized proportionally to how much it is actually discussed in the
        # deck (see `_country_target_sentences`).
        tasks = [
            self._summarise_one_country(
                country, country_map[country], client_name, period_label,
                target_sentences=_country_target_sentences(country_map[country]),
            )
            for country in unique_countries
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        summaries: List[CountrySummary] = []
        for country, result in zip(unique_countries, results):
            if isinstance(result, Exception):
                logger.error("Country summary failed for %s: %s", country, result)
            elif result is not None:
                summaries.append(result)

        return summaries

    async def _summarise_one_country(
        self,
        country: str,
        country_insights: List[StructuredInsight],
        client_name: Optional[str],
        period_label: Optional[str],
        target_sentences: int = 2,
    ) -> Optional[CountrySummary]:
        """
        Call the LLM once to produce a summary for one country, sized to
        `target_sentences` (1-3) based on how much the country is actually
        discussed in the deck.
        """
        # Cap insights sent to LLM
        top_insights = sorted(
            country_insights,
            key=lambda i: -i.metadata.overall_confidence,
        )[:MAX_INSIGHTS_PER_GROUP]

        insights_block = self._build_insights_block(top_insights)
        sentence_word = {1: "ONE sentence", 2: "TWO sentences", 3: "THREE sentences"}.get(
            target_sentences, "TWO sentences"
        )
        user_message = COUNTRY_SUMMARY_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            country=country,
            insight_count=len(top_insights),
            insights_block=insights_block,
            target_sentence_count=target_sentences,
            target_sentence_word=sentence_word,
        )

        try:
            raw = await self._llm.call(
                system_prompt=COUNTRY_SUMMARY_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=settings.token_budget("recap_country_summary_per_sentence") * target_sentences,
                reasoning_effort=settings.reasoning_effort_for("recap_country_summary_per_sentence"),
                stage="recap_country_summary_per_sentence",
            )
            d = json.loads(raw) if isinstance(raw, str) else raw
            summary_text = str(d.get("summary", "") or "").strip()
            # LLM may return the literal string "null" — treat as no summary
            if not summary_text or summary_text.lower() == "null":
                return None
            return CountrySummary(
                country=country,
                summary=summary_text,
                source_content_unit_ids=d.get("source_content_unit_ids", [
                    i.content_unit_id for i in top_insights
                ]),
            )
        except Exception as exc:
            logger.error("Country summary LLM failed for %s: %s", country, exc)
            # Do not fall back to raw content — if the LLM fails we skip
            # the country entirely rather than show structural/list content.
            return None

    # ----------------------------------------------------------------
    # Prompt construction helpers
    # ----------------------------------------------------------------

    def _build_insights_block(self, insights: List[StructuredInsight]) -> str:
        """Serialise insights into a compact text block for the LLM.

        Raw [TABLE DATA] / [CHART DATA] block markers and table-row lines are
        stripped from the content before serialisation — the LLM receives
        clean prose with any inline numbers preserved.

        A dedicated "Metrics:" line is also appended from the structured
        metadata (metadata.metrics / growth_value / baseline_value /
        current_value) captured during enrichment. This is a deliberate
        second, independent path for numeric data reaching the LLM: even
        if a figure did not survive the regex-based stripping of `content`
        above, the number is still explicitly present here, because it was
        already extracted into structured fields by the enrichment stage
        and should never be silently dropped before reaching the prompt.
        """
        lines: List[str] = []
        for ins in insights:
            md = ins.metadata
            action_flag = (
                f"[ACTION:{ins.action_item.urgency.value.upper()}]"
                if ins.action_item.is_action_item else ""
            )
            clean_content = _strip_structural_markup(ins.content)

            # Structured numeric metrics — rendered from metadata.metrics
            # (falls back to metadata.kpis if metrics is empty) plus any
            # growth/baseline/current values, so figures already captured
            # during enrichment always reach the LLM regardless of what
            # survived the markup-stripping regexes above.
            metric_entries = [_format_metric_entry(m) for m in (md.metrics or md.kpis)]
            growth_bits = []
            if md.growth_value:
                gt = f" ({md.growth_type.value})" if md.growth_type else ""
                growth_bits.append(f"Growth{gt}: {md.growth_value}")
            if md.baseline_value:
                growth_bits.append(f"Baseline: {md.baseline_value}")
            if md.current_value:
                growth_bits.append(f"Current: {md.current_value}")
            metrics_line = " | ".join(metric_entries + growth_bits)

            lines.append(
                f"[{ins.content_unit_id}] Slide {ins.slide_number}"
                f" | {ins.slide_title or ins.section or ''} {action_flag}\n"
                f"  Content: {clean_content}\n"
                f"  Metrics: {metrics_line or '-'}\n"
                f"  LOB: {', '.join(md.lines_of_business) or '-'} | "
                f"Region: {', '.join(md.regions) or '-'} | "
                f"KPIs: {', '.join(md.kpis) or '-'} | "
                f"Direction: {md.performance_direction.value} | "
                f"Confidence: {md.overall_confidence:.2f}"
            )
        return "\n\n".join(lines)

    def _build_actions_block(self, items: List[ActionItemSummary]) -> str:
        """Serialise action item candidates for the ranker LLM."""
        lines: List[str] = []
        for i, ai in enumerate(items, 1):
            parts = [f"{i}. [{ai.urgency.value.upper()}] {ai.action}"]
            if ai.owner:
                parts.append(f"   Owner: {ai.owner}")
            if ai.deadline:
                parts.append(f"   Deadline: {ai.deadline}")
            if ai.line_of_business:
                parts.append(f"   LOB: {ai.line_of_business}")
            if ai.geography:
                parts.append(f"   Geography: {ai.geography}")
            parts.append(
                f"   Slide: {ai.source_slide_number or '?'} | "
                f"Confidence: {ai.confidence:.2f} | "
                f"Priority score: {ai.priority_score:.2f}"
            )
            lines.append("\n".join(parts))
        return "\n\n".join(lines)

    # ----------------------------------------------------------------
    # Deterministic title neutralisation safety net
    # ----------------------------------------------------------------

    # Aliases that are also common, generic English words. Matching these
    # inside a TITLE produces false positives (e.g. "Specialty and
    # Facilities Expansion" is a neutral topic label, not a title that
    # improperly singles out the "Facilities / lineslips" LoB just because
    # it contains the word "facilities"). Excluded from title-side matching
    # only; narrative-side matching is unaffected since narrative text is
    # long-form prose where these words are far less likely to appear as a
    # false LoB signal in isolation.
    _GENERIC_TITLE_ALIAS_DENYLIST = {
        "facilities", "programs", "life", "auto", "motor", "captives",
        "affinity", "crime", "real estate", "wellbeing",
    }

    @staticmethod
    @lru_cache(maxsize=1)
    def _lob_match_patterns():
        """
        Build (compiled_pattern, canonical_name, alias_lower) tuples for
        every known LoB alias and canonical name from assets/config.yaml,
        longest alias first so multi-word aliases match before shorter
        overlapping ones. Aliases under 3 characters are skipped to avoid
        false positives (e.g. matching "PI" inside an unrelated word).
        """
        index = settings.lob_alias_index
        pairs = sorted(index.items(), key=lambda kv: -len(kv[0]))
        compiled = []
        for alias_lower, canonical in pairs:
            if len(alias_lower) < 3:
                continue
            pattern = _re.compile(
                r"(?<![A-Za-z0-9])" + _re.escape(alias_lower) + r"(?![A-Za-z0-9])",
                _re.IGNORECASE,
            )
            compiled.append((pattern, canonical, alias_lower))
        return compiled

    @classmethod
    def _find_lob_mentions(cls, text: str, *, is_title: bool = False) -> set:
        """
        Return the set of canonical LoB names mentioned in `text`.

        When `is_title` is True, generic-English-word aliases (see
        `_GENERIC_TITLE_ALIAS_DENYLIST`) are excluded so a short title
        containing an ordinary word like "Facilities" is not mistaken for
        a LoB name.
        """
        if not text:
            return set()
        found = set()
        for pattern, canonical, alias_lower in cls._lob_match_patterns():
            if is_title and alias_lower in cls._GENERIC_TITLE_ALIAS_DENYLIST:
                continue
            if pattern.search(text):
                found.add(canonical)
        return found

    @classmethod
    def _neutralise_takeaway_titles(
        cls, takeaways: List[TitledTakeaway]
    ) -> List[TitledTakeaway]:
        """
        Deterministic safety net that catches titles naming a single line
        of business when the underlying narrative actually spans multiple
        LoBs (e.g. "Property-Led Portfolio Shift" over a narrative that
        also covers Marine, FINPRO, and Cyber).

        The generation prompt already instructs the LLM not to do this,
        but LLM compliance is not guaranteed, so this pass re-checks every
        title against the canonical LoB list from assets/config.yaml and
        falls back to the neutral sub-category label whenever a title
        singles out one LoB while the narrative names others.

        A title that names the ONLY LoB discussed in its own narrative is
        left untouched -- that is explicitly allowed by the generation
        prompt for genuinely single-LoB bullets.
        """
        result: List[TitledTakeaway] = []
        for t in takeaways:
            title_lobs = cls._find_lob_mentions(t.title, is_title=True)
            if not title_lobs:
                result.append(t)
                continue

            narrative_lobs = cls._find_lob_mentions(t.narrative)
            all_lobs = title_lobs | narrative_lobs
            if len(all_lobs) <= 1:
                # Title names the only LoB discussed anywhere in this
                # bullet -- fine per the generation prompt.
                result.append(t)
                continue

            neutral_title = _sub_category_label(t.umbrella, t.sub_category)
            logger.info(
                "Title neutralised (title named %s, narrative also covers "
                "%d other LoB(s)): %r -> %r",
                ", ".join(sorted(title_lobs)),
                len(all_lobs) - len(title_lobs),
                t.title, neutral_title,
            )
            result.append(t.model_copy(update={"title": neutral_title}))
        return result

    # ----------------------------------------------------------------
    # Fallbacks
    # ----------------------------------------------------------------

    def _fallback_recap(
        self,
        deck_id: str,
        client_name: Optional[str],
        period_label: Optional[str],
        insights: List[StructuredInsight],
    ) -> RecapOutput:
        """Rule-based fallback recap when LLM calls fail."""
        # Build simple titled takeaways from umbrella groups
        _sub_cat_attr = {
            "performance_and_position":      "performance_sub_category",
            "opportunity_and_growth":        "growth_sub_category",
            "market_and_external_context":   "market_sub_category",
            "relationship_and_collaboration": "relationship_sub_category",
        }
        seen: set = set()
        key_takeaways: List[TitledTakeaway] = []
        for ins in sorted(insights, key=lambda i: -i.metadata.overall_confidence):
            for umbrella_key in ins.umbrella_labels:
                sub_cat_attr = _sub_cat_attr.get(umbrella_key)
                sub_cat_key = None
                if sub_cat_attr:
                    sc = getattr(ins.classification, sub_cat_attr, None)
                    if sc and sc.sub_category:
                        sub_cat_key = sc.sub_category
                group_key = (umbrella_key, sub_cat_key)
                if group_key in seen:
                    continue
                seen.add(group_key)
                label = _sub_category_label(umbrella_key, sub_cat_key)
                key_takeaways.append(TitledTakeaway(
                    title=label,
                    narrative=_strip_structural_markup(ins.content)[:500],
                    umbrella=umbrella_key,
                    sub_category=sub_cat_key,
                    source_content_unit_ids=[ins.content_unit_id],
                ))

        # Action items: pre-sort and cap
        action_items: List[ActionItemSummary] = []
        for ins in insights:
            if ins.action_item.is_action_item:
                ai = ins.action_item
                item = ActionItemSummary(
                    action=ai.action_description or ins.content[:160],
                    owner=ai.owner,
                    deadline=ai.deadline,
                    line_of_business=ai.line_of_business,
                    geography=ai.geography,
                    urgency=ai.urgency,
                    source_slide_number=ins.slide_number,
                    source_content_unit_id=ins.content_unit_id,
                    confidence=ai.confidence,
                )
                item.priority_score = _priority_score(item)
                action_items.append(item)
        action_items.sort(key=lambda a: -a.priority_score)
        action_items = action_items[:TOP_N_ACTIONS]

        return RecapOutput(
            deck_id=deck_id,
            period_label=period_label,
            client_name=client_name,
            executive_summary=(
                "(Recap generated from structured insights — LLM synthesis unavailable.)"
            ),
            key_takeaways=key_takeaways,
            action_items=action_items,
            overall_confidence=0.0,
            contributing_insight_ids=[i.insight_id for i in insights],
        )

    @staticmethod
    def _empty_recap(
        deck_id: str,
        client_name: Optional[str],
        period_label: Optional[str],
    ) -> RecapOutput:
        return RecapOutput(
            deck_id=deck_id,
            period_label=period_label,
            client_name=client_name,
            executive_summary="No insights available for this deck.",
            key_takeaways=[],
            action_items=[],
            overall_confidence=0.0,
            contributing_insight_ids=[],
        )
