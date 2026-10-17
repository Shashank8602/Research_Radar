"""Phase 0 smoke test: LLM call -> run row -> email -> trace.

Usage: uv run radar-smoke [--no-email] [--no-db] [--no-llm]
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import date

from pydantic import BaseModel

from radar import db, llm, tracing
from radar.config import get_env
from radar.deliver import email as mail


class Pong(BaseModel):
    reply: str
    number: int


@tracing.traced_stage("call-llm", as_type="span")
def _llm_step() -> Pong:
    result, model = llm.complete_structured(
        "Reply with a short greeting in `reply` and the number 7 in `number`.",
        Pong,
        name="smoke-greeting",
    )
    tracing.update_stage(
        input="greeting request", output=result.model_dump(), metadata={"model_used": model}
    )
    print(f"[llm] {model}: {result}")
    return result


@tracing.traced_stage("send-email", as_type="span")
def _email_step() -> None:
    env = get_env()
    mail.send("Research Radar smoke test", "<h1>It works</h1><p>Phase 0 smoke test.</p>")
    tracing.update_stage(
        input={"backend": env.email_backend}, output={"sent": True, "to": env.email_to}
    )
    print(f"[email] sent via {env.email_backend} to {env.email_to}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    print(f"[tracing] langfuse {'on' if tracing.init(get_env()) else 'off (no keys)'}")

    with contextlib.ExitStack() as stack:
        conn, run_id = None, None
        if not args.no_db:
            conn = stack.enter_context(db.connect())
            print(f"[db] migrations applied: {db.migrate(conn) or 'none (up to date)'}")
            run_id = db.start_run(conn, date.today(), is_dry_run=True)
            print(f"[db] smoke run row: {run_id}")

        status, notes, trace_id = "sent", None, None
        try:
            with tracing.run_trace(run_id, date.today().isoformat(), dry_run=True) as trace_id:
                if not args.no_llm:
                    _llm_step()
                if not args.no_email:
                    _email_step()
                tracing.update_stage(output={"status": "ok"})
            print(f"[tracing] trace id: {trace_id}")
        except Exception as e:
            status, notes = "failed", str(e)[:500]
            raise
        finally:
            tracing.flush()
            if conn is not None:
                db.finish_run(conn, run_id, status, notes, langfuse_trace_id=trace_id)


if __name__ == "__main__":
    main()
