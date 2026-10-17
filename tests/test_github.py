"""GitHub repo collector: parsing, README cleaning, source cap in the digest, no network."""

from __future__ import annotations

from radar import diversify
from radar.collect import github
from radar.models import Candidate

REPO = {
    "full_name": "acme/re-skill", "html_url": "https://github.com/acme/re-skill",
    "description": "A skill that reverse engineers binaries", "topics": ["agent-skill", "reverse-engineering"],
    "stargazers_count": 640, "created_at": "2026-10-09T08:00:00Z", "fork": False, "archived": False,
}


def test_clean_readme_keeps_prose_drops_markup():
    md = (
        "# Re Skill\n\n[![build](https://img.shields.io/x.svg)](https://ci)\n"
        "![logo](logo.png)\n\n<p align=\"center\"><img src=x></p>\n\n"
        "Reverse engineers a **binary** and links to [the docs](https://d.example).\n\n"
        "```bash\npip install re-skill\n```\n\n- explains functions\n- finds strings\n"
    )
    out = github.clean_readme(md, 500)
    assert "Reverse engineers a **binary** and links to the docs." in out
    assert "shields.io" not in out and "logo.png" not in out and "pip install" not in out
    assert "<" not in out and "explains functions finds strings" in out
    assert len(github.clean_readme("word " * 1000, 100)) == 100


def test_parse_builds_item_with_readme_in_snippet_and_skips_forks():
    fork = {**REPO, "full_name": "x/fork", "fork": True}
    items = github.parse([REPO, fork, {"full_name": None}], "agent skills", {"acme/re-skill": "Explains functions."})
    assert len(items) == 1
    it = items[0]
    assert it.source == "github" and it.popularity == 640 and it.published_at.year == 2026
    assert it.title == "acme/re-skill: A skill that reverse engineers binaries"
    assert "Explains functions." in it.snippet and "reverse-engineering" in it.snippet


def _cand(i: int, source: str, rank: float) -> Candidate:
    return Candidate(id=str(i), url=f"https://x/{i}", title=f"t{i}", source=source, final_rank=rank,
                     embedding=[1.0, 0.0] if i % 2 else [0.0, 1.0], best_topic=f"topic{i}", judged=True, relevance=8)


def test_source_cap_stops_repos_crowding_out_papers():
    cands = [_cand(i, "github", 1.0 - i * 0.01) for i in range(6)] + [_cand(10 + i, "arxiv", 0.5 - i * 0.01) for i in range(4)]
    picked = diversify.mmr_select(cands, 5, 1.0, max_per_source={"github": 2})
    assert sum(c.source == "github" for c in picked) == 2 and sum(c.source == "arxiv" for c in picked) == 3
    # The cap is relaxed rather than leaving slots empty when only repos remain.
    only = diversify.mmr_select(cands[:6], 5, 1.0, max_per_source={"github": 2})
    assert len(only) == 5


def test_exclude_terms_drop_adult_and_gambling_repos():
    bad = {**REPO, "full_name": "x/qwen-nsfw-pose-skill", "description": "pose skill"}
    bad2 = {**REPO, "full_name": "x/okay", "description": "Online casino bot"}
    items = github.parse([REPO, bad, bad2], "q", exclude=["nsfw", "casino"])
    assert [i.title.split(":")[0] for i in items] == ["acme/re-skill"]
    assert len(github.parse([REPO, bad], "q")) == 2  # no exclude list = no filtering here
