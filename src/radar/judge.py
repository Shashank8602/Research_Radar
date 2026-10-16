"""LLM judge: score relevance / novelty / actionability and write the summary text."""

from __future__ import annotations

import re
import time

from radar import llm
from radar.config import AppConfig
from radar.models import Candidate, JudgeBatch

SYSTEM = """You are a research curator for a GenAI engineer who builds production RAG and agent systems.
You score candidate items (papers, posts, repos, releases) against the reader's topics.

Topics (name: description):
{topics}

Scoring rules, each on a 0-10 scale. Be strict and use the whole range: most items should land between 2 and 6,
and 8-10 is reserved for items that are clearly excellent for this reader. Avoid giving the same score to every item.
- relevance: how substantively the item is about one of the topics. Keyword overlap alone is not enough.
  Generic AI news (funding, executives, model-launch hype) scores 0-2.
- novelty: a new technique, finding or capability (10) versus incremental or well-known (0-3).
- actionability: an engineer could apply, test or learn from it this week (10) versus pure theory or opinion (0-3).

Writing rules:
- best_topic must be exactly one topic name above, or "none".
- rationale: one sentence on why you scored it this way.
- summary: at most 2 sentences, using ONLY facts present in the title and snippet. Never invent results, numbers, or claims.
- why_it_matters: one sentence addressed to the reader about what they could do with it.
Return one entry per item, using the item's number as `n`."""


def _topics_block(config: AppConfig) -> str:
    return "\n".join(f"- {t.name}: {' '.join(t.description.split())}" for t in config.topics)


def _items_block(batch: list[Candidate], snippet_chars: int) -> str:
    lines = []
    for n, c in enumerate(batch, 1):
        snippet = re.sub(r"\s+", " ", c.snippet)[:snippet_chars] or "(no snippet available)"
        lines.append(f"[{n}] {c.title}\n    source: {c.source}\n    snippet: {snippet}")
    return "\n\n".join(lines)


def fallback_text(c: Candidate) -> None:
    """Used when the LLM is unavailable: keep the item usable, clearly unscored."""
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", c.snippet).strip())
    c.summary = " ".join(sentences[:2])[:400] or c.title
    c.why_it_matters = "Ranked by topic match only (LLM judge unavailable)."
    c.best_topic = c.nearest_topic
    c.final_rank = round(0.5 * c.filter_score, 4)
    c.judged = False


def apply_scores(c: Candidate, item, config: AppConfig, topic_names: set[str]) -> None:
    j = config.judge
    c.best_topic = item.best_topic if item.best_topic in topic_names else c.nearest_topic
    c.relevance, c.novelty, c.actionability = item.relevance, item.novelty, item.actionability
    c.rationale, c.summary, c.why_it_matters = item.rationale, item.summary, item.why_it_matters
    weighted = (
        j.w_relevance * item.relevance
        + j.w_novelty * item.novelty
        + j.w_actionability * item.actionability
    ) / 10
    c.final_rank = round(weighted + 0.15 * c.filter_score, 4)
    c.judged = True


def judge_all(
    cands: list[Candidate], config: AppConfig, *, router=None, pause_s: float = 1.0
) -> int:
    """Judge candidates in batches (in place). Returns the number left unjudged (degraded)."""
    topic_names = {t.name for t in config.topics}
    system = SYSTEM.format(topics=_topics_block(config))
    router = router or llm.build_router(config)
    size = config.judge.batch_size
    unjudged = 0
    for start in range(0, len(cands), size):
        batch = cands[start : start + size]
        prompt = "Score these items:\n\n" + _items_block(batch, config.judge.snippet_chars)
        try:
            result, _model = llm.complete_structured(
                prompt, JudgeBatch, system=system, name="judge-batch", router=router
            )
            by_n = {i.n: i for i in result.items}
        except Exception:
            by_n = {}
        for n, c in enumerate(batch, 1):
            if n in by_n:
                apply_scores(c, by_n[n], config, topic_names)
            else:
                fallback_text(c)
                unjudged += 1
        if start + size < len(cands):
            time.sleep(pause_s)
    return unjudged
