"""Ranking and agreement metrics (plain numpy, no sklearn)."""

from __future__ import annotations

import numpy as np


def precision_at_k(scores: list[float], labels: list[bool], k: int) -> float | None:
    """Share of relevant items among the top k by score. None if fewer than k items."""
    if len(scores) < k:
        return None
    order = np.argsort(-np.asarray(scores, dtype=float), kind="stable")[:k]
    return float(np.mean(np.asarray(labels, dtype=float)[order]))


def average_precision(scores: list[float], labels: list[bool]) -> float | None:
    """Mean of precision at each relevant item's rank. None if there are no relevant items."""
    y = np.asarray(labels, dtype=bool)
    if not y.any():
        return None
    order = np.argsort(-np.asarray(scores, dtype=float), kind="stable")
    hits = y[order]
    precisions = np.cumsum(hits) / np.arange(1, len(hits) + 1)
    return float(np.mean(precisions[hits]))


def roc_auc(scores: list[float], labels: list[bool]) -> float | None:
    """Probability a random relevant item outranks a random irrelevant one (ties count half)."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=bool)
    pos, neg = s[y], s[~y]
    if pos.size == 0 or neg.size == 0:
        return None
    greater = (pos[:, None] > neg[None, :]).sum()
    ties = (pos[:, None] == neg[None, :]).sum()
    return float((greater + 0.5 * ties) / (pos.size * neg.size))


def agreement(predicted: list[bool], labels: list[bool]) -> dict[str, float | int | None]:
    """Confusion counts plus precision, recall, F1, accuracy and Cohen's kappa."""
    p = np.asarray(predicted, dtype=bool)
    y = np.asarray(labels, dtype=bool)
    tp, fp = int((p & y).sum()), int((p & ~y).sum())
    fn, tn = int((~p & y).sum()), int((~p & ~y).sum())
    n = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    accuracy = (tp + tn) / n if n else None
    kappa = None
    if n:
        p_o = (tp + tn) / n
        p_e = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n)
        kappa = (p_o - p_e) / (1 - p_e) if p_e < 1 else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall,
            "f1": f1, "accuracy": accuracy, "kappa": kappa}
