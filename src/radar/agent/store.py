"""Database access for the deep-dive app: read one item, log that it was opened."""

from __future__ import annotations

import json
import uuid

import psycopg

from radar.agent.graph import Item


def parse_item_id(raw: str) -> str:
    """A UUID from user-supplied text. Tolerates stray punctuation from copy-paste ("...dd8.")."""
    try:
        return str(uuid.UUID(raw.strip().strip(".,;:)>\"'")))
    except (ValueError, AttributeError) as e:
        raise LookupError("Unknown item") from e


def load_item(conn: psycopg.Connection, item_id: str) -> Item:
    item_id = parse_item_id(item_id)
    row = conn.execute(
        "select i.id, i.url, coalesce(nullif(s.headline, ''), i.title) as title, "
        "       coalesce(nullif(s.summary, ''), i.snippet, '') as snippet "
        "from items i left join lateral ("
        "  select headline, summary from item_scores where item_id = i.id "
        "  order by run_id desc limit 1) s on true "
        "where i.id = %s",
        (item_id,),
    ).fetchone()
    if row is None:
        raise LookupError("Unknown item")
    return Item(id=str(row["id"]), url=row["url"], title=row["title"], snippet=row["snippet"] or "")


def log_deepdive(conn: psycopg.Connection, item_id: str, run_id: str | None) -> None:
    """Record that the reader opened the deep dive (once per item; used by vote ranking later)."""
    conn.execute(
        "insert into feedback (item_id, run_id, action) values (%s, %s, 'deepdive') "
        "on conflict (item_id, action) do nothing",
        (item_id, run_id),
    )
    conn.commit()


def recent_items(conn: psycopg.Connection, limit: int = 20) -> list[dict]:
    """Dev picker: items from the latest digests."""
    return conn.execute(
        "select i.id, coalesce(nullif(s.headline, ''), i.title) as title, r.digest_date "
        "from digests d join runs r on r.id = d.run_id join items i on i.id = d.item_id "
        "left join item_scores s on s.item_id = i.id and s.run_id = d.run_id "
        "where not r.is_dry_run order by r.digest_date desc, d.position limit %s",
        (limit,),
    ).fetchall()


def load_chat(conn: psycopg.Connection, item_id: str) -> list[dict]:
    """The saved transcript for an item ([] if none): dicts with role, text, citations, notice."""
    row = conn.execute("select transcript from deepdive_chats where item_id = %s", (item_id,)).fetchone()
    return list(row["transcript"]) if row else []


def save_chat(conn: psycopg.Connection, item_id: str, transcript: list[dict]) -> None:
    conn.execute(
        "insert into deepdive_chats (item_id, transcript, updated_at) values (%s, %s::jsonb, now()) "
        "on conflict (item_id) do update set transcript = excluded.transcript, updated_at = now()",
        (item_id, json.dumps(transcript)),
    )
    conn.commit()
