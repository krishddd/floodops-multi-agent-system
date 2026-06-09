"""Models for agent memory (historical-event recall)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """One remembered event with its embedding vector."""

    record_id: str
    agent_id: str
    summary: str
    vector: list[float] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class RecalledEvent(BaseModel):
    """A recalled historical analogue with its similarity score."""

    summary: str
    similarity: float
    created_at: datetime
    metadata: dict = Field(default_factory=dict)
