"""Quality of the reader-facing text: plain language (deterministic) and faithfulness (LLM, sampled)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import psycopg
from pydantic import BaseModel

from radar import llm
from radar.plain import MAX_HEADLINE_WORDS, item_jargon, reading_grade


@dataclass
class ReaderItem:
    title: str
    snippet: str
    headline: str
    summary: str
    example: str
    why_it_matters: str


def load_recent_digest_items(conn: psycopg.Connection, n_runs: int = 10) -> list[ReaderItem]:
    rows = conn.execute(
        """
        select distinct on (d.item_id) i.title, coalesce(i.snippet, '') as snippet,
               s.headline, s.summary, coalesce(s.example, '') as example, s.why_it_matters
        from digests d
        join item_scores s on s.run_id = d.run_id and s.item_id = d.item_id
        join items i on i.id = d.item_id
        where d.run_id in (select id from runs where n_sent > 0 order by started_at desc limit %s)
          and s.judge_model is not null and s.headline is not null
        order by d.item_id
        """,
        (n_runs,),
    ).fetchall()
    return [ReaderItem(**r) for r in rows]


@dataclass
class PlainLanguageReport:
    n_items: int
    jargon_rate: float | None  # share of items with at least one unexplained jargon term
    top_terms: list[tuple[str, int]] = field(default_factory=list)
    example_ok_rate: float | None = None  # examples that start with "Imagine"
    headline_ok_rate: float | None = None  # headlines within the word limit
    reading_grade: float | None = None  # mean Flesch-Kincaid grade of an entry (lower = easier)


def plain_language(items: list[ReaderItem]) -> PlainLanguageReport:
    if not items:
        return PlainLanguageReport(n_items=0, jargon_rate=None)
    terms: Counter[str] = Counter()
    flagged = 0
    for it in items:
        found = set(item_jargon([it.headline, it.summary, it.example, it.why_it_matters]))
        terms.update(found)
        flagged += bool(found)
    n = len(items)
    grades = [g for it in items
              if (g := reading_grade(f"{it.headline}. {it.summary} {it.example} {it.why_it_matters}"))
              is not None]
    return PlainLanguageReport(
        reading_grade=sum(grades) / len(grades) if grades else None,
        n_items=n,
        jargon_rate=flagged / n,
        top_terms=terms.most_common(8),
        example_ok_rate=sum(it.example.strip().lower().startswith("imagine") for it in items) / n,
        headline_ok_rate=sum(len(it.headline.split()) <= MAX_HEADLINE_WORDS for it in items) / n,
    )


# ---- faithfulness (LLM, sampled) --------------------------------------------------------------
class Claim(BaseModel):
    claim: str
    supported: bool


class FaithfulnessCheck(BaseModel):
    claims: list[Claim]


FAITHFULNESS_SYSTEM = """You check summaries for invented facts.
List every factual claim made in SUMMARY (what was built, studied, found, measured, or released).
A claim is supported only if SOURCE states it or it is a direct paraphrase of SOURCE.
Plain-language rewording and short explanations of technical terms count as supported, as long as
they add no new facts (no new numbers, results, names, or abilities). Judge only the SUMMARY."""


@dataclass
class FaithfulnessReport:
    n_items: int
    mean_score: float | None
    unsupported: list[tuple[str, str]] = field(default_factory=list)  # (headline, claim)


def faithfulness(items: list[ReaderItem], *, router=None) -> FaithfulnessReport:
    scores, unsupported = [], []
    for it in items:
        prompt = f"SOURCE:\n{it.title}. {it.snippet[:1500]}\n\nSUMMARY:\n{it.summary}"
        try:
            res, _ = llm.complete_structured(
                prompt, FaithfulnessCheck, system=FAITHFULNESS_SYSTEM,
                name="faithfulness-check", router=router,
            )
        except Exception as e:
            print(f"[eval] faithfulness check failed for {it.headline[:50]!r}: {str(e)[:120]}")
            continue
        if not res.claims:
            scores.append(1.0)
            continue
        ok = sum(c.supported for c in res.claims)
        scores.append(ok / len(res.claims))
        unsupported += [(it.headline, c.claim) for c in res.claims if not c.supported]
    return FaithfulnessReport(
        n_items=len(scores),
        mean_score=sum(scores) / len(scores) if scores else None,
        unsupported=unsupported,
    )


# ---- variety between entries (D-043) -------------------------------------------------------------
_STOP = {"the", "a", "an", "to", "of", "and", "in", "it", "that", "is", "for", "can", "on", "with", "its",
         "this", "by", "or", "as", "be", "are", "from", "they", "so", "their", "when", "how", "what", "at",
         "you", "your", "if"}


def load_recent_digests(conn: psycopg.Connection, n_runs: int = 5) -> list[list[ReaderItem]]:
    """The entries of each of the last n digests (one list per run), for cross-entry checks."""
    runs = conn.execute(
        "select r.id from runs r where r.n_sent > 0 and exists (select 1 from item_scores s "
        "where s.run_id = r.id and s.headline is not null) order by r.started_at desc limit %s",
        (n_runs,),
    ).fetchall()
    out = []
    for run in runs:
        rows = conn.execute(
            """select i.title, coalesce(i.snippet, '') as snippet, s.headline, s.summary,
                      coalesce(s.example, '') as example, s.why_it_matters
               from digests d join item_scores s on s.run_id = d.run_id and s.item_id = d.item_id
               join items i on i.id = d.item_id
               where d.run_id = %s and s.judge_model is not null order by d.section, d.position""",
            (run["id"],),
        ).fetchall()
        if len(rows) >= 2:
            out.append([ReaderItem(**r) for r in rows])
    return out


@dataclass
class VarietyReport:
    n_digests: int
    written_similarity: float | None = None  # mean pairwise similarity of the written entries
    source_similarity: float | None = None  # same for the original title + abstract
    shared_openings: float | None = None  # avg headlines per digest sharing their first 2 words
    repeated_phrases: list[tuple[str, int]] = field(default_factory=list)  # 2-word phrases in 3+ entries

    @property
    def sameness_gap(self) -> float | None:
        """> 0 means the writing made entries MORE alike than the sources they describe."""
        if self.written_similarity is None or self.source_similarity is None:
            return None
        return self.written_similarity - self.source_similarity


def _pairwise(texts: list[str]) -> float:
    from radar.embed import embed_texts

    v = embed_texts(texts)
    s = v @ v.T
    n = len(texts)
    return float((s.sum() - n) / (n * n - n))


def _bigrams(text: str) -> set[str]:
    words = [w for w in re.findall(r"[a-z']+", text.lower()) if w not in _STOP]
    return {" ".join(words[i:i + 2]) for i in range(len(words) - 1)}


def variety(digests: list[list[ReaderItem]]) -> VarietyReport:
    if not digests:
        return VarietyReport(n_digests=0)
    written, source, openings = [], [], []
    phrases: Counter[str] = Counter()
    for items in digests:
        written.append(_pairwise([f"{i.headline} {i.summary} {i.example} {i.why_it_matters}" for i in items]))
        source.append(_pairwise([f"{i.title}. {i.snippet[:600]}" for i in items]))
        starts = Counter(" ".join(i.headline.lower().split()[:2]) for i in items)
        openings.append(sum(n for n in starts.values() if n > 1))
        per_digest: Counter[str] = Counter()
        for i in items:
            per_digest.update(_bigrams(f"{i.headline} {i.summary} {i.example} {i.why_it_matters}"))
        phrases.update({p: n for p, n in per_digest.items() if n >= 3})
    k = len(digests)
    return VarietyReport(
        n_digests=k,
        written_similarity=sum(written) / k,
        source_similarity=sum(source) / k,
        shared_openings=sum(openings) / k,
        repeated_phrases=sorted(phrases.items(), key=lambda kv: (-kv[1], kv[0]))[:6],
    )
