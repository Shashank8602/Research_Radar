"""New GitHub repos with traction, found by search, each with the start of its README as the snippet.

Papers dominate a research feed because arXiv is firehose-shaped; a repo that suddenly gets
attention (a new agent skill, an MCP server, an eval tool) never shows up in one. This collector
searches recently CREATED repos that already have stars, so "new and noticed" is what comes back.
The README excerpt is what the judge and the deep dive read, not just the one-line description.
"""

from __future__ import annotations

import contextlib
import re
import time
from datetime import UTC, datetime, timedelta

import httpx

from radar.collect.http import USER_AGENT
from radar.models import RawItem

API = "https://api.github.com"
PAUSE_S = {True: 2.2, False: 8.0}  # search allows 30 requests a minute with a token, 10 without


def _headers(token: str | None, accept: str = "application/vnd.github+json") -> dict[str, str]:
    h = {"User-Agent": USER_AGENT, "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def clean_readme(md: str, max_chars: int) -> str:
    """Plain prose from the top of a README: no badges, images, HTML, code fences or link syntax."""
    md = re.sub(r"```.*?```", " ", md, flags=re.S)
    md = re.sub(r"<!--.*?-->", " ", md, flags=re.S)
    md = re.sub(r"<[^>]+>", " ", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)  # images and badges
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)  # [text](url) -> text
    md = re.sub(r"^[#>\-*|=_ \t]+", "", md, flags=re.M)  # heading/quote/list/table markers
    return re.sub(r"\s+", " ", md).strip()[:max_chars]


def parse(
    repos: list[dict], query: str, readmes: dict[str, str] | None = None, exclude: list[str] | None = None
) -> list[RawItem]:
    readmes = readmes or {}
    items = []
    for r in repos:
        name, url = r.get("full_name"), r.get("html_url")
        if not name or not url or r.get("fork") or r.get("archived"):
            continue
        desc = (r.get("description") or "").strip()
        topics = " ".join(r.get("topics") or [])
        label = f"{name} {desc} {topics}".lower()
        if any(term.lower() in label for term in exclude or []):
            continue  # a stray adult/gambling repo must never reach the inbox
        snippet = " ".join(x for x in (desc, topics, readmes.get(name, "")) if x)
        created = r.get("created_at")
        items.append(
            RawItem(
                url=url,
                title=f"{name}: {desc}" if desc else name,
                source="github",
                published_at=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
                snippet=snippet,
                popularity=int(r.get("stargazers_count") or 0),
                origin=f"github:{query}",
            )
        )
    return items


def _wait_for_reset(resp: httpx.Response, max_wait: float = 75) -> float | None:
    """Seconds until the rate limit lets us back in, if that is short enough to wait for."""
    if resp.headers.get("retry-after", "").isdigit():
        wait = float(resp.headers["retry-after"])
    elif resp.headers.get("x-ratelimit-remaining") == "0" and resp.headers.get("x-ratelimit-reset"):
        wait = float(resp.headers["x-ratelimit-reset"]) - time.time() + 1
    else:
        return None
    return max(wait, 1.0) if wait <= max_wait else None


def _search(client: httpx.Client, query: str, *, since: str, min_stars: int, per_query: int) -> list[dict]:
    params = {
        "q": f"{query} created:>{since} stars:>={min_stars}",
        "sort": "stars", "order": "desc", "per_page": per_query,
    }
    for attempt in range(2):
        resp = client.get(f"{API}/search/repositories", params=params)
        if resp.status_code in (403, 429):
            wait = _wait_for_reset(resp)
            if attempt == 0 and wait:
                time.sleep(wait)
                continue
            raise RuntimeError(f"GitHub search rate limit ({resp.status_code}); set GITHUB_TOKEN for more")
        resp.raise_for_status()
        return resp.json().get("items", [])
    return []


def _readme(client: httpx.Client, full_name: str, max_chars: int) -> str:
    resp = client.get(
        f"{API}/repos/{full_name}/readme", headers={"Accept": "application/vnd.github.raw+json"}
    )
    return clean_readme(resp.text, max_chars) if resp.status_code == 200 else ""


def fetch(
    queries: list[str],
    *,
    window_days: int = 14,
    min_stars: int = 100,
    per_query: int = 10,
    max_repos: int = 25,
    readme_chars: int = 1200,
    exclude: list[str] | None = None,
    token: str | None = None,
) -> list[RawItem]:
    since = (datetime.now(UTC) - timedelta(days=window_days)).date().isoformat()
    found: dict[str, tuple[dict, str]] = {}
    with httpx.Client(headers=_headers(token), timeout=30) as client:
        failed: list[str] = []
        for q in queries:
            try:
                for repo in _search(client, q, since=since, min_stars=min_stars, per_query=per_query):
                    found.setdefault(repo["full_name"], (repo, q))
            except (RuntimeError, httpx.HTTPError) as e:  # one bad query must not lose the rest
                failed.append(f"{q}: {e}")
            time.sleep(PAUSE_S[bool(token)])
        if failed and not found:
            raise RuntimeError("; ".join(failed)[:300])
        if failed:
            print(f"[github] {len(failed)}/{len(queries)} queries failed, continuing: {failed[0][:120]}")
        # README only for the strongest repos: one request each, and the rest add little.
        top = sorted(found.values(), key=lambda rq: -rq[0].get("stargazers_count", 0))[:max_repos]
        readmes = {}
        for repo, _ in top:
            with contextlib.suppress(httpx.HTTPError):  # the description alone still works
                readmes[repo["full_name"]] = _readme(client, repo["full_name"], readme_chars)
        missing = sum(1 for repo, _ in top if not readmes.get(repo["full_name"]))
        if missing:
            print(f"[github] no README text for {missing}/{len(top)} repos (rate limit? set GITHUB_TOKEN)")
    out: list[RawItem] = []
    for repo, q in top:
        out.extend(parse([repo], q, readmes, exclude))
    return out
