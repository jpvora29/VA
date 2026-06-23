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
