"""Hugging Face Daily Papers (community-curated, includes upvotes)."""

from __future__ import annotations

from datetime import datetime

from radar.collect.http import get
from radar.models import RawItem

API = "https://huggingface.co/api/daily_papers"


def parse(rows: list[dict]) -> list[RawItem]:
    items = []
    for row in rows:
        paper = row.get("paper") or {}
        pid = paper.get("id")
        if not pid:
            continue
        published = None
        if row.get("publishedAt"):
            published = datetime.fromisoformat(row["publishedAt"].replace("Z", "+00:00"))
        items.append(
            RawItem(
                url=f"https://arxiv.org/abs/{pid}",  # same canonical URL as the arXiv feed
                title=(row.get("title") or paper.get("title") or "").strip(),
                source="hf_papers",
                published_at=published,
                snippet=(row.get("summary") or paper.get("summary") or "").strip()[:1500],
                popularity=int(paper.get("upvotes") or 0),
                origin="hf_daily_papers",
            )
        )
    return items


def fetch() -> list[RawItem]:
    return parse(get(API).json())
