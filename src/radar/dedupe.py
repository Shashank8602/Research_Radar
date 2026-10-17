"""Dedupe stage: canonical URLs, content hashes, embedding clusters, 'already sent' exclusion.

Pure helpers (canonical_url, content_hash, merge_by_url, cluster_filter) are unit-tested without a
database; `persist_and_load` does the DB work.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import numpy as np
import psycopg

from radar.embed import as_list, embed_texts, item_text
from radar.models import Candidate, RawItem

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|ref|ref_src|source|mc_cid|mc_eid|igshid|share)$", re.I)
_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", re.I)
# Higher wins when the same story arrives from several sources.
SOURCE_PRIORITY = {"arxiv": 5, "watchlist": 4, "hf_papers": 3, "github": 3, "rss": 2, "hn": 1}


def canonical_url(url: str) -> str:
    p = urlparse(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    if host in ("export.arxiv.org", "rss.arxiv.org", "alphaxiv.org"):
        host = "arxiv.org"
    path = p.path
    if host == "arxiv.org":
        m = _ARXIV_ID.search(path)
        if m:
            return f"https://arxiv.org/abs/{m.group(1)}"
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k)])
    path = path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", query, ""))


def content_hash(title: str) -> str:
    norm = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return hashlib.sha1(norm.encode()).hexdigest()


def merge_by_url(items: list[RawItem]) -> list[RawItem]:
    """Collapse items sharing a canonical URL: keep the best source, max popularity, longest
    snippet. Preserves first-seen order."""
    merged: dict[str, RawItem] = {}
    for it in items:
        key = canonical_url(it.url)
        cur = merged.get(key)
        if cur is None:
            merged[key] = it.model_copy(update={"url": key})
            continue
        best = it if SOURCE_PRIORITY.get(it.source, 0) > SOURCE_PRIORITY.get(cur.source, 0) else cur
        merged[key] = best.model_copy(
            update={
                "url": key,
                "popularity": max(cur.popularity, it.popularity),
                "snippet": max(cur.snippet, it.snippet, key=len),
                "published_at": cur.published_at or it.published_at,
                "is_watchlist": cur.is_watchlist or it.is_watchlist,
            }
        )
    return list(merged.values())


def cluster_filter(cands: list[Candidate], threshold: float) -> tuple[list[Candidate], int]:
    """Drop near-duplicates (cosine >= threshold). Higher-priority/more popular items win.
    Returns (kept, n_dropped)."""
    order = sorted(
        range(len(cands)),
        key=lambda i: (-SOURCE_PRIORITY.get(cands[i].source, 0), -cands[i].popularity, i),
    )
    kept_idx: list[int] = []
    kept_vecs: list[np.ndarray] = []
    for i in order:
        v = np.asarray(cands[i].embedding, dtype=np.float32)
        if kept_vecs and float(np.max(np.stack(kept_vecs) @ v)) >= threshold:
            continue
        kept_idx.append(i)
        kept_vecs.append(v)
    kept = [cands[i] for i in sorted(kept_idx)]
    return kept, len(cands) - len(kept)


def recently_sent_ids(conn: psycopg.Connection, days: int) -> set[str]:
    rows = conn.execute(
        "select distinct d.item_id from digests d join runs r on r.id = d.run_id "
        "where not r.is_dry_run and r.status in ('sent','degraded') "
        "and r.started_at > now() - make_interval(days => %s)",
        (days,),
    ).fetchall()
    return {str(r["item_id"]) for r in rows}


def persist_and_load(
    conn: psycopg.Connection, raw: list[RawItem], model: str
) -> list[Candidate]:
    """Upsert items (embedding only the new ones) and return Candidates for every item."""
    merged = merge_by_url(raw)
    if not merged:
        return []
    urls = [i.url for i in merged]
    existing = {
        r["canonical_url"]: r
        for r in conn.execute(
            "select id, canonical_url, embedding from items where canonical_url = any(%s)", (urls,)
        )
    }
    new = [i for i in merged if i.url not in existing or existing[i.url]["embedding"] is None]
    vecs = embed_texts([item_text(i.title, i.snippet) for i in new], model)
    new_vec = {i.url: v for i, v in zip(new, vecs, strict=True)}

    cands: list[Candidate] = []
    for it in merged:
        vec = new_vec.get(it.url)
        row = conn.execute(
            "insert into items (canonical_url, url, content_hash, title, source, published_at, "
            "snippet, embedding, embedding_model, popularity) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (canonical_url) do update set "
            "popularity = greatest(items.popularity, excluded.popularity), "
            "snippet = coalesce(items.snippet, excluded.snippet), "
            "embedding = coalesce(items.embedding, excluded.embedding), "
            "embedding_model = coalesce(items.embedding_model, excluded.embedding_model) "
            "returning id, embedding",
            (
                it.url, it.url, content_hash(it.title), it.title, it.source, it.published_at,
                it.snippet, vec, model if vec is not None else None, it.popularity,
            ),
        ).fetchone()
        emb = row["embedding"] if row["embedding"] is not None else vec
        cands.append(
            Candidate(
                id=str(row["id"]),
                url=it.url,
                title=it.title,
                source=it.source,
                published_at=it.published_at,
                snippet=it.snippet,
                popularity=it.popularity,
                is_watchlist=it.is_watchlist,
                embedding=as_list(emb),
            )
        )
    conn.commit()
    return cands


def mark_clusters(conn: psycopg.Connection, kept: list[Candidate], dropped: list[Candidate]) -> None:
    """Record cluster membership: dropped duplicates point at their nearest kept item."""
    if not kept or not dropped:
        return
    kv = np.array([c.embedding for c in kept], dtype=np.float32)
    for d in dropped:
        j = int(np.argmax(kv @ np.asarray(d.embedding, dtype=np.float32)))
        conn.execute("update items set cluster_id = %s where id = %s", (kept[j].id, d.id))
    conn.commit()
