"""Plain-language rules shared by the judge prompt, the editor pass and the evals (D-030, D-043).

One glossary, one checker: whatever the evals flag as jargon is exactly what the pipeline fixes.

Policy: a technical term is fine once it has been explained in brackets in the same item
("AI agent (an AI that takes actions on its own)"); after that the precise term is used. Replacing
every term with the same generic phrase ("AI assistant") made all items read alike (D-043).
"""

from __future__ import annotations

import re

MAX_HEADLINE_WORDS = 14

# term -> short plain explanation to put in brackets the first time the term appears.
GLOSSARY: list[tuple[str, str]] = [
    ("language model (LLM)", "the kind of AI behind chatbots like ChatGPT"),
    ("AI agent", "an AI that takes actions on its own, like searching, booking or running code"),
    ("multi-agent system", "several AI agents splitting up a job"),
    ("prompt injection", "hidden instructions that trick an AI into doing something it shouldn't"),
    ("jailbreak", "tricking an AI into breaking its own rules"),
    ("benchmark", "a standard test that scores AI systems"),
    ("context window", "the amount of text an AI can keep in mind at once"),
    ("tokens", "the chunks of text an AI reads and writes, which you pay for"),
    ("RAG", "letting an AI look things up in documents before it answers"),
    ("reranker", "a second pass that puts the best search results first"),
    ("embedding", "a list of numbers that captures what a text means"),
    ("fine-tuning", "extra training on examples for a specific job"),
    ("reinforcement learning", "learning by trial and error, with rewards for good results"),
    ("latency", "how long the AI takes to answer"),
    ("guardrails", "rules that block unsafe inputs or outputs"),
    ("sandbox", "an isolated space where code runs without touching anything important"),
    ("hallucination", "the AI confidently stating things that aren't true"),
    ("tracing", "recording each step an AI takes so problems can be traced"),
    ("memory compaction", "squeezing old conversation into a short summary to save space"),
]
# Vague words that add no meaning; never needed, so never "explained", just avoided.
ALSO_AVOID = ["framework", "paradigm", "novel", "leverage", "SOTA", "orchestration", "pipeline",
              "scalable", "robust", "workflow", "seamless", "cutting-edge", "game-changer"]

# What the checker flags (plural forms included where common).
JARGON = [
    "LLM", "LLMs", "language model", "language models", "agentic", "multi-agent",
    "prompt injection", "jailbreak", "benchmark", "benchmarks", "taxonomy", "token", "tokens",
    "context window", "long-horizon", "multi-turn", "RAG", "retrieval", "reranker", "embedding",
    "embeddings", "vector", "fine-tuning", "inference", "latency", "guardrail", "guardrails",
    "sandbox", "hallucination", "hallucinating", "observability", "training-free",
    "reinforcement learning", "compaction", *ALSO_AVOID,
]
_JARGON_RE = [(t, re.compile(rf"(?<![\w-]){re.escape(t)}(?![\w-])", re.IGNORECASE)) for t in JARGON]


def glossary_text(indent: str = "    ") -> str:
    width = max(len(j) for j, _ in GLOSSARY)
    lines = [f'{indent}{j.ljust(width)}  e.g. "{j.split(" (")[0]} ({p})"' for j, p in GLOSSARY]
    lines.append(f"{indent}Never use these vague words: {', '.join(ALSO_AVOID)}.")
    return "\n".join(lines)


_EXPLAINED_AFTER = re.compile(r"^(?:\s+[\w-]+){0,3}\s*\(")  # up to 3 words, then "("


def _explained(text: str, m: re.Match) -> bool:
    """'RAG (letting...)', 'multi-agent systems (several...)', or '...look things up (RAG)'."""
    before = text[max(0, m.start() - 1): m.start()]
    return before == "(" or bool(_EXPLAINED_AFTER.match(text[m.end(): m.end() + 60]))


def item_jargon(fields: list[str]) -> list[str]:
    """Terms used in an item (all its fields, in reading order) that are never explained in it.
    A term is explained when it is immediately followed by '(' ("RAG (letting an AI look things
    up)") or sits inside brackets after the plain wording ("...look things up (RAG)")."""
    text = "\n".join(f or "" for f in fields)
    flagged = []
    for term, pat in _JARGON_RE:
        hits = list(pat.finditer(text))
        if hits and not any(_explained(text, m) for m in hits):
            flagged.append(term.lower())
    return flagged


# ---- reading level ------------------------------------------------------------------------------
def _syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(1, n)


def reading_grade(text: str) -> float | None:
    """Flesch-Kincaid grade level (approx. US school grade needed to follow the text).
    ~8 = easy for most adults, 12 = high-school senior, 16+ = academic."""
    sentences = [s for s in re.split(r"[.!?]+(?:\s|$)", text or "") if s.strip()]
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text or "")
    if not sentences or not words:
        return None
    syl = sum(_syllables(w) for w in words)
    return 0.39 * (len(words) / len(sentences)) + 11.8 * (syl / len(words)) - 15.59
