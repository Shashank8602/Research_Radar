"""Compose stage: render the digest as HTML + plain text."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from radar.models import Candidate

TEMPLATES = Path(__file__).parent / "templates"
SECTION_TITLES = {
    "core": "Top picks",
    "watchlist": "Watchlist: releases you track",
    "exploration": "Something different",
}
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["j2", "html"]))


def _scores(c: Candidate) -> str:
    if not c.judged or None in (c.relevance, c.novelty, c.actionability):
        return "unscored"
    return f"rel {c.relevance:.0f} · new {c.novelty:.0f} · act {c.actionability:.0f}"


def build_context(
    items: list[Candidate],
    *,
    digest_date: date,
    run_id: str,
    degraded: bool,
    links: Callable[[Candidate], dict[str, str]] | None = None,
) -> dict:
    sections = []
    for key in ("core", "watchlist", "exploration"):
        chosen = sorted((c for c in items if c.section == key), key=lambda c: c.position)
        if not chosen:
            continue
        sections.append(
            {
                "title": SECTION_TITLES[key],
                "entries": [
                    {
                        "url": c.url,
                        "title": c.title,
                        "source": c.source,
                        "best_topic": c.best_topic,
                        "scores": _scores(c),
                        "summary": c.summary,
                        "why_it_matters": c.why_it_matters,
                        "links": links(c) if links else None,
                    }
                    for c in chosen
                ],
            }
        )
    return {
        "date": digest_date.strftime("%a %d %b %Y"),
        "items": items,
        "sections": sections,
        "degraded": degraded,
        "run_id": run_id,
    }


def render(ctx: dict) -> tuple[str, str]:
    """Returns (html, plain_text)."""
    html = _env.get_template("digest.html.j2").render(**ctx)
    lines = [f"Research Radar - {ctx['date']}", ""]
    for s in ctx["sections"]:
        lines += [s["title"].upper(), ""]
        for it in s["entries"]:
            lines += [it["title"], it["url"], it["summary"], f"Why it matters: {it['why_it_matters']}", ""]
    return html, "\n".join(lines)


def subject(digest_date: date, n_items: int, degraded: bool) -> str:
    tag = " (degraded)" if degraded else ""
    return f"Research Radar {digest_date.isoformat()}: {n_items} picks{tag}"
