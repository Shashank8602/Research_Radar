"""Thin Postgres access (direct psycopg; pgvector SQL is easier this way than via supabase-py)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from radar.config import ROOT, get_env

MIGRATIONS_DIR = ROOT / "db" / "migrations"


@contextmanager
def connect(*, read_only: bool = False) -> Iterator[psycopg.Connection]:
    """Open a connection. `read_only` makes the server refuse any write, and prefers
    DASHBOARD_DATABASE_URL (a role limited to SELECT) when one is set."""
    env = get_env()
    url = (env.dashboard_database_url if read_only else None) or env.database_url
    if not url:
        env.require("database_url")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        if read_only:
            # Every transaction starts as BEGIN READ ONLY. A startup option would be dropped by the
            # connection pooler in front of the database, silently allowing writes.
            conn.read_only = True
        register_vector_types(conn)
        yield conn


def register_vector_types(conn: psycopg.Connection) -> None:
    """Teach psycopg about pgvector. No-op before the extension exists (first migration)."""
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        conn.rollback()


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
    if applied:
        register_vector_types(conn)
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
    allowed = {"n_collected", "n_filtered", "n_sent", "langfuse_trace_id"}
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
