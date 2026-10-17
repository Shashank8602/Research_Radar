"""Diversify stage: MMR for the core section, plus watchlist and exploration slots."""

from __future__ import annotations

import numpy as np

from radar.config import AppConfig
from radar.models import Candidate


def topic_of(c: Candidate) -> str:
    return c.best_topic or c.nearest_topic


def mmr_select(
    cands: list[Candidate],
    k: int,
    lam: float,
    max_per_topic: int | None = None,
    max_per_source: dict[str, int] | None = None,
) -> list[Candidate]:
    """Maximal Marginal Relevance: balance rank against similarity to already-picked items.

    With `max_per_topic`, no topic takes more than that many slots while other topics still have
    eligible items (the cap is relaxed only if slots would otherwise stay empty). `max_per_source`
    does the same per source type, e.g. {"github": 2} so new repos cannot crowd out papers.
    """
    if not cands or k <= 0:
        return []
    top = max(c.final_rank for c in cands) or 1.0
    vecs = {c.id: np.asarray(c.embedding, dtype=np.float32) for c in cands}
    chosen: list[Candidate] = []
    pool = list(cands)

    def mmr(c: Candidate) -> float:
        rel = c.final_rank / top
        if not chosen:
            return rel
        sim = max(float(vecs[c.id] @ vecs[s.id]) for s in chosen)
        return lam * rel - (1 - lam) * sim

    while pool and len(chosen) < k:
        allowed = pool
        if max_per_topic:
            counts: dict[str, int] = {}
            for s in chosen:
                counts[topic_of(s)] = counts.get(topic_of(s), 0) + 1
            under_cap = [c for c in pool if counts.get(topic_of(c), 0) < max_per_topic]
            allowed = under_cap or pool
        if max_per_source:
            by_src: dict[str, int] = {}
            for s in chosen:
                by_src[s.source] = by_src.get(s.source, 0) + 1
            under_src = [c for c in allowed if by_src.get(c.source, 0) < max_per_source.get(c.source, k)]
            allowed = under_src or allowed
        best = max(allowed, key=mmr)
        chosen.append(best)
        pool.remove(best)
    return chosen


def _eligible(c: Candidate, min_relevance: float) -> bool:
    # Unjudged items (degraded mode) stay eligible; judged ones must clear the bar.
    return (not c.judged) or (c.relevance or 0) >= min_relevance


def select_digest(cands: list[Candidate], config: AppConfig) -> list[Candidate]:
    quotas = {name: s.max_items for name, s in config.digest.sections.items()}
    min_rel = config.judge.min_relevance
    regular = [c for c in cands if not c.is_watchlist and _eligible(c, min_rel)]
    watch = [c for c in cands if c.is_watchlist and _eligible(c, min_rel / 2)]

    core = mmr_select(
        regular, quotas.get("core", 5), config.diversify.mmr_lambda,
        max_per_topic=config.diversify.max_per_topic,
        max_per_source=config.diversify.max_per_source,
    )
    taken = {c.id for c in core}

    watchlist = sorted(watch, key=lambda c: -c.final_rank)[: quotas.get("watchlist", 2)]

    # Exploration: a good item that sits furthest from the usual topic profile.
    rest = [c for c in regular if c.id not in taken and c.judged]
    explore: list[Candidate] = []
    if rest and quotas.get("exploration", 0) > 0:
        top = max(c.final_rank for c in rest) or 1.0
        core_topics = {topic_of(c) for c in core}
        pick = max(
            rest,
            key=lambda c: 0.5 * (c.final_rank / top)
            + 0.5 * (1 - c.filter_parts.get("cosine", 0))
            + (0.3 if topic_of(c) not in core_topics else 0.0),  # prefer a topic not yet shown
        )
        explore = [pick]

    out: list[Candidate] = []
    for section, items in (("core", core), ("watchlist", watchlist), ("exploration", explore)):
        for pos, c in enumerate(items, 1):
            c.section, c.position = section, pos
            out.append(c)
    return out
