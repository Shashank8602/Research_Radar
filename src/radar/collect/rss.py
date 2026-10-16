"""Generic RSS/Atom collector for blogs and GitHub release feeds."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import feedparser

from radar.collect.http import get
from radar.models import RawItem

_PRERELEASE = re.compile(r"(dev|[-.]dev|rc\d|[-.]rc|alpha|beta|nightly|preview|\.post\d)", re.I)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def parse(xml: str, name: str, *, is_watchlist: bool = False, per_feed: int | None = None) -> list[RawItem]:
    # Watchlist = 'what's new in the tools I track': only each tool's latest release.
    per_feed = per_feed or (1 if is_watchlist else 15)
    entries = feedparser.parse(xml).entries
    if is_watchlist:  # announce stable releases only
        entries = [e for e in entries if not _PRERELEASE.search(e.get("title", ""))]
    items = []
    for e in entries[:per_feed]:
        link = e.get("link")
        if not link:
            continue
        stamp = e.get("published_parsed") or e.get("updated_parsed")
        body = e.get("summary") or (e.get("content") or [{}])[0].get("value", "")
        title = (e.get("title") or "").strip()
        if is_watchlist:
            title = f"{name}: {title}"  # release titles are bare versions
        items.append(
            RawItem(
                url=link,
                title=title,
                source="watchlist" if is_watchlist else "rss",
                published_at=datetime(*stamp[:6], tzinfo=UTC) if stamp else None,
                snippet=_text(body)[:1500],
                origin=f"rss:{name}",
                is_watchlist=is_watchlist,
            )
        )
    return items


def fetch(name: str, feed: str, *, is_watchlist: bool = False) -> list[RawItem]:
    return parse(get(feed).text, name, is_watchlist=is_watchlist)
