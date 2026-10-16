"""Ranking ablation and judge calibration, replayed offline from stored scores (no LLM calls).

Each ranker is recomputed from the stored filter components and judge scores using the CURRENT
config weights, so changing a weight in topics.yaml and re-running `radar-eval` shows its effect.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from radar.config import AppConfig
from radar.evals import metrics
from radar.evals.dataset import Example, by_day, unique_items
from radar.personalize import Votes, score_vector

FILTER_PARTS = ("cosine", "keyword", "recency", "popularity")
FEEDBACK_BLENDS = (0.1, 0.2, 0.3)
CURRENT = "Hybrid filter + LLM judge (current)"


def hybrid(e: Example, cfg: AppConfig) -> float:
    w = cfg.filter.weights
    return sum(getattr(w, k) * e.parts.get(k, 0.0) for k in FILTER_PARTS)


def judge_rank(e: Example, cfg: AppConfig) -> float:
    """Same formula as judge.apply_scores / fallback_text, from stored scores."""
    h = hybrid(e, cfg)
    if e.relevance is None:
        return 0.5 * h
    j = cfg.judge
    weighted = (j.w_relevance * e.relevance + j.w_novelty * (e.novelty or 0)
                + j.w_actionability * (e.actionability or 0)) / 10
    return weighted + 0.15 * h


def rankers(cfg: AppConfig, votes: Votes | None) -> list[tuple[str, Callable[[Example], float]]]:
    out: list[tuple[str, Callable[[Example], float]]] = [
        ("Keywords only", lambda e: e.parts.get("keyword", 0.0)),
        ("Embedding similarity only", lambda e: e.parts.get("cosine", 0.0)),
        ("Hybrid filter", lambda e: hybrid(e, cfg)),
        (CURRENT, lambda e: judge_rank(e, cfg)),
    ]
    if votes is not None and len(votes) >= cfg.personalize.min_votes:
        k = cfg.personalize.k

        def loo(e: Example) -> float:  # leave-one-out: an item's own vote never scores itself
            return score_vector(e.embedding, votes, k=k, exclude_id=e.item_id) if e.embedding else 0.0

        for b in FEEDBACK_BLENDS:
            out.append((f"+ your votes (blend {b})", lambda e, b=b: judge_rank(e, cfg) + b * loo(e)))
    return out


@dataclass
class AblationRow:
    ranker: str
    p5_per_day: float | None
    days_used: int
    p5_pooled: float | None
    p10_pooled: float | None
    avg_precision: float | None
    roc_auc: float | None


def run_ablation(examples: list[Example], cfg: AppConfig, votes: Votes | None = None) -> list[AblationRow]:
    days = by_day(examples)
    pooled = unique_items(examples)
    labels = [e.label for e in pooled]
    rows = []
    for name, fn in rankers(cfg, votes):
        per_day = []
        for exs in days.values():
            if len(exs) >= 5 and any(e.label for e in exs):
                per_day.append(metrics.precision_at_k([fn(e) for e in exs], [e.label for e in exs], 5))
        scores = [fn(e) for e in pooled]
        rows.append(AblationRow(
            ranker=name,
            p5_per_day=sum(per_day) / len(per_day) if per_day else None,
            days_used=len(per_day),
            p5_pooled=metrics.precision_at_k(scores, labels, 5),
            p10_pooled=metrics.precision_at_k(scores, labels, 10),
            avg_precision=metrics.average_precision(scores, labels),
            roc_auc=metrics.roc_auc(scores, labels),
        ))
    return rows


@dataclass
class CalibrationRow:
    threshold: float
    is_current: bool
    precision: float | None
    recall: float | None
    f1: float | None
    kappa: float | None
    n: int


def judge_calibration(examples: list[Example], cfg: AppConfig) -> tuple[list[CalibrationRow], float | None]:
    """How well 'judge relevance >= t' agrees with my labels, for a sweep of thresholds t.
    Also returns the ROC-AUC of the raw relevance score."""
    judged = [e for e in unique_items(examples) if e.relevance is not None]
    labels = [e.label for e in judged]
    rows = []
    for t in range(2, 10):
        a = metrics.agreement([e.relevance >= t for e in judged], labels)
        rows.append(CalibrationRow(
            threshold=t, is_current=abs(t - cfg.judge.min_relevance) < 1e-9,
            precision=a["precision"], recall=a["recall"], f1=a["f1"], kappa=a["kappa"], n=len(judged),
        ))
    auc = metrics.roc_auc([e.relevance for e in judged], labels)
    return rows, auc
