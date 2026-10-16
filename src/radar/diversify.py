"""Diversify stage: MMR for the core section, plus watchlist and exploration slots."""

from __future__ import annotations

import numpy as np

from radar.config import AppConfig
from radar.models import Candidate


def mmr_select(cands: list[Candidate], k: int, lam: float) -> list[Candidate]:
    """Maximal Marginal Relevance: balance rank against similarity to already-picked items."""
    if not cands or k <= 0:
        return []
    top = max(c.final_rank for c in cands) or 1.0
    vecs = {c.id: np.asarray(c.embedding, dtype=np.float32) for c in cands}
    chosen: list[Candidate] = []
    pool = list(cands)
    while pool and len(chosen) < k:
        def mmr(c: Candidate) -> float:
            rel = c.final_rank / top
            if not chosen:
                return rel
            sim = max(float(vecs[c.id] @ vecs[s.id]) for s in chosen)
            return lam * rel - (1 - lam) * sim

        best = max(pool, key=mmr)
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

    core = mmr_select(regular, quotas.get("core", 5), config.diversify.mmr_lambda)
    taken = {c.id for c in core}

    watchlist = sorted(watch, key=lambda c: -c.final_rank)[: quotas.get("watchlist", 2)]

    # Exploration: a good item that sits furthest from the usual topic profile.
    rest = [c for c in regular if c.id not in taken and c.judged]
    explore: list[Candidate] = []
    if rest and quotas.get("exploration", 0) > 0:
        top = max(c.final_rank for c in rest) or 1.0
        pick = max(
            rest, key=lambda c: 0.5 * (c.final_rank / top) + 0.5 * (1 - c.filter_parts.get("cosine", 0))
        )
        explore = [pick]

    out: list[Candidate] = []
    for section, items in (("core", core), ("watchlist", watchlist), ("exploration", explore)):
        for pos, c in enumerate(items, 1):
            c.section, c.position = section, pos
            out.append(c)
    return out
