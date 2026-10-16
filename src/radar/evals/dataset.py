"""Labeled examples: golden labels joined with the scores stored for each digest day."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import psycopg

from radar.embed import as_list


@dataclass
class Example:
    item_id: str
    day: date
    label: bool
    parts: dict[str, float] = field(default_factory=dict)  # filter components
    relevance: float | None = None
    novelty: float | None = None
    actionability: float | None = None
    final_rank: float = 0.0
    embedding: list[float] | None = None
    title: str = ""
    source: str = ""


def load_examples(conn: psycopg.Connection) -> list[Example]:
    """One example per (digest day, labeled item), using the latest run of that day.

    Labels are per item; scores are per run. Items only get scores once they reach the judge,
    so every example comes from the shortlist (the ablation compares rankers within it).
    """
    rows = conn.execute(
        """
        with latest as (
          select distinct on (r.digest_date, s.item_id)
                 r.digest_date, s.item_id, s.filter_parts, s.relevance, s.novelty,
                 s.actionability, s.final_rank
          from item_scores s join runs r on r.id = s.run_id
          where r.status <> 'failed'
          order by r.digest_date, s.item_id, r.started_at desc
        )
        select l.*, g.relevant, i.embedding, i.title, i.source
        from latest l
        join golden_labels g on g.item_id = l.item_id
        join items i on i.id = l.item_id
        """
    ).fetchall()
    return [
        Example(
            item_id=str(r["item_id"]),
            day=r["digest_date"],
            label=bool(r["relevant"]),
            parts={k: float(v) for k, v in (r["filter_parts"] or {}).items()},
            relevance=r["relevance"],
            novelty=r["novelty"],
            actionability=r["actionability"],
            final_rank=float(r["final_rank"] or 0.0),
            embedding=as_list(r["embedding"]) if r["embedding"] is not None else None,
            title=r["title"],
            source=r["source"],
        )
        for r in rows
    ]


def by_day(examples: list[Example]) -> dict[date, list[Example]]:
    out: dict[date, list[Example]] = defaultdict(list)
    for e in examples:
        out[e.day].append(e)
    return dict(out)


def unique_items(examples: list[Example]) -> list[Example]:
    """One example per item (its most recent day), for pooled metrics."""
    latest: dict[str, Example] = {}
    for e in sorted(examples, key=lambda e: e.day):
        latest[e.item_id] = e
    return list(latest.values())
