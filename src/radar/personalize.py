"""Revealed interests: score candidates by how close they are to items I voted on.

score(item) = similarity to my nearest liked items - similarity to my nearest disliked items,
scaled to -1..1. "Save for later" counts as a stronger like than "More like this".

It feeds two places, both controlled by config and both 0 (off) until the ablation shows a gain
(decision D-005): `filter.weights.feedback` (shortlist) and `personalize.final_blend` (final rank).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import psycopg

from radar.config import PersonalizeConfig
from radar.embed import as_list
from radar.models import Candidate

ACTION_WEIGHT = {"up": 1.0, "save": 1.5, "deepdive": 1.2, "down": -1.0}
# bge-small similarity between unrelated texts sits around here; used when one side has no votes.
NEUTRAL_SIM = 0.35
SCALE = 0.30  # a 0.30 gap between liked and disliked similarity maps to the full +-1


@dataclass
class Votes:
    ids: list[str]
    vecs: np.ndarray  # (n, d), L2-normalised
    weights: np.ndarray  # (n,), >0 liked, <0 disliked

    def __len__(self) -> int:
        return len(self.ids)


def load_votes(conn: psycopg.Connection) -> Votes:
    rows = conn.execute(
        "select f.item_id, f.action, i.embedding from feedback f join items i on i.id = f.item_id "
        "where i.embedding is not null"
    ).fetchall()
    net: dict[str, float] = {}
    emb: dict[str, list[float]] = {}
    for r in rows:
        iid = str(r["item_id"])
        net[iid] = net.get(iid, 0.0) + ACTION_WEIGHT.get(r["action"], 0.0)
        emb[iid] = as_list(r["embedding"])
    ids = [i for i, w in net.items() if w != 0]
    if not ids:
        return Votes([], np.zeros((0, 0), dtype=np.float32), np.zeros(0, dtype=np.float32))
    return Votes(
        ids,
        np.array([emb[i] for i in ids], dtype=np.float32),
        np.array([net[i] for i in ids], dtype=np.float32),
    )


def _side(sims: np.ndarray, w: np.ndarray, k: int) -> float:
    """Weighted mean of the k highest similarities on one side (liked or disliked)."""
    if sims.size == 0:
        return NEUTRAL_SIM
    top = np.argsort(-sims)[:k]
    return float(np.sum(sims[top] * w[top]) / np.sum(w[top]))


def score_vector(vec, votes: Votes, *, k: int = 5, exclude_id: str | None = None) -> float:
    """-1..1. `exclude_id` drops the item's own vote (leave-one-out, used by the evals)."""
    if len(votes) == 0:
        return 0.0
    mask = np.ones(len(votes), dtype=bool)
    if exclude_id is not None:
        mask &= np.array([i != exclude_id for i in votes.ids])
    sims = votes.vecs @ np.asarray(vec, dtype=np.float32)
    pos = mask & (votes.weights > 0)
    neg = mask & (votes.weights < 0)
    liked = _side(sims[pos], votes.weights[pos], k)
    disliked = _side(sims[neg], -votes.weights[neg], k)
    return float(np.clip((liked - disliked) / SCALE, -1.0, 1.0))


def feedback_scores(cands: list[Candidate], votes: Votes, cfg: PersonalizeConfig) -> dict[str, float]:
    """Per-candidate scores, or {} when there are too few votes to trust."""
    if len(votes) < cfg.min_votes:
        return {}
    return {c.id: round(score_vector(c.embedding, votes, k=cfg.k), 4) for c in cands}


def apply_final_blend(cands: list[Candidate], scores: dict[str, float], blend: float) -> None:
    """Nudge the judge's final rank by the vote score (in place)."""
    if not blend or not scores:
        return
    for c in cands:
        c.final_rank = round(c.final_rank + blend * scores.get(c.id, 0.0), 4)
