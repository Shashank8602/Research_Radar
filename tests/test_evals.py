from datetime import date

import numpy as np
import pytest

from radar import judge, personalize, plain
from radar.config import Env, load_config
from radar.evals import ablation, cli, metrics, models_check, quality
from radar.evals.dataset import Example, by_day, unique_items
from radar.models import Candidate


# ---- metrics -----------------------------------------------------------------------------
def test_precision_at_k():
    assert metrics.precision_at_k([0.9, 0.8, 0.1], [True, False, True], 2) == 0.5
    assert metrics.precision_at_k([0.1], [True], 5) is None


def test_average_precision_perfect_and_worst():
    assert metrics.average_precision([3, 2, 1], [True, True, False]) == 1.0
    assert metrics.average_precision([3, 2, 1], [False, False, True]) == pytest.approx(1 / 3)
    assert metrics.average_precision([1, 2], [False, False]) is None


def test_roc_auc_with_ties():
    assert metrics.roc_auc([0.9, 0.1], [True, False]) == 1.0
    assert metrics.roc_auc([0.5, 0.5], [True, False]) == 0.5
    assert metrics.roc_auc([0.5], [True]) is None


def test_agreement_and_kappa():
    a = metrics.agreement([True, True, False, False], [True, False, False, False])
    assert (a["tp"], a["fp"], a["fn"], a["tn"]) == (1, 1, 0, 2)
    assert a["precision"] == 0.5 and a["recall"] == 1.0
    assert metrics.agreement([True, False], [True, False])["kappa"] == 1.0


# ---- personalize ---------------------------------------------------------------------------
def votes(*items):
    ids = [i for i, _, _ in items]
    vecs = np.array([v for _, v, _ in items], dtype=np.float32)
    w = np.array([w for _, _, w in items], dtype=np.float32)
    return personalize.Votes(ids, vecs, w)


def test_score_vector_prefers_liked_neighbourhood():
    v = votes(("a", [1, 0, 0], 1.0), ("b", [0, 1, 0], -1.0))
    assert personalize.score_vector([1, 0, 0], v) > 0
    assert personalize.score_vector([0, 1, 0], v) < 0
    assert -1 <= personalize.score_vector([0.7, 0.7, 0], v) <= 1


def test_score_vector_leave_one_out_ignores_own_vote():
    v = votes(("a", [1, 0, 0], 1.0))
    assert personalize.score_vector([1, 0, 0], v) > 0
    assert personalize.score_vector([1, 0, 0], v, exclude_id="a") == 0.0


def test_feedback_scores_needs_min_votes_and_blend_moves_rank():
    cfg = load_config().personalize
    c = Candidate(id="x", url="u", title="t", source="arxiv", embedding=[1, 0, 0], final_rank=0.5)
    few = votes(("a", [1, 0, 0], 1.0))
    assert personalize.feedback_scores([c], few, cfg) == {}
    many = votes(*[(str(i), [1, 0, 0], 1.0) for i in range(cfg.min_votes)])
    scores = personalize.feedback_scores([c], many, cfg)
    assert scores["x"] > 0
    personalize.apply_final_blend([c], scores, 0.2)
    assert c.final_rank > 0.5


# ---- ablation + calibration ------------------------------------------------------------------
def ex(i, label, *, kw=0.0, cos=0.0, rel=None, day=date(2026, 10, 17), emb=None):
    return Example(item_id=str(i), day=day, label=label, parts={"keyword": kw, "cosine": cos},
                   relevance=rel, novelty=5, actionability=5, embedding=emb)


def test_ablation_shows_judge_beating_keywords_when_keywords_mislead():
    # keywords point at the wrong items; the judge's relevance points at the right ones
    exs = [ex(i, label=i < 5, kw=0.0 if i < 5 else 1.0, cos=0.5, rel=9 if i < 5 else 2) for i in range(10)]
    rows = {r.ranker: r for r in ablation.run_ablation(exs, load_config())}
    assert rows["Keywords only"].p5_pooled == 0.0
    assert rows[ablation.CURRENT].p5_pooled == 1.0
    assert rows[ablation.CURRENT].days_used == 1


def test_ablation_adds_vote_rows_only_with_enough_votes():
    cfg = load_config()
    exs = [ex(i, label=i % 2 == 0, rel=5, emb=[1, 0, 0] if i % 2 == 0 else [0, 1, 0]) for i in range(10)]
    few = votes(("v", [1, 0, 0], 1.0))
    assert not any("votes" in r.ranker for r in ablation.run_ablation(exs, cfg, few))
    many = votes(*[(f"v{i}", [1, 0, 0], 1.0) for i in range(3)], *[(f"n{i}", [0, 1, 0], -1.0) for i in range(3)])
    rows = {r.ranker: r for r in ablation.run_ablation(exs, cfg, many)}
    assert rows["+ your votes (blend 0.3)"].avg_precision > rows[ablation.CURRENT].avg_precision


def test_judge_calibration_marks_current_cutoff():
    cfg = load_config()
    exs = [ex(i, label=i < 3, rel=8 if i < 3 else 2) for i in range(6)]
    rows, auc = ablation.judge_calibration(exs, cfg)
    current = [r for r in rows if r.is_current]
    assert len(current) == 1 and current[0].threshold == cfg.judge.min_relevance
    assert auc == 1.0


def test_unique_items_keeps_latest_day():
    a = ex(1, True, day=date(2026, 10, 16))
    b = ex(1, True, day=date(2026, 10, 17))
    assert unique_items([a, b])[0].day == date(2026, 10, 17)
    assert set(by_day([a, b])) == {date(2026, 10, 16), date(2026, 10, 17)}


# ---- plain language --------------------------------------------------------------------------
def test_item_jargon_explained_once_is_enough():
    fields = ["AI agents split a job", "Multi-agent (several AI agents splitting a job) setups help.",
              "Imagine a multi-agent team."]
    assert plain.item_jargon(fields) == []
    assert plain.item_jargon(["Multi-agent setups help."]) == ["multi-agent"]


def test_unexplained_jargon_respects_explanations_and_word_boundaries():
    assert plain.unexplained_jargon("A new benchmark for agents") == ["benchmark"]
    assert plain.unexplained_jargon("RAG (letting an AI look things up) helps") == []
    assert plain.unexplained_jargon("letting an AI look things up (RAG) helps") == []
    assert plain.unexplained_jargon("LiteLLM ships a release") == []  # not the word LLM
    assert plain.unexplained_jargon("Tokens are cheap") == ["tokens"]


def test_plain_language_report():
    good = quality.ReaderItem("t", "s", "A short headline", "Plain words.", "Imagine a shop.", "Useful.")
    bad = quality.ReaderItem("t", "s", "A new benchmark framework", "LLM agents.", "A shop.", "Useful.")
    r = quality.plain_language([good, bad])
    assert r.jargon_rate == 0.5 and r.example_ok_rate == 0.5 and r.headline_ok_rate == 1.0


class EditorRouter:
    """Returns the given entries (already numbered) as the editor's output."""

    def __init__(self, entries):
        self.entries = entries
        self.model_list = [{"litellm_params": {"model": "fake/m"}}]

    def completion(self, **kw):
        body = judge.EditedDigest(items=[judge.EditedEntry(n=i + 1, **e)
                                         for i, e in enumerate(self.entries)]).model_dump_json()

        class M: ...

        m = M()
        m.message = M()
        m.message.content = body
        r = M()
        r.choices = [m]
        r.model = "fake/m"
        return r


def _entry(i, **kw):
    base = dict(id=str(i), url="u", title=f"t{i}", source="arxiv", judged=True,
                headline=f"Headline {i}", summary="A multi-agent framework.",
                example="Imagine a help desk.", why_it_matters="Saves time.")
    base.update(kw)
    return Candidate(**base)


def _edit(**kw):
    return dict({"headline": "Agents split a job", "summary": "Multi-agent (several AI agents splitting a job) systems.",
                 "example": "Imagine a codebase.", "why_it_matters": "Specific."}, **kw)


def test_edit_digest_keeps_edit_that_makes_entries_less_alike(monkeypatch):
    sims = iter([0.80, 0.60])  # before, after
    monkeypatch.setattr(judge, "_mean_pairwise_similarity", lambda texts: next(sims))
    cs = [_entry(1), _entry(2)]
    rep = judge.edit_digest(cs, load_config(), router=EditorRouter([_edit(), _edit(headline="Teams of agents split the work")]))
    assert rep["kept"] and rep["edited"] == 2
    assert cs[0].headline == "Agents split a job" and judge.jargon_in(cs[0]) == []


def test_edit_digest_rejects_edit_that_makes_entries_more_alike(monkeypatch):
    sims = iter([0.60, 0.80])
    monkeypatch.setattr(judge, "_mean_pairwise_similarity", lambda texts: next(sims))
    cs = [_entry(1), _entry(2)]
    rep = judge.edit_digest(cs, load_config(), router=EditorRouter([_edit(), _edit()]))
    assert not rep["kept"] and cs[0].headline == "Headline 1"


def test_edit_digest_skips_entries_that_break_format_and_keeps_watchlist_example_empty(monkeypatch):
    sims = iter([0.80, 0.60])
    monkeypatch.setattr(judge, "_mean_pairwise_similarity", lambda texts: next(sims))
    a = _entry(1)
    w = _entry(2, source="watchlist", is_watchlist=True, example="")
    edits = [_edit(example="A codebase story without the opener."), _edit(example="Imagine an invented scene.")]
    judge.edit_digest([a, w], load_config(), router=EditorRouter(edits))
    assert a.headline == "Headline 1"  # rejected: example lost its "Imagine" opener
    assert w.example == "" and w.headline == "Agents split a job"


# ---- gate, report, model check -----------------------------------------------------------------
def _result(**kw):
    base = dict(examples=[], votes=0, ablation=[], calibration=[], judge_auc=None,
                plain=quality.PlainLanguageReport(n_items=0, jargon_rate=None))
    base.update(kw)
    return cli.EvalResult(**base)


def test_gate_skips_ranking_without_labels_but_checks_jargon_and_models():
    cfg = load_config()
    r = _result(plain=quality.PlainLanguageReport(n_items=10, jargon_rate=0.9),
                models=[models_check.ModelStatus("groq/x", False, "NOT FOUND")])
    cli.apply_gate(r, cfg)
    assert "skipped" in r.gate_skipped_reason
    assert any("jargon" in f for f in r.gate_failures) and any("groq/x" in f for f in r.gate_failures)
    assert "No labels yet" in cli.render(r, cfg)


def test_check_models_flags_missing_ids(monkeypatch):
    cfg = load_config()
    cfg.models.judge, cfg.models.fallbacks = "groq/a", ["gemini/b", "mystery/c"]
    monkeypatch.setitem(models_check.LISTERS, "groq", lambda env: {"a"})
    monkeypatch.setitem(models_check.LISTERS, "gemini", lambda env: {"other"})
    out = {m.model: m for m in models_check.check_models(cfg, Env(_env_file=None))}
    assert out["groq/a"].ok and not out["gemini/b"].ok and not out["mystery/c"].ok


def test_variety_reports_gap_openings_and_repeated_phrases(monkeypatch):
    sims = iter([0.75, 0.65])  # written, then source
    monkeypatch.setattr(quality, "_pairwise", lambda texts: next(sims))
    items = [quality.ReaderItem(f"t{i}", "s", "A new method", "AI assistants.", "", "") for i in range(3)]
    v = quality.variety([items])
    assert v.sameness_gap == pytest.approx(0.10)
    assert v.shared_openings == 3
    assert ("ai assistants", 3) in v.repeated_phrases


def test_reading_grade_orders_easy_below_hard():
    easy = plain.reading_grade("The cat sat on the mat. It was a good day.")
    hard = plain.reading_grade("Topology-aware adversarial poisoning exploits approximate nearest-neighbor "
                               "indexing constraints in deployment-scale retrieval infrastructures.")
    assert easy < 5 < 14 < hard


def test_edit_digest_rejects_entry_edit_that_reads_harder(monkeypatch):
    sims = iter([0.80, 0.60])
    monkeypatch.setattr(judge, "_mean_pairwise_similarity", lambda texts: next(sims))
    a = _entry(1, summary="The cat sat on the mat.", headline="Cats sit on mats")
    b = _entry(2)
    harder = _edit(headline="Feline positional equilibrium",
                   summary="Multi-agent (several AI agents) quadrupedal positional equilibrium characterization.")
    judge.edit_digest([a, b], load_config(), router=EditorRouter([harder, _edit()]))
    assert a.headline == "Cats sit on mats"
