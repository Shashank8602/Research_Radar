"""Pipeline orchestrator: collect -> dedupe -> filter -> judge -> diversify -> compose -> send.

Usage:
    uv run radar-run                      # real run (claims today's lock, sends email)
    uv run radar-run --dry-run            # no lock, no email
    uv run radar-run --dry-run --email    # no lock, but email me the result
    uv run radar-run --dry-run --top-n 8  # cheaper iteration while developing
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date

from psycopg.types.json import Jsonb
from pydantic import BaseModel

from radar import compose, db, dedupe, tracing
from radar import diversify as diversify_stage
from radar import filter as filter_stage
from radar import judge as judge_stage
from radar.collect import collect_all
from radar.config import ROOT, get_env, load_config
from radar.deliver import email as mail
from radar.models import Candidate


class RunSummary(BaseModel):
    run_id: str | None
    status: str
    n_collected: int = 0
    n_candidates: int = 0
    n_filtered: int = 0
    n_unjudged: int = 0
    n_sent: int = 0
    failed_sources: list[str] = []
    trace_id: str | None = None


def _persist_scores(conn, run_id: str, cands: list[Candidate], judge_model: str) -> None:
    for c in cands:
        conn.execute(
            "insert into item_scores (item_id, run_id, best_topic, relevance, novelty, "
            "actionability, rationale, summary, why_it_matters, headline, example, filter_score, "
            "filter_parts, final_rank, judge_model) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing",
            (
                c.id, run_id, c.best_topic or c.nearest_topic, c.relevance, c.novelty,
                c.actionability, c.rationale, c.summary, c.why_it_matters, c.headline, c.example,
                c.filter_score,
                Jsonb(c.filter_parts), c.final_rank, judge_model if c.judged else None,
            ),
        )
    conn.commit()


def _persist_digest(conn, run_id: str, chosen: list[Candidate]) -> None:
    for c in chosen:
        conn.execute(
            "insert into digests (run_id, item_id, section, position) values (%s,%s,%s,%s) "
            "on conflict do nothing",
            (run_id, c.id, c.section, c.position),
        )
    conn.commit()


def _dump_pool(run_id: str, digest_date: date, cands: list[Candidate], chosen_ids: set[str]) -> None:
    """Store the scored candidate pool so Phase 2 evals can replay it offline."""
    path = ROOT / "evals" / "candidate_pool" / f"{digest_date.isoformat()}-{run_id[:8]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in cands:
            row = c.model_dump(mode="json", exclude={"embedding"})
            row["in_digest"] = c.id in chosen_ids
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(
    *, dry_run: bool = False, send_email: bool | None = None, top_n: int | None = None,
    digest_date: date | None = None,
) -> RunSummary:
    config = load_config()
    env = get_env()
    digest_date = digest_date or date.today()
    send_email = (not dry_run) if send_email is None else send_email
    if top_n:
        config.filter.top_n = top_n
    tracing.init(env)

    with db.connect() as conn:
        db.migrate(conn)
        run_id = db.start_run(conn, digest_date, is_dry_run=dry_run)
        if run_id is None:
            print(f"[run] a digest for {digest_date} already exists; nothing to do.")
            return RunSummary(run_id=None, status="skipped")

        summary = RunSummary(run_id=run_id, status="running")
        notes: list[str] = []
        try:
            with tracing.run_trace(run_id, digest_date.isoformat(), dry_run) as trace_id:
                summary.trace_id = trace_id
                _execute(conn, config, summary, run_id, digest_date, dry_run, send_email, notes)
                tracing.update_stage(
                    output={
                        "status": summary.status, "items_sent": summary.n_sent,
                        "collected": summary.n_collected, "judged": summary.n_filtered
                        - summary.n_unjudged, "failed_sources": summary.failed_sources,
                    }
                )
            db.finish_run(
                conn, run_id, summary.status, "; ".join(notes) or None,
                n_collected=summary.n_collected, n_filtered=summary.n_filtered,
                n_sent=summary.n_sent, langfuse_trace_id=trace_id,
            )
        except Exception as e:
            conn.rollback()
            db.finish_run(conn, run_id, "failed", str(e)[:500], langfuse_trace_id=summary.trace_id)
            raise
        finally:
            tracing.flush()
    return summary


def _execute(conn, config, summary, run_id, digest_date, dry_run, send_email, notes) -> None:
    # 1. collect
    with tracing.stage_span(
        "collect-sources", input={"topics": len(config.topics), "watchlist": len(config.watchlist)}
    ) as span:
        collected = collect_all(config)
        summary.n_collected = len(collected.items)
        summary.failed_sources = collected.failed
        if collected.failed:
            notes.append(f"failed sources: {', '.join(collected.failed)}")
        span.update(
            output={"items": len(collected.items), "failed": collected.failed},
            metadata={"per_source": {r.source: r.n_kept for r in collected.reports}},
        )
        print(f"[collect] {len(collected.items)} items; failed: {collected.failed or 'none'}")

    # 2. dedupe
    with tracing.stage_span("dedupe-items", input={"raw_items": len(collected.items)}) as span:
        cands = dedupe.persist_and_load(conn, collected.items, config.models.embedding)
        sent = dedupe.recently_sent_ids(conn, config.dedupe.resend_window_days)
        fresh = [c for c in cands if c.id not in sent]
        kept, n_dup = dedupe.cluster_filter(fresh, config.dedupe.similarity_threshold)
        kept_ids = {c.id for c in kept}
        dedupe.mark_clusters(conn, kept, [c for c in fresh if c.id not in kept_ids])
        summary.n_candidates = len(kept)
        span.update(
            output={"unique": len(cands), "already_sent": len(cands) - len(fresh),
                    "near_duplicates": n_dup, "candidates": len(kept)},
        )
        print(f"[dedupe] {len(cands)} unique, {len(cands) - len(fresh)} already sent, "
              f"{n_dup} near-duplicates -> {len(kept)}")

    # 3. cheap filter
    with tracing.stage_span(
        "filter-candidates", input={"candidates": len(kept), "top_n": config.filter.top_n}
    ) as span:
        topic_vecs = filter_stage.build_topic_vectors(config)
        scored = filter_stage.score_candidates(kept, config, topic_vecs)
        top = filter_stage.select_top(scored, config)
        summary.n_filtered = len(top)
        by_topic = Counter(c.nearest_topic for c in top)
        span.update(output={"scored": len(scored), "selected": len(top)},
                    metadata={"by_topic": dict(by_topic)})
        print(f"[filter] {len(scored)} fresh -> top {len(top)} {dict(by_topic)}")

    # 4. judge
    with tracing.stage_span(
        "judge-items",
        input={"items": len(top), "batch_size": config.judge.batch_size, "model": config.models.judge},
    ) as span:
        summary.n_unjudged = judge_stage.judge_all(top, config)
        span.update(output={"judged": len(top) - summary.n_unjudged,
                            "unjudged": summary.n_unjudged})
        print(f"[judge] {len(top) - summary.n_unjudged}/{len(top)} judged")
    degraded = summary.n_unjudged > 0
    if degraded:
        notes.append(f"{summary.n_unjudged} items unjudged (LLM unavailable)")

    # 5. diversify
    with tracing.stage_span("diversify-items", input={"candidates": len(top)}) as span:
        chosen = diversify_stage.select_digest(top, config)
        span.update(output={"selected": [(c.section, c.title[:80]) for c in chosen]})
        print(f"[diversify] {Counter(c.section for c in chosen)}")

    judge_model = config.models.judge
    _persist_scores(conn, run_id, top, judge_model)
    _persist_digest(conn, run_id, chosen)
    _dump_pool(run_id, digest_date, top, {c.id for c in chosen})

    # 6. compose + send
    with tracing.stage_span("compose-digest", input={"items": len(chosen), "degraded": degraded}) as span:
        ctx = compose.build_context(
            chosen, digest_date=digest_date, run_id=run_id, degraded=degraded,
            topic_labels={t.name: t.label or t.name for t in config.topics},
        )
        html, text = compose.render(ctx)
        span.update(output={"items": len(chosen), "html_chars": len(html)})
    summary.n_sent = len(chosen)

    if send_email and chosen:
        with tracing.stage_span("send-email", input={"subject_items": len(chosen)}) as span:
            mail.send(compose.subject(digest_date, len(chosen), degraded), html, text=text)
            span.update(output={"sent": True, "to": get_env().email_to})
            print(f"[send] emailed {get_env().email_to}")
        summary.status = "dry-run" if dry_run else ("degraded" if degraded else "sent")
    else:
        summary.status = "dry-run" if dry_run else ("degraded" if degraded else "sent")
        if not send_email:
            print("[send] skipped (dry run)")
        else:
            notes.append("nothing cleared the bar; no email sent")
            print("[send] nothing to send")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Research Radar pipeline.")
    ap.add_argument("--dry-run", action="store_true", help="no lock, no email")
    ap.add_argument("--email", action="store_true", help="with --dry-run, still send the email")
    ap.add_argument("--top-n", type=int, help="override filter.top_n (cheaper dev runs)")
    args = ap.parse_args()
    s = run(dry_run=args.dry_run, send_email=True if args.email else None, top_n=args.top_n)
    print(f"[done] {s.status}: {s.n_sent} items; run {s.run_id}; trace {s.trace_id}")


if __name__ == "__main__":
    main()
