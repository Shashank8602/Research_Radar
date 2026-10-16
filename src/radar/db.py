"""Thin Postgres access (direct psycopg; pgvector SQL is easier this way than via supabase-py)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from radar.config import ROOT, get_env

MIGRATIONS_DIR = ROOT / "db" / "migrations"


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    env = get_env()
    env.require("database_url")
    with psycopg.connect(env.database_url, row_factory=dict_row) as conn:
        yield conn


def migrate(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply unapplied *.sql files in name order. Returns the names applied."""
    conn.execute(
        "create table if not exists schema_migrations "
        "(name text primary key, applied_at timestamptz default now())"
    )
    done = {r["name"] for r in conn.execute("select name from schema_migrations")}
    applied = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in done:
            continue
        conn.execute(path.read_text(encoding="utf-8"))
        conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))
        applied.append(path.name)
    conn.commit()
    return applied


def start_run(conn: psycopg.Connection, digest_date: date, is_dry_run: bool = False) -> str | None:
    """Create a run row. Returns its id, or None if a real run already exists for that date
    (the idempotency lock)."""
    row = conn.execute(
        "insert into runs (digest_date, is_dry_run) values (%s, %s) "
        "on conflict do nothing returning id",
        (digest_date, is_dry_run),
    ).fetchone()
    conn.commit()
    return str(row["id"]) if row else None


def finish_run(
    conn: psycopg.Connection, run_id: str, status: str, notes: str | None = None, **counts
) -> None:
    allowed = {"n_collected", "n_filtered", "n_sent", "cost_usd", "langfuse_trace_id"}
    extra = {k: v for k, v in counts.items() if k in allowed}
    sets = [
        "status = %s",
        "notes = %s",
        "sent_at = case when %s = 'sent' then now() else sent_at end",
    ]
    params: list = [status, notes, status]
    for k, v in extra.items():
        sets.append(f"{k} = %s")
        params.append(v)
    params.append(run_id)
    conn.execute(f"update runs set {', '.join(sets)} where id = %s", params)
    conn.commit()
