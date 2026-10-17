"""Golden-set labeling: pick the next item to judge and record the answer.

The dashboard's Labeling page is a thin screen over these functions. A label says "would I want this
in my daily email?"; the evals replay them against the scores stored for each digest day.
"""

from __future__ import annotations

import random

import psycopg

GOAL = 250  # labels worth having for a stable precision@5


def progress(conn: psycopg.Connection) -> dict[str, int]:
    rows = conn.execute("select relevant, count(*) n from golden_labels group by relevant").fetchall()
    yes = sum(int(r["n"]) for r in rows if r["relevant"])
    no = sum(int(r["n"]) for r in rows if not r["relevant"])
    return {"relevant": yes, "not_relevant": no, "total": yes + no, "goal": GOAL}


def next_item(conn: psycopg.Connection, skipped: list[str] | None = None) -> dict | None:
    """An unlabeled, judged item. Items that made a digest come first, then the ones that did not
    (the hard negatives), so about half the labels teach the ranker what to leave out."""
    for in_digest in (True, False):
        rows = conn.execute(
            "select distinct on (i.id) i.id, i.canonical_url, i.title, i.source, s.headline, s.summary, "
            "s.best_topic, (d.item_id is not null) as in_digest "
            "from item_scores s join items i on i.id = s.item_id "
            "left join digests d on d.item_id = s.item_id and d.run_id = s.run_id "
            "where s.judge_model is not null "
            "and not exists (select 1 from golden_labels g where g.item_id = i.id) "
            "and i.id::text <> all(%s) and (d.item_id is not null) = %s "
            "order by i.id, random() limit 50",
            (list(skipped or []) or [""], in_digest),
        ).fetchall()
        if rows:
            return random.choice(rows)
    return None


def save_label(conn: psycopg.Connection, item_id: str, relevant: bool) -> None:
    conn.execute(
        "insert into golden_labels (item_id, relevant) values (%s, %s) "
        "on conflict (item_id) do update set relevant = excluded.relevant, labeled_at = now()",
        (item_id, relevant),
    )
    conn.commit()
