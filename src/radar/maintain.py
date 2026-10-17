"""Storage retention: keep the free-tier database small (decision D-044).

Protected forever: items that were in a real digest, got a vote (more/less/save), or have a golden
label. Everything else ages out in two steps, like a trash can:

  1. after `slim_after_days`   -> "slim": drop the abstract and embedding (~90% of the row); keep
                                   title + link so the item is still recognised as already seen.
  2. after `delete_after_days` -> delete the item and its scores.

Also: test (dry) runs older than `dry_run_keep_days` lose their digests and the scores of unlabeled
items, feedback-link tokens are removed `token_grace_days` after they expire, and saved deep-dive chats
are removed `chat_keep_days` after their last message.

    uv run radar-maintain            # apply
    uv run radar-maintain --preview  # show what would change, change nothing
"""

from __future__ import annotations

import argparse

import psycopg
from pydantic import BaseModel

from radar import db
from radar.config import RetentionConfig, load_config

PROTECTED = """
    select d.item_id from digests d join runs r on r.id = d.run_id where not r.is_dry_run
    union select item_id from feedback
    union select item_id from golden_labels
"""


class MaintenanceReport(BaseModel):
    preview: bool
    dry_run_digest_rows: int = 0
    dry_run_score_rows: int = 0
    dry_run_runs_deleted: int = 0
    items_slimmed: int = 0
    items_deleted: int = 0
    tokens_deleted: int = 0
    chats_deleted: int = 0
    db_size_mb: float = 0.0
    warning: str | None = None


def run_maintenance(conn: psycopg.Connection, cfg: RetentionConfig, *, preview: bool) -> MaintenanceReport:
    r = MaintenanceReport(preview=preview)
    ex = conn.execute

    # 1. Old test runs: drop their digests and the scores of items nobody labeled.
    old_dry = (
        "select id from runs where is_dry_run "
        "and started_at < now() - make_interval(days => %(dry)s)"
    )
    p = {"dry": cfg.dry_run_keep_days, "slim": cfg.slim_after_days, "del": cfg.delete_after_days,
         "grace": cfg.token_grace_days}
    r.dry_run_digest_rows = ex(f"delete from digests where run_id in ({old_dry})", p).rowcount
    r.dry_run_score_rows = ex(
        f"delete from item_scores where run_id in ({old_dry}) "
        "and item_id not in (select item_id from golden_labels)", p).rowcount
    ex(f"delete from feedback_tokens where run_id in ({old_dry})", p)
    # Run rows are tiny; delete them only once nothing points at them any more.
    r.dry_run_runs_deleted = ex(
        f"delete from runs where id in ({old_dry}) "
        "and not exists (select 1 from item_scores s where s.run_id = runs.id) "
        "and not exists (select 1 from feedback f where f.run_id = runs.id)", p).rowcount

    # 2. Delete unprotected items older than delete_after_days (and what references them).
    doomed = (f"select id from items where created_at < now() - make_interval(days => %(del)s) "
              f"and id not in ({PROTECTED})")
    ex(f"delete from item_scores where item_id in ({doomed})", p)
    ex(f"delete from digests where item_id in ({doomed})", p)
    ex(f"delete from feedback_tokens where item_id in ({doomed})", p)
    ex(f"update items set cluster_id = null where cluster_id in ({doomed})", p)
    r.items_deleted = ex(f"delete from items where id in ({doomed})", p).rowcount

    # 3. Slim unprotected items older than slim_after_days.
    r.items_slimmed = ex(
        f"update items set snippet = null, embedding = null, embedding_model = null "
        f"where created_at < now() - make_interval(days => %(slim)s) "
        f"and (snippet is not null or embedding is not null) "
        f"and id not in ({PROTECTED})", p).rowcount

    # 4. Feedback-link tokens well past expiry.
    r.tokens_deleted = ex(
        "delete from feedback_tokens where expires_at < now() - make_interval(days => %(grace)s)", p
    ).rowcount

    # 5. Deep-dive chats not touched for chat_keep_days (links expire after 7 days anyway).
    r.chats_deleted = ex(
        "delete from deepdive_chats where updated_at < now() - make_interval(days => %(chat)s)",
        {"chat": cfg.chat_keep_days},
    ).rowcount

    if preview:
        conn.rollback()
    else:
        conn.commit()
    size = ex("select pg_database_size(current_database()) as b").fetchone()["b"]
    r.db_size_mb = round(size / 1_048_576, 1)
    if r.db_size_mb > cfg.warn_db_mb:
        r.warning = (f"database is {r.db_size_mb} MB (warning at {cfg.warn_db_mb} MB; free tier "
                     f"limit ~500 MB). Consider shorter retention windows in topics.yaml.")
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply storage retention rules.")
    ap.add_argument("--preview", action="store_true", help="report what would change; change nothing")
    args = ap.parse_args()
    cfg = load_config().retention
    with db.connect() as conn:
        r = run_maintenance(conn, cfg, preview=args.preview)
    verb = "would" if r.preview else "did"
    print(f"[maintain] {verb}: slim {r.items_slimmed} items, delete {r.items_deleted} items, "
          f"clear {r.dry_run_digest_rows} test-digest rows and {r.dry_run_score_rows} test scores, "
          f"delete {r.dry_run_runs_deleted} test runs, {r.tokens_deleted} expired link tokens and "
          f"{r.chats_deleted} old chats. "
          f"Database: {r.db_size_mb} MB.")
    if r.warning:
        print(f"[maintain] WARNING {r.warning}")


if __name__ == "__main__":
    main()
