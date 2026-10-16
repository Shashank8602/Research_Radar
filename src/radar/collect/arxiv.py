"""arXiv daily listings via the RSS/Atom feed (friendlier than the search API, which rate-limits)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import feedparser

from radar.collect.http import get
from radar.models import RawItem

FEED = "https://rss.arxiv.org/atom/{cats}"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _abstract(summary: str) -> str:
    # Feed summaries look like "arXiv:2501.01234v1 Announce Type: new Abstract: ...".
    m = re.search(r"Abstract:\s*(.*)", summary or "", flags=re.S)
    return _clean(m.group(1) if m else summary)


def parse(xml: str, origin: str = "") -> list[RawItem]:
    items = []
    for e in feedparser.parse(xml).entries:
        if "replace" in (e.get("arxiv_announce_type") or ""):
            continue  # skip replacements/cross-list updates of old papers
        link = e.get("link", "")
        if not link:
            continue
        published = None
        if e.get("published_parsed"):
            published = datetime(*e.published_parsed[:6], tzinfo=UTC)
        items.append(
            RawItem(
                url=link,
                title=_clean(e.get("title", "")),
                source="arxiv",
                published_at=published,
                snippet=_abstract(e.get("summary", ""))[:1500],
                origin=origin,
            )
        )
    return items


def fetch(categories: list[str]) -> list[RawItem]:
    cats = "+".join(sorted(set(categories)))
    resp = get(FEED.format(cats=cats))
    return parse(resp.text, origin=f"arxiv:{cats}")
