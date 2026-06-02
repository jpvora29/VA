"""Pydantic schema for the fallback (out-of-scope) message."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FallbackMessage(BaseModel):
    msg: str = Field(description="Not relevant or out of scope question message")
