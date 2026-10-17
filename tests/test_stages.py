from datetime import UTC, date, datetime, timedelta

import numpy as np

from radar import compose, dedupe, diversify, judge
from radar import filter as flt
from radar.collect import arxiv, hf_papers, hn, keyword_filter, rss
from radar.config import load_config
from radar.models import Candidate, JudgeBatch, JudgeItem, RawItem

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def cand(i, *, title="t", source="arxiv", emb=None, rank=0.5, judged=True, rel=8.0, **kw):
    return Candidate(
        id=str(i), url=f"https://x/{i}", title=title, source=source,
        embedding=list(emb if emb is not None else np.eye(4)[i % 4]),
        final_rank=rank, judged=judged, relevance=rel if judged else None, **kw,
    )


# ---- dedupe ----------------------------------------------------------------------------
def test_canonical_url_strips_tracking_and_normalises():
    assert dedupe.canonical_url("http://www.Example.com/post/?utm_source=x&id=2#frag") == (
        "https://example.com/post?id=2"
    )


def test_canonical_url_arxiv_variants_collapse():
    want = "https://arxiv.org/abs/2501.01234"
    for u in (
        "https://arxiv.org/pdf/2501.01234v2",
        "http://export.arxiv.org/abs/2501.01234v1",
        "https://arxiv.org/html/2501.01234",
        "https://arxiv.org/abs/2501.01234",
    ):
        assert dedupe.canonical_url(u) == want


def test_merge_by_url_prefers_arxiv_and_keeps_max_popularity():
    a = RawItem(url="https://arxiv.org/abs/2501.01234", title="P", source="arxiv", snippet="short")
    h = RawItem(url="https://arxiv.org/pdf/2501.01234v1", title="P", source="hf_papers",
                snippet="a much longer snippet", popularity=42)
    (m,) = dedupe.merge_by_url([h, a])
    assert m.source == "arxiv" and m.popularity == 42 and m.snippet == "a much longer snippet"


def test_cluster_filter_drops_near_duplicates_keeps_priority_source():
    v = [1, 0, 0, 0]
    near = [0.99, 0.14, 0, 0]
    a = cand(0, source="hn", emb=v)
    b = cand(1, source="arxiv", emb=near)
    c = cand(2, source="arxiv", emb=[0, 1, 0, 0])
    kept, dropped = dedupe.cluster_filter(
        [a, b, c], 0.95
    )
    assert dropped == 1 and {x.id for x in kept} == {"1", "2"}


def test_content_hash_ignores_case_and_punctuation():
    assert dedupe.content_hash("Hello, World!") == dedupe.content_hash("hello world")


# ---- collectors (parsing fixtures) -------------------------------------------------------
ARXIV_XML = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>
 <title>Agent Paper</title><link href="http://arxiv.org/abs/2501.00001v1"/>
 <summary>arXiv:2501.00001v1 Announce Type: new Abstract: We study tool use.</summary>
 <published>2026-10-16T04:00:00Z</published><arxiv:announce_type>new</arxiv:announce_type></entry>
 <entry><title>Old Paper</title><link href="http://arxiv.org/abs/2001.00002v3"/>
 <summary>arXiv:2001.00002v3 Announce Type: replace Abstract: Old.</summary>
 <arxiv:announce_type>replace</arxiv:announce_type></entry></feed>"""


def test_arxiv_parse_extracts_abstract_and_skips_replacements():
    items = arxiv.parse(ARXIV_XML)
    assert len(items) == 1
    assert items[0].snippet == "We study tool use." and items[0].source == "arxiv"


def test_hf_papers_parse_maps_to_arxiv_url():
    rows = [{"paper": {"id": "2501.00001", "upvotes": 12, "summary": "S"}, "title": "T",
             "publishedAt": "2026-10-16T00:00:00.000Z"}]
    (it,) = hf_papers.parse(rows)
    assert it.url == "https://arxiv.org/abs/2501.00001" and it.popularity == 12


def test_hn_parse_skips_posts_without_url():
    hits = [{"title": "A", "url": "https://a.com", "points": 50, "created_at_i": 1_760_000_000},
            {"title": "Ask HN", "url": None, "points": 5, "created_at_i": 1_760_000_000}]
    assert [i.title for i in hn.parse(hits, "q")] == ["A"]


def test_rss_watchlist_keeps_only_latest_and_prefixes_name():
    xml = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>v2</title><link href="https://g/2"/><updated>2026-10-16T00:00:00Z</updated></entry>
      <entry><title>v1</title><link href="https://g/1"/><updated>2026-10-01T00:00:00Z</updated></entry></feed>"""
    items = rss.parse(xml, "Tool", is_watchlist=True)
    assert [i.title for i in items] == ["Tool: v2"] and items[0].is_watchlist


def test_rss_watchlist_skips_prereleases():
    xml = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>v1.107.0-dev.3</title><link href="https://g/3"/></entry>
      <entry><title>v1.106.0</title><link href="https://g/2"/></entry></feed>"""
    assert [i.title for i in rss.parse(xml, "T", is_watchlist=True)] == ["T: v1.106.0"]


def test_keyword_filter_word_boundary_for_short_keywords():
    items = [RawItem(url="u1", title="Cloud storage tips", source="arxiv"),
             RawItem(url="u2", title="A new RAG method", source="arxiv")]
    assert [i.url for i in keyword_filter(items, ["RAG"])] == ["u2"]


# ---- filter ----------------------------------------------------------------------------
def test_recency_and_keyword_scores():
    assert flt.recency_score(NOW, NOW, 3) == 1.0
    assert abs(flt.recency_score(NOW - timedelta(days=3), NOW, 3) - 0.5) < 1e-9
    assert flt.keyword_score("RAG reranker", "", ["RAG", "reranker"]) == 1.0
    assert flt.keyword_score("nothing", "nope", ["RAG"]) == 0.0


def test_score_candidates_ranks_on_topic_higher_and_drops_stale():
    cfg = load_config()
    names = [t.name for t in cfg.topics]
    vecs = {n: np.eye(len(names))[i].astype(np.float32) for i, n in enumerate(names)}
    on = cand(0, emb=list(np.eye(len(names))[0]), published_at=NOW, title="agent multi-agent tool use")
    off = cand(1, emb=list(np.eye(len(names))[-1] * 0 + 0.01), published_at=NOW, title="unrelated")
    stale = cand(2, emb=list(np.eye(len(names))[0]), published_at=NOW - timedelta(days=60))
    out = flt.score_candidates([on, off, stale], cfg, vecs, now=NOW)
    assert stale not in out and on.filter_score > off.filter_score


def test_select_top_caps_regular_and_watchlist_separately():
    cfg = load_config()
    cfg.filter.top_n = 2
    cs = [cand(i, filter_score=i / 10) for i in range(5)]
    ws = [cand(10 + i, is_watchlist=True, filter_score=i / 10) for i in range(9)]
    top = flt.select_top(cs + ws, cfg)
    assert sum(not c.is_watchlist for c in top) == 2 and sum(c.is_watchlist for c in top) == 6


# ---- judge -----------------------------------------------------------------------------
class FakeRouter:
    """Returns scores for items 1..k of each batch except those in `skip` (by n)."""

    def __init__(self, skip=()):
        self.skip = set(skip)
        self.model_list = [{"litellm_params": {"model": "fake/m"}}]
        self.calls = 0

    def completion(self, **kw):
        self.calls += 1
        user = kw["messages"][-1]["content"]
        n_items = user.count("\n    source:")
        items = [
            JudgeItem(n=n, best_topic="rag-retrieval", relevance=7, novelty=6, actionability=5,
                      rationale="r", headline="h", summary="s", example="Imagine x.",
                      why_it_matters="w").model_dump()
            for n in range(1, n_items + 1) if n not in self.skip
        ]

        class M: ...

        m = M()
        m.message = M()
        m.message.content = JudgeBatch(items=items).model_dump_json()
        r = M()
        r.choices = [m]
        r.model = "fake/m"
        return r


def test_judge_all_scores_every_item_in_batches():
    cfg = load_config()
    cfg.judge.batch_size = 3
    cs = [cand(i, judged=False) for i in range(7)]
    router = FakeRouter()
    unjudged = judge.judge_all(cs, cfg, router=router, pause_s=0)
    assert unjudged == 0 and router.calls == 3 and all(c.judged for c in cs)
    assert cs[0].final_rank > 0 and cs[0].best_topic == "rag-retrieval"


def test_judge_all_degrades_items_the_llm_skipped():
    cfg = load_config()
    cs = [cand(i, judged=False, snippet="First sentence. Second one. Third.") for i in range(3)]
    unjudged = judge.judge_all(cs, cfg, router=FakeRouter(skip={2}), pause_s=0, passes=1)
    assert unjudged == 1 and not cs[1].judged and cs[1].summary == "First sentence. Second one."


# ---- diversify + compose -----------------------------------------------------------------
def test_mmr_prefers_diverse_over_near_duplicate():
    a = cand(0, emb=[1, 0, 0, 0], rank=1.0)
    b = cand(1, emb=[0.99, 0.1, 0, 0], rank=0.98)
    c = cand(2, emb=[0, 1, 0, 0], rank=0.8)
    picked = diversify.mmr_select([a, b, c], 2, 0.5)
    assert {x.id for x in picked} == {"0", "2"}


def test_select_digest_respects_quotas_and_relevance_floor():
    cfg = load_config()
    cs = [cand(i, rank=1 - i / 20, rel=8, filter_parts={"cosine": 0.5}) for i in range(10)]
    cs.append(cand(20, rank=0.9, rel=1.0))  # below the bar
    cs.append(cand(21, rank=0.7, rel=6, is_watchlist=True))
    out = diversify.select_digest(cs, cfg)
    sections = [c.section for c in out]
    assert sections.count("core") == 5 and sections.count("watchlist") == 1
    assert sections.count("exploration") == 1 and "20" not in {c.id for c in out}


def test_compose_renders_sections_and_degraded_banner():
    c = cand(0, title="A <b>title</b>", rank=1)
    c.section, c.position, c.summary, c.why_it_matters = "core", 1, "Sum.", "Why."
    c.headline, c.example, c.best_topic = "Plain headline", "Imagine a shop.", "rag-retrieval"
    ctx = compose.build_context(
        [c], digest_date=date(2026, 10, 17), run_id="r1", degraded=True,
        topic_labels={"rag-retrieval": "AI that looks things up (RAG)"},
    )
    html, text = compose.render(ctx)
    assert "Top picks for you" in html and "unavailable" in html and "Original title: A &lt;b&gt;title&lt;/b&gt;" in html
    assert "Plain headline" in html and "Imagine a shop." in html and "AI that looks things up" in html
    assert "Why it matters: Why." in text and "Imagine a shop." in text


def test_compose_deepdive_button_alone_and_with_votes():
    c = cand(0, rank=1)
    c.section, c.position, c.summary, c.why_it_matters, c.headline = "core", 1, "S.", "W.", "H"
    kw = {"digest_date": date(2026, 10, 17), "run_id": "r1", "degraded": False}
    only = compose.build_context([c], links=lambda _c: {"deepdive": "https://app.test/?t=abc"}, **kw)
    html, text = compose.render(only)
    assert "Explain in depth" in html and "https://app.test/?t=abc" in html
    assert "More like this" not in html and "about 30 seconds" in html
    assert "Explain in depth: https://app.test/?t=abc" in text
    both = {"up": "https://w.test/f/u", "down": "https://w.test/f/d", "save": "https://w.test/f/s",
            "deepdive": "https://app.test/?t=abc"}
    html, _ = compose.render(compose.build_context([c], links=lambda _c: both, **kw))
    assert all(x in html for x in ("Explain in depth", "More like this", "Less like this", "Save for later"))
    plain, _ = compose.render(compose.build_context([c], **kw))
    assert "Explain in depth" not in plain and "about 30 seconds" not in plain


# ---- collect isolation -------------------------------------------------------------------
def test_collect_all_isolates_failing_sources(monkeypatch):
    from radar import collect as col

    def boom(*a, **k):
        raise RuntimeError("source down")

    ok = [RawItem(url="https://a.com/1", title="RAG things", source="hn")]
    monkeypatch.setattr(col.arxiv, "fetch", boom)
    monkeypatch.setattr(col.hf_papers, "fetch", lambda: ok)
    monkeypatch.setattr(col.hn, "fetch", boom)
    monkeypatch.setattr(col.github, "fetch", boom)
    monkeypatch.setattr(col.rss, "fetch", boom)
    result = col.collect_all(load_config())
    assert [i.url for i in result.items] == ["https://a.com/1"]
    assert "arxiv" in result.failed and "hn" in result.failed
    assert any(r.source == "hf_papers" and r.error is None for r in result.reports)


def test_select_top_balances_topics():
    cfg = load_config()
    cfg.filter.top_n = 10
    big = [cand(i, filter_score=0.9 - i / 100, nearest_topic="memory-context") for i in range(20)]
    small = [cand(100 + i, filter_score=0.2, nearest_topic="rag-retrieval") for i in range(3)]
    top = flt.select_top(big + small, cfg)
    topics = [c.nearest_topic for c in top]
    assert len(top) == 10
    assert topics.count("rag-retrieval") >= 2  # floor protects the smaller topic
    assert topics.count("memory-context") <= 8


def test_judge_retries_skipped_items_in_second_pass():
    class Flaky(FakeRouter):
        def completion(self, **kw):
            self.skip = {2} if self.calls == 0 else set()  # first call skips item 2
            return super().completion(**kw)

    cfg = load_config()
    cs = [cand(i, judged=False) for i in range(3)]
    router = Flaky()
    assert judge.judge_all(cs, cfg, router=router, pause_s=0) == 0
    assert all(c.judged for c in cs) and router.calls == 2


def test_mmr_topic_cap_spreads_core_across_topics():
    cs = [cand(i, rank=1 - i / 100, best_topic="agentic-systems", emb=np.eye(4)[i % 4]) for i in range(5)]
    cs += [cand(10 + i, rank=0.5, best_topic=t, emb=np.eye(4)[i % 4])
           for i, t in enumerate(["rag-retrieval", "agent-security", "memory-context"])]
    picked = diversify.mmr_select(cs, 5, 0.6, max_per_topic=2)
    topics = [diversify.topic_of(c) for c in picked]
    assert topics.count("agentic-systems") == 2 and len(set(topics)) == 4


def test_mmr_topic_cap_relaxes_when_only_one_topic_exists():
    cs = [cand(i, rank=1 - i / 10, best_topic="agentic-systems") for i in range(5)]
    assert len(diversify.mmr_select(cs, 5, 0.6, max_per_topic=2)) == 5
