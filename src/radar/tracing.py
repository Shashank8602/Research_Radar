"""Langfuse tracing (Python SDK v3+ / OTel) plus the LiteLLM `langfuse_otel` callback.

Design (per Langfuse best practices):
- One trace per pipeline run (`radar-digest-run`), session = the digest date, tagged by feature.
- Pipeline stages are nested spans with stable, verb-first names; run-specific values go in
  metadata, never in names.
- Every LLM call is an explicit `generation` (model, role-labelled messages in/out, token usage,
  reasoning in metadata). The LiteLLM `langfuse_otel` callback is deliberately NOT used: for
  Groq it emitted a bare span with no model/usage/IO and its own environment label.
- Stage input/output are explicit small summaries, not raw function args (no secrets, no
  payload dumps).
- Secrets are masked before export. Everything is a no-op when Langfuse keys are absent.
"""

from __future__ import annotations

import functools
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

from radar.config import Env, get_env

F = TypeVar("F", bound=Callable[..., Any])

_SECRET_RE = re.compile(
    r"(gsk_[A-Za-z0-9]{10,}|sk-or-v1-[A-Za-z0-9]{10,}|sk-lf-[A-Za-z0-9-]{10,}|pk-lf-[A-Za-z0-9-]{10,}"
    r"|AIza[0-9A-Za-z_-]{20,}|postgresql://[^\s\"']+)"
)

_enabled = False


def mask(*, data: Any, **_: Any) -> Any:
    """Redact credentials from anything about to be exported to Langfuse."""
    if isinstance(data, str):
        return _SECRET_RE.sub("[REDACTED]", data)
    if isinstance(data, dict):
        return {k: mask(data=v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [mask(data=v) for v in data]
    return data


def init(env: Env | None = None) -> bool:
    """Configure the Langfuse client. Safe to call repeatedly. Returns True if on.

    Environment variables are set BEFORE the Langfuse client is created (it reads them at init).
    """
    global _enabled
    env = env or get_env()
    if _enabled:
        return True
    if not (env.langfuse_public_key and env.langfuse_secret_key):
        return False

    os.environ["LANGFUSE_PUBLIC_KEY"] = env.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = env.langfuse_secret_key
    os.environ["LANGFUSE_HOST"] = env.langfuse_host
    os.environ["LANGFUSE_BASE_URL"] = env.langfuse_host
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = env.app_env

    from langfuse import Langfuse

    Langfuse(mask=mask, release=env.app_release)  # registers as the global client
    _enabled = True
    return True


def is_enabled() -> bool:
    return _enabled


def _client():
    from langfuse import get_client

    return get_client()


@contextmanager
def run_trace(run_id: str | None, digest_date: str, dry_run: bool) -> Iterator[str | None]:
    """Root observation for one pipeline run. Yields the trace id (or None if disabled)."""
    if not _enabled:
        yield None
        return
    from langfuse import propagate_attributes

    lf = _client()
    tags = ["digest", "dry-run" if dry_run else "scheduled"]
    with lf.start_as_current_observation(
        as_type="span",
        name="radar-digest-run",
        input={"digest_date": digest_date, "dry_run": dry_run},
        metadata={"run_id": run_id},
    ) as root:
        with propagate_attributes(
            trace_name="radar-digest-run",
            session_id=f"digest-{digest_date}",
            tags=tags,
            metadata={"run_id": str(run_id), "dry_run": str(dry_run).lower()},
        ):
            trace_id = lf.get_current_trace_id()
            try:
                yield trace_id
            except Exception as e:
                root.update(level="ERROR", status_message=str(e)[:300])
                raise


class _NoopSpan:
    def update(self, **_: Any) -> None:
        pass


@contextmanager
def stage_span(name: str, *, input: Any = None, as_type: str = "span") -> Iterator[Any]:
    """Nested span for a pipeline stage. Call `.update(output=...)` on the yielded object
    (a no-op object when tracing is disabled)."""
    if not _enabled:
        yield _NoopSpan()
        return
    with _client().start_as_current_observation(as_type=as_type, name=name, input=input) as span:
        try:
            yield span
        except Exception as e:
            span.update(level="ERROR", status_message=str(e)[:300])
            raise


def traced_stage(name: str, as_type: str = "span") -> Callable[[F], F]:
    """Decorator for stage functions. IO capture is off on purpose (args may hold secrets or
    large payloads); stages record explicit summaries via `update_stage`."""

    def deco(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _enabled:
                return fn(*args, **kwargs)
            from langfuse import observe

            return observe(name=name, as_type=as_type, capture_input=False, capture_output=False)(
                fn
            )(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return deco


def update_stage(*, input: Any = None, output: Any = None, metadata: Any = None) -> None:
    """Attach small, human-readable input/output/metadata to the current observation."""
    if not _enabled:
        return
    _client().update_current_span(input=input, output=output, metadata=metadata)


@contextmanager
def generation(
    name: str, *, model: str, input: Any, model_parameters: dict[str, Any] | None = None
) -> Iterator[Any]:
    """One LLM invocation as a `generation` (yields None when tracing is off)."""
    if not _enabled:
        yield None
        return
    with _client().start_as_current_observation(
        as_type="generation",
        name=name,
        model=model,
        input=input,
        model_parameters=model_parameters,
    ) as gen:
        try:
            yield gen
        except Exception as e:
            gen.update(level="ERROR", status_message=str(e)[:300])
            raise


def flush() -> None:
    """Block until buffered traces are sent. Required in short-lived processes (cron, scripts)."""
    if _enabled:
        _client().flush()
