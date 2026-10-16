"""Collect stage: run every configured source, isolating failures."""

from __future__ import annotations

import re
from collections.abc import Callable

from pydantic import BaseModel, Field

from radar.collect import arxiv, hf_papers, hn, rss
from radar.config import AppConfig
from radar.models import RawItem


class SourceReport(BaseModel):
    source: str
    n_items: int = 0
    n_kept: int = 0
    error: str | None = None


class CollectResult(BaseModel):
    items: list[RawItem] = Field(default_factory=list)
    reports: list[SourceReport] = Field(default_factory=list)

    @property
    def failed(self) -> list[str]:
        return [r.source for r in self.reports if r.error]


def keyword_filter(items: list[RawItem], keywords: list[str]) -> list[RawItem]:
    """Keep items whose title/snippet mention any keyword (case-insensitive, word-boundary
    for short keywords so 'RAG' does not match 'storage')."""
    if not keywords:
        return items
    pats = [
        re.compile(rf"\b{re.escape(k)}\b" if len(k) <= 4 else re.escape(k), re.IGNORECASE)
        for k in keywords
    ]
    return [i for i in items if any(p.search(f"{i.title} {i.snippet}") for p in pats)]


def collect_all(config: AppConfig) -> CollectResult:
    result = CollectResult()
    all_keywords = sorted({k for t in config.topics for k in t.keywords})

    def run(name: str, fn: Callable[[], list[RawItem]], post=None) -> None:
        report = SourceReport(source=name)
        try:
            items = fn()
            report.n_items = len(items)
            if post:
                items = post(items)
            report.n_kept = len(items)
            result.items.extend(items)
        except Exception as e:  # one bad source must never kill the run
            report.error = str(e)[:300]
        result.reports.append(report)

    cats = sorted({c for t in config.topics for c in t.sources.arxiv})
    if cats:
        run("arxiv", lambda: arxiv.fetch(cats), post=lambda xs: keyword_filter(xs, all_keywords))
    if config.global_sources.hf_daily_papers:
        run("hf_papers", hf_papers.fetch)
    queries = sorted({q for t in config.topics for q in t.sources.hn_queries})
    if queries:
        run("hn", lambda: hn.fetch(queries))
    for feed in config.global_sources.rss:
        run(f"rss:{feed.name}", lambda f=feed: rss.fetch(f.name, f.feed))
    for w in config.watchlist:
        run(f"watchlist:{w.name}", lambda w=w: rss.fetch(w.name, w.feed, is_watchlist=True))
    return result
