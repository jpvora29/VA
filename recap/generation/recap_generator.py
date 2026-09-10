"""
recap/recap_generator.py

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
from typing import Dict, List, Optional, Tuple

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
    RECAP_OVERLAP_SYSTEM_PROMPT,
    RECAP_OVERLAP_USER_TEMPLATE,
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
MAX_INSIGHTS_PER_GROUP = 17
# Maximum total insights sent to the action ranker
MAX_ACTION_CANDIDATES = 20
# Number of action items to keep in the final output
TOP_N_ACTIONS = 4
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
# Labelled table rows:  "Row 1: ...", "Headers: ...", "Table (N rows, ...)"
# Headers: is matched with .* so the ENTIRE line is stripped, not just the label.
_RE_TABLE_ROW = _re.compile(
    r"^(?:Table\s*\(\d+\s*rows[^)]*\)|Headers?:.*|Row\s+\d+:)[^\n]*$", _re.M
)
# Pipe-delimited lines — table rows serialised as "cell | cell | cell".
# A line with ANY pipe character is structurally a table row, not prose.
_RE_PIPE_ROW = _re.compile(
    r"^[^\n]*\|[^\n]*$", _re.M
)
# Raw data cell lines — lines that contain NO alphabetic word ≥ 4 chars
# (i.e. pure numbers, percentages, codes, short labels like "SoW2.9%").
# These are bare table cell values that leaked through without Row/Header labels.
_RE_DATA_CELL = _re.compile(
    # Strip a line if it does NOT contain 3+ consecutive pure-alpha words.
    # "Marsh Book % Change+10.2%" → only 2 consecutive pure-alpha words → stripped.
    # "UK Global posted strong GWP growth" → 4+ consecutive → kept.
    r"^(?!(?:.*?\b[A-Za-z]+\b\s+){2}[A-Za-z]+\b)[^\n]{1,120}$",
    _re.M
)

# Minimum prose characters remaining after stripping structural markup
# for an insight to contribute to key-takeaway generation.
_MIN_PROSE_CHARS = 40

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
    # Strip pipe-delimited table rows (cell | cell | cell)
    text = _RE_PIPE_ROW.sub("", text)
    # Strip lines that are pure data cells (no word ≥ 4 chars = no prose)
    text = _RE_DATA_CELL.sub("", text)
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
        # runs on the prose tier by default; the two mechanical passes below
        # (dedup, action ranking) ask for the structured tier per call.
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
        min_confidence: float = 0.0,
    ) -> RecapOutput:
        """
        Generate a recap for a specific deck.
        """
        insights = store.query(deck_id=deck_id, min_confidence=min_confidence)

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
                                    client_name, period_label)
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
            exec_summary_source_takeaways, client_name, period_label
        )

        # 3b. Deduplication checkpoint — merge or drop bullets that carry the
        #     same core commercial claim before anything is passed downstream.
        #     Runs AFTER exec summary generation so the merge step cannot
        #     contaminate the umbrella-pure source material used above.
        key_takeaways = await self._dedup_takeaways(
            key_takeaways, client_name, period_label
        )
        logger.info("Takeaways after dedup: %d", len(key_takeaways))

        # 4b. Remove overlap between the executive summary and the key
        #     takeaways — the point used for the executive summary should
        #     not also appear as (essentially) the first key takeaway.
        key_takeaways = await self._remove_exec_summary_overlap(
            executive_summary, key_takeaways, client_name, period_label
        )
        logger.info("Takeaways after exec-summary overlap removal: %d", len(key_takeaways))

        # 5. Rank and cap action items
        action_items = await self._rank_action_items(
            insights, client_name, period_label
        )

        # 6. Per-country summaries (only when 2+ unique countries present)
        country_summaries = await self._generate_country_summaries(
            insights, client_name, period_label
        )

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
    ) -> Optional[TitledTakeaway]:
        """Call the LLM once to produce a titled bullet for one group."""
        umbrella_label = UMBRELLA_DEFINITIONS[umbrella_key]["label"]
        sub_cat_label = _sub_category_label(umbrella_key, sub_cat_key)
        insights_block = self._build_insights_block(group_insights)

        user_message = RECAP_GENERATION_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            umbrella_label=umbrella_label,
            sub_category_label=sub_cat_label,
            insight_count=len(group_insights),
            insights_block=insights_block,
        )

        try:
            raw = await self._llm.call(
                system_prompt=RECAP_GENERATION_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=600,
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

    async def _dedup_takeaways(
        self,
        takeaways: List[TitledTakeaway],
        client_name: Optional[str],
        period_label: Optional[str],
    ) -> List[TitledTakeaway]:
        """
        Post-generation deduplication checkpoint.

        Sends the full list of drafted takeaways to a separate LLM call
        whose sole job is to identify bullets that carry the same core
        commercial claim and merge them.  The original list is returned
        unchanged on any failure so the pipeline is never blocked.
        """
        if len(takeaways) <= 1:
            return takeaways

        # Serialise bullets for the LLM — numbered for easy reference
        bullets_lines: List[str] = []
        for i, t in enumerate(takeaways, 1):
            sub = f" / {t.sub_category}" if t.sub_category else ""
            bullets_lines.append(
                f"{i}. [{t.umbrella}{sub}]\n"
                f"   Title: {t.title}\n"
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
                tier=STRUCTURED_TIER,
                max_completion_tokens=2048,
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

    # ----------------------------------------------------------------
    # Executive summary generation
    # ----------------------------------------------------------------

    # Sub-categories under performance_and_position that must NOT feed the
    # executive summary because they carry LoB-specific or segment-specific
    # detail rather than umbrella-level commercial position.
    _EXEC_SUMMARY_EXCLUDED_SUB_CATEGORIES = {
        "line_of_business_performance",
    }

    def _filter_exec_summary_source(
        self, takeaways: List[TitledTakeaway]
    ) -> List[TitledTakeaway]:
        """
        Restrict the executive summary's source material to the
        `performance_and_position` umbrella only.

        No takeaway from any other umbrella (Opportunity & Growth,
        Market & External Context, Relationship & Collaboration) may
        contribute to the executive summary. Within `performance_and_position`,
        LoB-specific sub-categories (currently `line_of_business_performance`)
        are also excluded, since the executive summary must stay at the
        umbrella/overall-position level, not drill into individual lines of
        business or segments.
        """
        filtered = [
            t for t in takeaways
            if t.umbrella == "performance_and_position"
            and t.sub_category not in self._EXEC_SUMMARY_EXCLUDED_SUB_CATEGORIES
        ]
        logger.info(
            "Executive summary source filter: %d performance_and_position "
            "takeaways (of %d total) after excluding LoB-specific sub-categories",
            len(filtered), len(takeaways),
        )
        return filtered

    async def _generate_exec_summary(
        self,
        takeaways: List[TitledTakeaway],
        client_name: Optional[str],
        period_label: Optional[str],
    ) -> str:
        if not takeaways:
            return "No insights available for this review period."

        takeaways_block = "\n".join(
            f"• {t.title}: {t.narrative}" for t in takeaways
        )
        user_message = RECAP_EXEC_SUMMARY_USER_TEMPLATE.format(
            client_name=client_name or "the client",
            period_label=period_label or "",
            takeaways_block=takeaways_block,
        )
        try:
            raw = await self._llm.call(
                system_prompt=RECAP_EXEC_SUMMARY_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=128,
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
                max_completion_tokens=2048,
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
    # Action item ranking
    # ----------------------------------------------------------------

    async def _rank_action_items(
        self,
        insights: List[StructuredInsight],
        client_name: Optional[str],
        period_label: Optional[str],
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
            action_count=len(top_candidates),
            actions_block=actions_block,
        )

        try:
            raw = await self._llm.call(
                system_prompt=RECAP_ACTION_RANKER_SYSTEM_PROMPT,
                user_message=user_message,
                tier=STRUCTURED_TIER,
                max_completion_tokens=512,
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
                max_completion_tokens=120 * target_sentences,
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
        """
        lines: List[str] = []
        for ins in insights:
            md = ins.metadata
            action_flag = (
                f"[ACTION:{ins.action_item.urgency.value.upper()}]"
                if ins.action_item.is_action_item else ""
            )
            clean_content = _strip_structural_markup(ins.content)
            lines.append(
                f"[{ins.content_unit_id}] Slide {ins.slide_number}"
                f" | {ins.slide_title or ins.section or ''} {action_flag}\n"
                f"  Content: {clean_content}\n"
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
