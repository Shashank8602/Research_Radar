"""Hacker News stories via the Algolia API."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from radar.collect.http import get
from radar.models import RawItem

API = "https://hn.algolia.com/api/v1/search_by_date"


def parse(hits: list[dict], query: str) -> list[RawItem]:
    items = []
    for h in hits:
        url = h.get("url")
        title = (h.get("title") or "").strip()
        if not url or not title:
            continue  # Ask HN / text posts have no external URL
        items.append(
            RawItem(
                url=url,
                title=title,
                source="hn",
                published_at=datetime.fromtimestamp(h["created_at_i"], tz=UTC),
                snippet="",
                popularity=int(h.get("points") or 0),
                origin=f"hn:{query}",
            )
        )
    return items


def fetch(queries: list[str], *, hours: int = 48, min_points: int = 20) -> list[RawItem]:
    since = int(time.time()) - hours * 3600
    out: list[RawItem] = []
    for q in queries:
        resp = get(
            API,
            params={
                "query": q,
                "tags": "story",
                "numericFilters": f"created_at_i>{since},points>{min_points}",
                "hitsPerPage": 50,
            },
        )
        out.extend(parse(resp.json().get("hits", []), q))
    return out
