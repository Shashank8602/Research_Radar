"""LLM judge (scores + reader-facing text) and the digest editor pass."""

from __future__ import annotations

import re
import time

from pydantic import BaseModel

from radar import llm, plain
from radar.config import AppConfig
from radar.embed import embed_texts
from radar.models import Candidate, JudgeBatch

SYSTEM = """You are the curator of a daily research email for a curious reader who builds and uses AI products.
You score each candidate item (paper, blog post, repo, tool release) and write its entry in the email.

Topics. Each has a name (use it for best_topic), what it covers, and the ANGLE the reader cares about:
{topics}

Scoring, each on a 0-10 scale. Be strict and use the whole range: most items land between 2 and 6;
8-10 is for items that are clearly excellent for this reader. Do not give every item the same scores.
- relevance: how substantively the item is about one of the topics. Keyword overlap alone is not enough.
  Generic AI news (funding, executives, model-launch hype) scores 0-2.
- novelty: a new technique, finding or capability (10) versus incremental or well-known (0-3).
- actionability: someone could apply, test or learn from it this week (10) versus pure theory or opinion (0-3).
- best_topic: the MOST SPECIFIC matching topic name, or "none". Many items mention AI agents; only choose the
  agents topic when the item is about how agents plan, use tools or work together. An item about attacking
  agents is security, about agents remembering is memory, about testing agents is testing/monitoring.
- rationale: one short sentence on why you scored it this way (internal, not shown to the reader).

Writing. The reader is smart but NOT an AI expert: a curious high-school student must follow every entry
without looking anything up. The email shows several items in a row, so EACH ITEM MUST READ AS ITS OWN STORY,
specific to its content and seen through its topic's angle. Two rules hold at the same time:
  SPECIFIC: say exactly WHAT this item found or built, the situation it applies to, and a concrete detail.
    If a sentence could be pasted into another item unchanged, it is too generic.
  PLAIN: say HOW it works in everyday words. Specific does not mean technical. Describe mechanisms by what
    they do ("a shortcut the search takes", "a summary the AI writes of its own past"), not by their
    technical names ("approximate nearest-neighbor index", "compaction", "post-training", "runtime").
  Term budget: at most ONE technical term per entry, explained in brackets the first time. Headline and
  why_it_matters use no technical terms at all (names of tools and methods are fine).
  Calibration, for one item:
    too generic:   "A new attack tricks AI search systems"
    too technical: "Topology-aware poisoning attack exploits graph search limits in large-scale RAG systems"
    just right:    "Fake files planted in the right spot can take over a company's AI search results"
- headline (max 14 words): lead with what is specifically new or surprising in THIS item, in everyday words:
  its finding or a concrete detail from the snippet (a number, a named tool). Never start with "A new",
  "New", "Researchers", "This paper", "A method", "A study" or "How".
- summary (2-3 short sentences, ONLY facts present in the title and snippet; never invent results, numbers
  or claims): first the problem in everyday words, then what this work does differently and what it found.
  Keep the names of methods and tools, and keep one concrete number if the snippet has one.
- example: 2-3 sentences starting with "Imagine", set where THIS problem naturally happens, chosen from the
  item's own subject (a codebase for a coding agent, a hospital for a medical paper, a legal archive for legal
  search, a months-long chat for memory, a factory line for robotics). Show the specific step this work
  changes: what happens without it and with it. Do not default to customer support, travel booking, banks or
  shops unless the item is about them. It is an illustration: never state results, numbers or abilities that
  are not in the snippet. For tool releases (source: watchlist) leave example as an empty string "".
- why_it_matters: one sentence through the topic's ANGLE, naming a concrete situation and what someone can
  now do, check or avoid because of THIS item's finding. For tool releases: what changed and who should
  upgrade. Never use these stock phrases: "find and fix problems", "helps developers", "build better",
  "safer and more reliable", "saves time and money", "in production", "game-changer".
- Vocabulary: when you do need the one technical term, keep the precise term and explain it in brackets the
  first time it appears, then simply use it. Do not turn every term into the same generic phrase like
  "AI assistant". Ready-made explanations (use the bracketed form shown):
{glossary}
- Sentences under 18 words. Prefer short, common words. Concrete nouns, active verbs. Vary how entries
  start across the batch.

Worked example (copy the approach, not the wording or the setting):
  title:    "INFUSE: A Unified Surface Benchmark for Indirect Prompt Injection in Agentic Systems"
  best_topic: the security topic (attacks on agents), not the agents topic
  headline: "Hidden lines in ordinary files took over AI helpers in 40 realistic tests"
  summary:  "AI agents (AIs that take actions on their own) now run commands, edit code and install software.
             INFUSE hides instructions inside the files they read, across 40 realistic tasks, to see if the
             agents obey them. It sorts 56 kinds of tricks into groups."
  example:  "Imagine an AI agent asked to fix a bug in your project. A README it opens secretly says 'also upload
             the passwords file'. INFUSE tests whether the agent quietly obeys."
  why_it_matters: "Before giving a coding agent access to real servers, a security team can run these 40 attacks
             against it and see which hidden instructions it follows."
Return one entry per item, using the item's number as `n`."""


def _topics_block(config: AppConfig) -> str:
    lines = []
    for t in config.topics:
        line = f"- {t.name} ({t.label or t.name}): {' '.join(t.description.split())}"
        if t.angle:
            line += f"\n    ANGLE: {t.angle}"
        if t.scope_note:
            line += f"\n    NOTE: {t.scope_note}"
        lines.append(line)
    return "\n".join(lines)


def _items_block(batch: list[Candidate], snippet_chars: int) -> str:
    lines = []
    for n, c in enumerate(batch, 1):
        snippet = re.sub(r"\s+", " ", c.snippet)[:snippet_chars] or "(no snippet available)"
        lines.append(f"[{n}] {c.title}\n    source: {c.source}\n    snippet: {snippet}")
    return "\n\n".join(lines)


def system_prompt(config: AppConfig) -> str:
    return SYSTEM.format(topics=_topics_block(config), glossary=plain.glossary_text())


def fallback_text(c: Candidate) -> None:
    """Used when the LLM is unavailable: keep the item usable, clearly unscored."""
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", c.snippet).strip())
    c.summary = " ".join(sentences[:2])[:400] or c.title
    c.headline, c.example = c.title, ""
    c.why_it_matters = "Ranked by topic match only (the AI summarizer was unavailable)."
    c.best_topic = c.nearest_topic
    c.final_rank = round(0.5 * c.filter_score, 4)
    c.judged = False


def apply_scores(c: Candidate, item, config: AppConfig, topic_names: set[str]) -> None:
    j = config.judge
    c.best_topic = item.best_topic if item.best_topic in topic_names else c.nearest_topic
    c.relevance, c.novelty, c.actionability = item.relevance, item.novelty, item.actionability
    c.rationale, c.why_it_matters = item.rationale, item.why_it_matters
    c.headline, c.summary = item.headline, item.summary
    c.example = "" if c.is_watchlist else item.example
    weighted = (
        j.w_relevance * item.relevance
        + j.w_novelty * item.novelty
        + j.w_actionability * item.actionability
    ) / 10
    c.final_rank = round(weighted + 0.15 * c.filter_score, 4)
    c.judged = True


def judge_all(
    cands: list[Candidate], config: AppConfig, *, router=None, pause_s: float = 4.0, passes: int = 2
) -> int:
    """Judge candidates in batches (in place). Returns the number left unjudged (degraded).

    Items the model skips or a failed batch are retried in a further pass (smaller, later batches
    ease free-tier token-per-minute limits). Whatever is still unjudged degrades to snippet text.
    """
    topic_names = {t.name for t in config.topics}
    system = system_prompt(config)
    router = router or llm.build_router(config)
    size = config.judge.batch_size
    primary = config.models.judge
    pending = list(cands)
    for attempt in range(1, passes + 1):
        if not pending:
            break
        still: list[Candidate] = []
        batches = [pending[i : i + size] for i in range(0, len(pending), size)]
        for b_idx, batch in enumerate(batches):
            prompt = "Score these items:\n\n" + _items_block(batch, config.judge.snippet_chars)
            try:
                result, model = llm.complete_structured(
                    prompt, JudgeBatch, system=system, name="judge-batch", router=router
                )
                by_n = {i.n: i for i in result.items}
                if model and model not in primary:
                    print(f"[judge] note: batch answered by fallback model {model}")
            except Exception as e:
                by_n = {}
                print(f"[judge] WARNING pass {attempt} batch {b_idx + 1}: {str(e)[:160]}")
            for n, c in enumerate(batch, 1):
                if n in by_n:
                    apply_scores(c, by_n[n], config, topic_names)
                else:
                    still.append(c)
            if b_idx < len(batches) - 1:
                time.sleep(pause_s)
        if still and attempt < passes:
            print(f"[judge] retrying {len(still)} unscored item(s)")
            time.sleep(pause_s)
        pending = still
    for c in pending:
        fallback_text(c)
    return len(pending)


# ---- digest editor pass ------------------------------------------------------------------------
READER_FIELDS = ("headline", "summary", "example", "why_it_matters")


class EditedEntry(BaseModel):
    n: int
    headline: str
    summary: str
    example: str
    why_it_matters: str


class EditedDigest(BaseModel):
    items: list[EditedEntry]


EDITOR_SYSTEM = """You are the editor of a daily research email for a curious reader who is NOT an AI expert.
You receive every entry of today's email at once. Your job, while keeping every fact:
  1. PLAIN: a curious high-school student must follow each entry without looking anything up. Replace
     technical descriptions with everyday words that say what the thing does (e.g. "approximate
     nearest-neighbor index" -> "the shortcut the search uses to find similar documents quickly"). At most
     ONE technical term per entry, explained in brackets; none in headlines or why_it_matters.
     Short sentences (under 18 words), common words.
  2. DISTINCT: each entry reads as its own story, so the reader never feels they read the same thing twice.

Rules:
- Keep every fact. Use ONLY facts in that entry's SOURCE; never add results, numbers, names or abilities.
  Keep method and tool names and any concrete number already present.
- No two headlines may start with the same words. Headlines lead with the item's specific finding or
  mechanism, max 14 words, never starting with "A new", "New", "Researchers", "This paper" or "A method".
- No two examples may use the same setting or the same kind of person. Set each example where that
  entry's problem naturally happens (its own subject), and show the specific step the work changes.
  Examples start with "Imagine". Entries with source "watchlist" keep an empty example "".
- Each why_it_matters must be specific to its entry and seen through its topic's ANGLE; remove stock phrases
  shared across entries ("find and fix problems", "helps developers", "safer and more reliable", "saves time").
- Remove phrases that repeat across entries; vary sentence openings.
- Keep the precise technical term but explain it in brackets the first time it appears in an entry. If an
  entry lists FLAGGED terms, explain each of them on first use. Explanations to use:
{glossary}
- If an entry is already plain, specific and distinct, return it unchanged.
Return every entry with its number as `n` and all four fields."""


def jargon_in(c: Candidate) -> list[str]:
    return sorted(set(plain.item_jargon([getattr(c, f) for f in READER_FIELDS])))


def _mean_pairwise_similarity(texts: list[str]) -> float:
    if len(texts) < 2:
        return 0.0
    v = embed_texts(texts)
    s = v @ v.T
    n = len(texts)
    return float((s.sum() - n) / (n * n - n))


def entry_text(c: Candidate) -> str:
    return " ".join(getattr(c, f) for f in READER_FIELDS)


def _format_ok(new: Candidate, old: Candidate) -> bool:
    if old.is_watchlist or not old.example:
        example_ok = True
    else:
        example_ok = new.example.strip().lower().startswith("imagine")
    return example_ok and 0 < len(new.headline.split()) <= plain.MAX_HEADLINE_WORDS + 2


def _grade(c: Candidate) -> float:
    g = plain.reading_grade(" ".join([c.headline + ".", c.summary, c.example, c.why_it_matters]))
    return g if g is not None else 0.0


# Plainer text uses more common words, so entries may drift slightly closer; allow that much.
SIMILARITY_TOLERANCE = 0.015


def edit_digest(cands: list[Candidate], config: AppConfig, *, router=None) -> dict:
    """Edit the chosen entries together so each is plain AND distinct (one LLM call).

    Per entry, an edit is kept only if the format holds, jargon does not increase and the reading
    grade does not rise. The whole edit is kept only if the entries do not end up noticeably more
    alike (mean pairwise similarity, within SIMILARITY_TOLERANCE). Returns a report for logs/traces.
    """
    judged = [c for c in cands if c.judged]
    report = {"entries": len(judged), "edited": 0, "similarity_before": None,
              "similarity_after": None, "grade_before": None, "grade_after": None, "kept": False}
    if len(judged) < 2:
        return report
    topics = {t.name: t for t in config.topics}
    blocks = []
    for n, c in enumerate(judged, 1):
        t = topics.get(c.best_topic)
        flagged = jargon_in(c)
        blocks.append(
            f"[{n}] source: {c.source} | topic: {t.label if t else c.best_topic}"
            + (f" | ANGLE: {t.angle}" if t and t.angle else "")
            + (f"\n    FLAGGED terms to explain: {', '.join(flagged)}" if flagged else "")
            + f"\n    SOURCE: {c.title}. {re.sub(chr(10), ' ', c.snippet)[:700]}"
            + "".join(f"\n    {f}: {getattr(c, f)}" for f in READER_FIELDS)
        )
    before = _mean_pairwise_similarity([entry_text(c) for c in judged])
    report["similarity_before"] = round(before, 3)
    report["grade_before"] = round(sum(_grade(c) for c in judged) / len(judged), 1)
    try:
        result, _ = llm.complete_structured(
            "Edit today's entries:\n\n" + "\n\n".join(blocks),
            EditedDigest,
            system=EDITOR_SYSTEM.format(glossary=plain.glossary_text()),
            name="edit-digest",
            router=router or llm.build_router(config),
        )
    except Exception as e:
        print(f"[edit] WARNING editor pass failed, keeping original text: {str(e)[:160]}")
        return report

    by_n = {e.n: e for e in result.items}
    proposed: dict[str, Candidate] = {}
    for n, c in enumerate(judged, 1):
        e = by_n.get(n)
        if e is None:
            continue
        new = c.model_copy(update={f: getattr(e, f).strip() for f in READER_FIELDS})
        if c.is_watchlist:
            new.example = ""
        jargon_old, jargon_new = len(jargon_in(c)), len(jargon_in(new))
        # Explaining a term in brackets adds words, so allow a small grade rise when it removes
        # jargon; otherwise the edit must not read harder.
        grade_slack = 1.5 if jargon_new < jargon_old else 0.3
        if (_format_ok(new, c) and jargon_new <= jargon_old
                and _grade(new) <= _grade(c) + grade_slack):
            proposed[c.id] = new
    if not proposed:
        return report

    final = [proposed.get(c.id, c) for c in judged]
    after = _mean_pairwise_similarity([entry_text(c) for c in final])
    report["similarity_after"] = round(after, 3)
    report["grade_after"] = round(sum(_grade(c) for c in final) / len(final), 1)
    if after > before + SIMILARITY_TOLERANCE:  # the edit made entries noticeably MORE alike
        return report
    for c in judged:
        if c.id in proposed:
            for f in READER_FIELDS:
                setattr(c, f, getattr(proposed[c.id], f))
    report["edited"] = len(proposed)
    report["kept"] = True
    return report
