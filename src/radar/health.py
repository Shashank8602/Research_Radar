"""Missed-digest alarm: is there a recent real digest that actually went out?

A second scheduled workflow runs this a few hours after the digest is due. If the digest never ran,
crashed, or is still stuck in `running`, it emails an alert and exits non-zero, so the failure is
loud instead of a silent empty inbox (GitHub's scheduler can also fire hours late or skip a run).

    uv run radar-check              # alert by email and exit 1 if the digest is missing
    uv run radar-check --no-alert   # just report
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg

from radar import db
from radar.deliver import email as mail

MAX_AGE_HOURS = 10  # digest runs ~03:30 IST; this check runs ~10:00 IST
DONE = ("sent", "degraded")


@dataclass
class Health:
    ok: bool
    message: str


def evaluate(run: dict | None, now: datetime, max_age_hours: float = MAX_AGE_HOURS) -> Health:
    """Judge the latest real run row (None if there has never been one)."""
    if run is None:
        return Health(False, "No digest run has ever been recorded.")
    age = now - run["started_at"]
    when = run["started_at"].strftime("%Y-%m-%d %H:%M UTC")
    if age > timedelta(hours=max_age_hours):
        return Health(False, f"No digest started in the last {max_age_hours:g} hours "
                             f"(the latest, {run['status']}, started {when}).")
    if run["status"] in DONE:
        note = " (degraded: some items were not scored)" if run["status"] == "degraded" else ""
        return Health(True, f"Digest {run['status']} at {when}{note}.")
    detail = f" Notes: {run['notes']}" if run.get("notes") else ""
    return Health(False, f"The digest that started {when} has status '{run['status']}', not sent.{detail}")


def latest_real_run(conn: psycopg.Connection) -> dict | None:
    return conn.execute(
        "select status, started_at, notes from runs where not is_dry_run order by started_at desc limit 1"
    ).fetchone()


def main() -> None:
    ap = argparse.ArgumentParser(description="Check that today's digest went out.")
    ap.add_argument("--no-alert", action="store_true", help="report only; do not send the alert email")
    args = ap.parse_args()
    with db.connect() as conn:
        health = evaluate(latest_real_run(conn), datetime.now(UTC))
    print(f"[check] {'OK' if health.ok else 'PROBLEM'}: {health.message}")
    if health.ok:
        return
    if not args.no_alert:
        body = (f"{health.message}\n\nCheck the daily-digest workflow in GitHub Actions. If it ran late, "
                "the digest may still arrive; the run is idempotent, so re-running it is safe.")
        mail.send("Research Radar: no digest this morning", f"<p>{body}</p>".replace("\n\n", "</p><p>"), text=body)
        print("[check] alert emailed")
    sys.exit(1)


if __name__ == "__main__":
    main()
