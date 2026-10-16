"""Compose stage: render the digest as HTML + plain text."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from radar.models import Candidate

TEMPLATES = Path(__file__).parent / "templates"
SECTION_TITLES = {
    "core": "Top picks for you",
    "watchlist": "Tools you follow: what's new",
    "exploration": "Something different (outside your usual topics)",
}
SOURCE_LABELS = {
    "arxiv": "Research paper",
    "hf_papers": "Research paper",
    "hn": "Tech community discussion",
    "rss": "Blog post",
    "watchlist": "New tool release",
}
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["j2", "html"]))


def build_context(
    items: list[Candidate],
    *,
    digest_date: date,
    run_id: str,
    degraded: bool,
    links: Callable[[Candidate], dict[str, str]] | None = None,
    topic_labels: dict[str, str] | None = None,
) -> dict:
    labels = topic_labels or {}
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
                        "headline": c.headline or c.title,
                        "original_title": c.title if c.headline and c.headline != c.title else "",
                        "kind": SOURCE_LABELS.get(c.source, "Article"),
                        "topic": labels.get(c.best_topic, ""),
                        "summary": c.summary,
                        "example": c.example,
                        "why_it_matters": c.why_it_matters,
                        "unscored": not c.judged,
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
            lines += [it["headline"], f"({it['kind']}) {it['url']}", it["summary"]]
            if it["example"]:
                lines += [it["example"]]
            lines += [f"Why it matters: {it['why_it_matters']}", ""]
    return html, "\n".join(lines)


def subject(digest_date: date, n_items: int, degraded: bool) -> str:
    tag = " (degraded)" if degraded else ""
    return f"Research Radar {digest_date.isoformat()}: {n_items} things worth knowing{tag}"
