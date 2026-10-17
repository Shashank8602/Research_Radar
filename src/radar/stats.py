"""Read-only aggregates for the dashboard: what ran, what was collected, how the votes look.

SQL fetches raw counts; the small pure functions below turn them into rates so they can be tested
without a database. Nothing here writes, and nothing returns item text beyond titles.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import psycopg

VOTE_ACTIONS = ("up", "down", "save", "deepdive")


def up_rate(up: int, down: int) -> float | None:
    """Share of votes that were 'more like this' (None when there are no up/down votes)."""
    return up / (up + down) if up + down else None


def pivot_weekly(rows: list[dict], key: str) -> dict[date, dict[str, int]]:
    """[{week, <key>, n}] -> {week: {key value: n}} for charting."""
    out: dict[date, dict[str, int]] = defaultdict(dict)
    for r in rows:
        out[r["week"]][r[key]] = int(r["n"])
    return dict(sorted(out.items()))


def weekly_up_rate(vote_rows: list[dict]) -> dict[date, float | None]:
    return {wk: up_rate(c.get("up", 0), c.get("down", 0)) for wk, c in pivot_weekly(vote_rows, "action").items()}


def section_up_rates(rows: list[dict]) -> dict[str, dict]:
    """[{section, action, n}] -> {section: {up, down, rate}} for up/down votes only."""
    by: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0})
    for r in rows:
        if r["action"] in ("up", "down"):
            by[r["section"] or "unknown"][r["action"]] += int(r["n"])
    return {s: {**c, "rate": up_rate(c["up"], c["down"])} for s, c in sorted(by.items())}


def overview(conn: psycopg.Connection) -> dict:
    sent = conn.execute(
        "select count(*) n from runs where not is_dry_run and status in ('sent', 'degraded')"
    ).fetchone()["n"]
    last = conn.execute(
        "select started_at, digest_date, status, n_collected, n_sent from runs "
        "where not is_dry_run order by started_at desc limit 1"
    ).fetchone()
    votes = {r["action"]: int(r["n"]) for r in conn.execute("select action, count(*) n from feedback group by action")}
    return {
        "digests_sent": int(sent),
        "last_run": last,
        "items_collected": int(conn.execute("select count(*) n from items").fetchone()["n"]),
        "labels": int(conn.execute("select count(*) n from golden_labels").fetchone()["n"]),
        "votes": {a: votes.get(a, 0) for a in VOTE_ACTIONS},
    }


def collected_by_source(conn: psycopg.Connection, weeks: int = 12) -> dict[date, dict[str, int]]:
    rows = conn.execute(
        "select date_trunc('week', created_at)::date as week, source, count(*) as n from items "
        "where created_at > now() - make_interval(weeks => %s) group by 1, 2",
        (weeks,),
    ).fetchall()
    return pivot_weekly(rows, "source")


def digested_by_source(conn: psycopg.Connection, weeks: int = 12) -> dict[date, dict[str, int]]:
    rows = conn.execute(
        "select date_trunc('week', r.started_at)::date as week, i.source, count(*) as n "
        "from digests d join runs r on r.id = d.run_id join items i on i.id = d.item_id "
        "where not r.is_dry_run and r.started_at > now() - make_interval(weeks => %s) group by 1, 2",
        (weeks,),
    ).fetchall()
    return pivot_weekly(rows, "source")


def vote_rows(conn: psycopg.Connection, weeks: int = 12) -> list[dict]:
    return conn.execute(
        "select date_trunc('week', created_at)::date as week, action, count(*) as n from feedback "
        "where created_at > now() - make_interval(weeks => %s) group by 1, 2",
        (weeks,),
    ).fetchall()


def section_vote_rows(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "select section, action, count(*) as n from feedback where action in ('up', 'down') group by 1, 2"
    ).fetchall()


def recent_runs(conn: psycopg.Connection, n: int = 14) -> list[dict]:
    return conn.execute(
        "select started_at, digest_date, status, n_collected, n_filtered, n_sent, notes from runs "
        "where not is_dry_run order by started_at desc limit %s",
        (n,),
    ).fetchall()
