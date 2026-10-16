"""`radar-eval`: offline evaluation report and CI gate.

    uv run radar-eval                     # ablation + judge calibration + plain-language checks
    uv run radar-eval --faithfulness 10   # + LLM check that 10 recent summaries invent nothing
    uv run radar-eval --check-models      # + verify pinned model IDs still exist
    uv run radar-eval --gate              # exit 1 if a threshold in topics.yaml `evals:` fails

Everything except --faithfulness replays stored data: no LLM calls, no tokens spent.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import date

from radar import db, tracing
from radar.config import ROOT, AppConfig, get_env, load_config
from radar.evals import ablation, quality
from radar.evals.dataset import Example, load_examples, unique_items
from radar.evals.models_check import ModelStatus, check_models
from radar.personalize import Votes, load_votes

REPORT_PATH = ROOT / "evals" / "reports" / "latest.md"


@dataclass
class EvalResult:
    examples: list[Example]
    votes: int
    ablation: list[ablation.AblationRow]
    calibration: list[ablation.CalibrationRow]
    judge_auc: float | None
    plain: quality.PlainLanguageReport
    variety: quality.VarietyReport | None = None
    faithfulness: quality.FaithfulnessReport | None = None
    models: list[ModelStatus] = field(default_factory=list)
    gate_failures: list[str] = field(default_factory=list)
    gate_skipped_reason: str | None = None


def _fmt(x: float | None, pct: bool = False) -> str:
    if x is None:
        return "–"
    return f"{x:.0%}" if pct else f"{x:.2f}"


def compute(conn, config: AppConfig, *, faithfulness_n: int = 0, models: bool = False,
            env=None) -> EvalResult:
    examples = load_examples(conn)
    votes: Votes = load_votes(conn)
    calib, auc = ablation.judge_calibration(examples, config)
    reader_items = quality.load_recent_digest_items(conn)
    result = EvalResult(
        examples=examples,
        votes=len(votes),
        ablation=ablation.run_ablation(examples, config, votes) if examples else [],
        calibration=calib,
        judge_auc=auc,
        plain=quality.plain_language(reader_items),
        variety=quality.variety(quality.load_recent_digests(conn)),
    )
    if faithfulness_n and reader_items:
        sample = random.Random(0).sample(reader_items, min(faithfulness_n, len(reader_items)))
        result.faithfulness = quality.faithfulness(sample)
    if models:
        result.models = check_models(config, env or get_env())
    return result


def apply_gate(r: EvalResult, config: AppConfig) -> None:
    g = config.evals
    r.gate_failures = [f"model {m.model}: {m.detail}" for m in r.models if not m.ok]
    if r.plain.jargon_rate is not None and r.plain.jargon_rate > g.max_jargon_rate:
        r.gate_failures.append(
            f"jargon rate {r.plain.jargon_rate:.0%} > {g.max_jargon_rate:.0%}"
        )
    if r.faithfulness and r.faithfulness.mean_score is not None \
            and r.faithfulness.mean_score < g.min_faithfulness:
        r.gate_failures.append(
            f"faithfulness {r.faithfulness.mean_score:.0%} < {g.min_faithfulness:.0%}"
        )
    if r.plain.reading_grade is not None and r.plain.reading_grade > g.max_reading_grade:
        r.gate_failures.append(
            f"reading grade {r.plain.reading_grade:.1f} > {g.max_reading_grade:g}"
        )
    gap = r.variety.sameness_gap if r.variety else None
    if gap is not None and gap > g.max_sameness_gap:
        r.gate_failures.append(
            f"writing makes entries more alike than their sources (+{gap:.2f} > +{g.max_sameness_gap:.2f})"
        )
    n_labels = len(unique_items(r.examples))
    if n_labels < g.min_labels_for_gate:
        r.gate_skipped_reason = (
            f"ranking gate skipped: {n_labels} labels < {g.min_labels_for_gate} needed"
        )
        return
    current = next((row for row in r.ablation if row.ranker == ablation.CURRENT), None)
    if current and current.p5_pooled is not None and current.p5_pooled < g.min_precision_at_5:
        r.gate_failures.append(f"precision@5 {current.p5_pooled:.0%} < {g.min_precision_at_5:.0%}")


def render(r: EvalResult, config: AppConfig) -> str:
    items = unique_items(r.examples)
    n_rel = sum(e.label for e in items)
    days = len({e.day for e in r.examples})
    out = [f"# Research Radar evals ({date.today().isoformat()})", ""]
    out += [f"**Labels:** {len(items)} items ({n_rel} relevant, {len(items) - n_rel} not) across "
            f"{days} digest day(s). **Votes:** {r.votes}.", ""]

    out += ["## Ranking ablation", ""]
    if not r.examples:
        out += ["No labels yet. Label items on the dev console's **Labeling** page "
                "(`uv run streamlit run devui/app.py`), then re-run.", ""]
    else:
        out += ["Higher is better. P@5 = share of the top 5 that you labeled relevant.", "",
                "| Ranker | P@5 per day | days | P@5 pooled | P@10 pooled | Avg precision | ROC-AUC |",
                "|---|---|---|---|---|---|---|"]
        for a in r.ablation:
            out.append(f"| {a.ranker} | {_fmt(a.p5_per_day, True)} | {a.days_used} | "
                       f"{_fmt(a.p5_pooled, True)} | {_fmt(a.p10_pooled, True)} | "
                       f"{_fmt(a.avg_precision)} | {_fmt(a.roc_auc)} |")
        if r.votes < config.personalize.min_votes:
            out.append(f"\nVote-based rows appear once there are {config.personalize.min_votes}+ votes "
                       f"(currently {r.votes}).")
        out += ["", "_Labels come from items that reached the judge, so these rankers are compared "
                "within the daily shortlist. Small samples are noisy: check the label counts._", ""]

    out += ["## LLM judge vs your labels", ""]
    if not r.calibration or r.calibration[0].n == 0:
        out += ["Needs labels.", ""]
    else:
        out += [f"Judged labeled items: {r.calibration[0].n}. ROC-AUC of the relevance score: "
                f"{_fmt(r.judge_auc)}.", "",
                "| Relevance ≥ | Precision | Recall | F1 | Cohen's κ |", "|---|---|---|---|---|"]
        for c in r.calibration:
            mark = " ← current cutoff" if c.is_current else ""
            out.append(f"| {c.threshold:g}{mark} | {_fmt(c.precision, True)} | {_fmt(c.recall, True)} | "
                       f"{_fmt(c.f1)} | {_fmt(c.kappa)} |")
        out.append("")

    p = r.plain
    out += ["## Plain language (recent digests)", ""]
    if not p.n_items:
        out += ["No digests with plain-language fields yet.", ""]
    else:
        terms = ", ".join(f"{t} ({n})" for t, n in p.top_terms) or "none"
        out += [f"- Items checked: {p.n_items}",
                f"- Reading level (Flesch-Kincaid grade, lower = easier): {_fmt(p.reading_grade)} "
                f"(limit {config.evals.max_reading_grade:g}; ~8 = easy for most adults, 12 = end of high school)",
                f"- Items with unexplained jargon: {_fmt(p.jargon_rate, True)} "
                f"(limit {config.evals.max_jargon_rate:.0%}). Most common: {terms}",
                f"- Examples that start with \"Imagine\": {_fmt(p.example_ok_rate, True)}",
                f"- Headlines within {quality.MAX_HEADLINE_WORDS} words: {_fmt(p.headline_ok_rate, True)}", ""]

    v = r.variety
    if v and v.n_digests:
        out += ["## Variety between entries (recent digests)", "",
                f"- Digests checked: {v.n_digests}",
                f"- How alike the entries are (0-1, lower = more varied): written {_fmt(v.written_similarity)} "
                f"vs their sources {_fmt(v.source_similarity)}. Gap {v.sameness_gap:+.2f} "
                f"(limit +{config.evals.max_sameness_gap:.2f}; above 0 means the writing adds sameness)",
                f"- Headlines per digest that share their first two words with another: {v.shared_openings:.1f}",
                "- Phrases repeated across 3+ entries of a digest: "
                + (", ".join(f'"{p}" ({n})' for p, n in v.repeated_phrases) or "none"), ""]

    if r.faithfulness:
        f = r.faithfulness
        out += ["## Faithfulness (LLM check on a sample)", "",
                f"Summaries checked: {f.n_items}. Share of claims supported by the source: "
                f"{_fmt(f.mean_score, True)} (minimum {config.evals.min_faithfulness:.0%}).", ""]
        for headline, claim in f.unsupported[:10]:
            out.append(f"- Unsupported in \"{headline[:70]}\": {claim}")
        out.append("")

    if r.models:
        out += ["## Pinned model IDs", ""]
        out += [f"- {'OK' if m.ok else 'FAIL'} `{m.model}`: {m.detail}" for m in r.models]
        out.append("")

    out += ["## Gate", ""]
    if r.gate_skipped_reason:
        out.append(f"- {r.gate_skipped_reason}")
    out += [f"- FAIL: {msg}" for msg in r.gate_failures] or ["- All checked thresholds pass."]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate Research Radar against your labels.")
    ap.add_argument("--faithfulness", type=int, default=0, metavar="N",
                    help="LLM-check N recent summaries for invented facts (spends tokens)")
    ap.add_argument("--check-models", action="store_true", help="verify pinned model IDs exist")
    ap.add_argument("--gate", action="store_true", help="exit 1 if a threshold fails")
    ap.add_argument("--out", default=str(REPORT_PATH), help="where to write the markdown report")
    args = ap.parse_args()

    config, env = load_config(), get_env()
    if args.faithfulness:
        tracing.init(env)
    try:
        with tracing.eval_trace({"faithfulness_n": args.faithfulness, "gate": args.gate}) as span, \
                db.connect() as conn:
            r = compute(conn, config, faithfulness_n=args.faithfulness, models=args.check_models, env=env)
            apply_gate(r, config)
            span.update(output={"labels": len(unique_items(r.examples)), "votes": r.votes,
                                "gate_failures": r.gate_failures})
    finally:
        tracing.flush()

    report = render(r, config)
    from pathlib import Path

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    print(f"[eval] report written to {out}")
    if args.gate and r.gate_failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
