"""Pydantic IO schemas for the Studio AI agents (LangChain structured output)."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


# ── Story agent ──────────────────────────────────────────────────────────────


class SlideStory(BaseModel):
    idx: int = Field(description="0-based index of the slide being rewritten")
    action_title: str = Field(description="The takeaway-sentence title (no invented numbers)")
    takeaways: List[str] = Field(default_factory=list, description="2-4 short key-message bullets")
    recommendation: str = Field(default="", description="One imperative recommendation")


class DeckStory(BaseModel):
    thesis: str = Field(default="", description="One-sentence executive thesis for the deck")
    slides: List[SlideStory] = Field(default_factory=list)


# ── Layout agent ─────────────────────────────────────────────────────────────


class LayoutChoice(BaseModel):
    idx: int
    archetype: str = Field(description="An archetype id from the provided catalog")


class DeckLayout(BaseModel):
    choices: List[LayoutChoice] = Field(default_factory=list)


# ── Slide-selection agent ────────────────────────────────────────────────────


class SectionOrder(BaseModel):
    sections: List[str] = Field(
        default_factory=list,
        description="Ordered agenda-section ids to INCLUDE, most important first",
    )


# ── QA / critic agent ────────────────────────────────────────────────────────


class CriticIssue(BaseModel):
    idx: int = Field(default=-1, description="Slide index the issue is on (-1 = deck-level)")
    severity: str = Field(default="warn", description="info | warn | error")
    category: str = Field(default="quality", description="title|evidence|overflow|contradiction|duplicate")
    message: str


class CriticReport(BaseModel):
    issues: List[CriticIssue] = Field(default_factory=list)


# ── Commentary writer + verifier ─────────────────────────────────────────────


class CommentaryBullet(BaseModel):
    text: str = Field(description="One complete sentence, ending in a full stop")
    fact_ids: List[str] = Field(
        default_factory=list,
        description="Ids of the evidence facts this sentence's figures and claims come from",
    )


class CommentaryColumn(BaseModel):
    bullets: List[CommentaryBullet] = Field(default_factory=list)


class CommentaryVerdict(BaseModel):
    keep: bool = Field(description="True to keep the sentence, False to drop it")
    reason: str = Field(default="", description="Why it is dropped; empty when kept")


class CommentaryVerdicts(BaseModel):
    verdicts: List[CommentaryVerdict] = Field(
        default_factory=list, description="One verdict per sentence, in the order given"
    )


# ── Section-level commentary (one call per sub-deck) ─────────────────────────
#
# The per-column schema above writes ONE textbox per request. A six-product QBR has 27 of
# them, and 27 author calls plus 27 verifier calls is the reason a build took hours. These
# carry a whole sub-deck's columns in a single request and a single answer.
#
# There is deliberately no `headline` field. The plan's draft contract had one, and the
# shipped templates already print the column's header on the slide — a headline the fill
# layer must discard is tokens spent on nothing, and a slot nobody renders is where a
# "PowerPoint rewrites the commentary" habit starts.


class CommentarySection(BaseModel):
    """One commentary field: its sentences, the action it lands on, and its risk read."""

    field_id: str = Field(description="The field id EXACTLY as given in the request")
    bullets: List[CommentaryBullet] = Field(default_factory=list)
    action: str = Field(
        default="",
        description="One specific leadership action, naming a segment and a figure. Empty "
                    "unless the column is asked for one.",
    )
    risk_flag: str = Field(
        default="none", description="none | watch | concern — the risk this column carries"
    )


class CommentarySections(BaseModel):
    """Every field in one sub-deck, answered in one call."""

    sections: List[CommentarySection] = Field(default_factory=list)
