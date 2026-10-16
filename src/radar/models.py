"""Typed objects passed between pipeline stages."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RawItem(BaseModel):
    """One collected item, before dedupe."""

    url: str
    title: str
    source: str  # arxiv | hf_papers | hn | github | rss | watchlist
    published_at: datetime | None = None
    snippet: str = ""
    popularity: int = 0
    origin: str = ""  # feed/query that produced it (for debugging)
    is_watchlist: bool = False


class Candidate(BaseModel):
    """An item inside the pipeline with scores accumulating as it moves along."""

    id: str  # items.id (uuid) once persisted
    url: str
    title: str
    source: str
    published_at: datetime | None = None
    snippet: str = ""
    popularity: int = 0
    is_watchlist: bool = False
    embedding: list[float] = Field(default_factory=list, repr=False)

    # filter stage
    filter_score: float = 0.0
    filter_parts: dict[str, float] = Field(default_factory=dict)
    nearest_topic: str = ""

    # judge stage
    best_topic: str = ""
    relevance: float | None = None
    novelty: float | None = None
    actionability: float | None = None
    rationale: str = ""
    headline: str = ""
    summary: str = ""
    example: str = ""
    why_it_matters: str = ""
    judged: bool = False
    final_rank: float = 0.0

    # digest stage
    section: str = ""
    position: int = 0


class JudgeItem(BaseModel):
    """What the LLM returns per item. `n` echoes the number we gave it in the prompt."""

    n: int
    best_topic: str
    relevance: float = Field(ge=0, le=10)
    novelty: float = Field(ge=0, le=10)
    actionability: float = Field(ge=0, le=10)
    rationale: str
    headline: str
    summary: str
    example: str
    why_it_matters: str


class JudgeBatch(BaseModel):
    items: list[JudgeItem]
