"""Cheap filter: hybrid score (cosine to topic vectors + keywords + recency + popularity)
that narrows ~hundreds of candidates to the top N for the LLM judge."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

import numpy as np

from radar.config import AppConfig, Topic
from radar.embed import embed_texts
from radar.models import Candidate

# bge-small cosine between related texts sits roughly in 0.4-0.8; rescale to 0..1.
COS_LO, COS_HI = 0.35, 0.80
POP_CAP = 200
WATCHLIST_KEEP = 6


def build_topic_vectors(config: AppConfig) -> dict[str, np.ndarray]:
    """One unit vector per topic: mean of the description and any anchor texts."""
    out = {}
    for t in config.topics:
        texts = [f"{t.description.strip()} Keywords: {', '.join(t.keywords)}"] + list(t.anchors)
        vecs = embed_texts(texts, config.models.embedding)
        mean = vecs.mean(axis=0)
        out[t.name] = mean / max(float(np.linalg.norm(mean)), 1e-12)
    return out


def keyword_score(text_title: str, text_body: str, keywords: list[str]) -> float:
    """0..1. Title hits count double; saturates after a handful of hits."""
    raw = 0
    for k in keywords:
        pat = re.compile(rf"\b{re.escape(k)}\b" if len(k) <= 4 else re.escape(k), re.IGNORECASE)
        raw += 2 * bool(pat.search(text_title)) + bool(pat.search(text_body))
    return min(1.0, raw / 4)


def recency_score(published: datetime | None, now: datetime, halflife_days: float) -> float:
    if published is None:
        return 0.3
    age = max((now - published).total_seconds() / 86400, 0.0)
    return math.exp(-math.log(2) * age / halflife_days)


def popularity_score(pop: int) -> float:
    return min(1.0, math.log1p(max(pop, 0)) / math.log1p(POP_CAP))


def score_candidates(
    cands: list[Candidate],
    config: AppConfig,
    topic_vecs: dict[str, np.ndarray],
    *,
    now: datetime | None = None,
    feedback: dict[str, float] | None = None,
) -> list[Candidate]:
    """Compute filter_score for every candidate (in place) and drop stale ones."""
    now = now or datetime.now(UTC)
    cfg = config.filter
    w = cfg.weights
    topics: dict[str, Topic] = {t.name: t for t in config.topics}
    names = list(topic_vecs)
    mat = np.stack([topic_vecs[n] for n in names])
    weights = np.array([topics[n].weight for n in names])
    kept = []
    for c in cands:
        if c.published_at is not None:
            age_days = (now - c.published_at).total_seconds() / 86400
            limit = cfg.watchlist_window_days if c.is_watchlist else cfg.max_age_days
            if age_days > limit:
                continue
        sims = mat @ np.asarray(c.embedding, dtype=np.float32) * weights
        j = int(np.argmax(sims))
        cos = min(1.0, max(0.0, (float(sims[j]) - COS_LO) / (COS_HI - COS_LO)))
        kw = max(
            keyword_score(c.title, c.snippet, topics[n].keywords) for n in names
        )
        parts = {
            "cosine": cos,
            "keyword": kw,
            "recency": recency_score(c.published_at, now, cfg.recency_halflife_days),
            "popularity": popularity_score(c.popularity),
            "feedback": (feedback or {}).get(c.id, 0.0),
        }
        c.filter_parts = {k: round(v, 4) for k, v in parts.items()}
        c.filter_score = round(sum(getattr(w, k) * v for k, v in parts.items()), 4)
        c.nearest_topic = names[j]
        kept.append(c)
    return kept


def select_top(cands: list[Candidate], config: AppConfig) -> list[Candidate]:
    """Top N regular items plus the best few watchlist releases (their own digest section)."""
    regular = sorted((c for c in cands if not c.is_watchlist), key=lambda c: -c.filter_score)
    watch = sorted((c for c in cands if c.is_watchlist), key=lambda c: -c.filter_score)
    return regular[: config.filter.top_n] + watch[:WATCHLIST_KEEP]
