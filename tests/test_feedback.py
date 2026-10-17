import subprocess
from pathlib import Path

import pytest

from radar import feedback

SECRET = "test-secret"
ITEM = "11111111-1111-1111-1111-111111111111"
RUN = "22222222-2222-2222-2222-222222222222"


def test_mint_and_verify_roundtrip():
    token, nonce, expires = feedback.mint(ITEM, RUN, "up", SECRET)
    claims = feedback.verify(token, SECRET)
    assert claims["i"] == ITEM and claims["r"] == RUN and claims["a"] == "up" and claims["n"] == nonce
    assert expires.year >= 2026


def test_verify_rejects_tampering_wrong_secret_and_expiry():
    token, _, _ = feedback.mint(ITEM, RUN, "up", SECRET, now=1_000_000)
    assert feedback.verify(token, SECRET, now=1_000_100) is not None
    assert feedback.verify(token, "other-secret", now=1_000_100) is None
    payload, sig = token.split(".")
    assert feedback.verify(payload[:-2] + "AA." + sig, SECRET, now=1_000_100) is None
    assert feedback.verify(token, SECRET, now=1_000_000 + 31 * 86400) is None


def test_nonces_are_unique():
    nonces = {feedback.mint(ITEM, RUN, "up", SECRET)[1] for _ in range(50)}
    assert len(nonces) == 50


@pytest.mark.skipif(subprocess.run(["node", "--version"], capture_output=True).returncode != 0,
                    reason="node not installed")
def test_python_token_verifies_in_worker_js():
    """Cross-language contract: the Worker's verifyToken accepts what Python mints."""
    token, nonce, _ = feedback.mint(ITEM, RUN, "down", SECRET)
    bad = token[:-3] + "AAA"
    script = Path(__file__).parent.parent / "worker" / "test" / "verify.mjs"
    out = subprocess.run(["node", str(script), token, bad, SECRET],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    good_claims, bad_claims = out.stdout.strip().splitlines()
    assert f'"n":"{nonce}"' in good_claims.replace(" ", "") and bad_claims == "null"


def test_deepdive_link_is_signed_reusable_and_scoped():
    link = feedback.deepdive_link("item-1", "run-1", base_url="https://app.test/", secret="s3cret")
    assert link.startswith("https://app.test/?t=")
    claims = feedback.verify(link.split("?t=")[1], "s3cret")
    assert claims["a"] == "deepdive" and claims["i"] == "item-1" and claims["r"] == "run-1"
    assert feedback.verify(link.split("?t=")[1], "other-secret") is None


def test_deepdive_link_lasts_a_week_votes_longer():
    import time

    now = time.time()
    link = feedback.deepdive_link("i", "r", base_url="https://app.test", secret="s")
    token = link.split("?t=")[1]
    assert feedback.verify(token, "s", now=now + 6 * 86400) is not None
    assert feedback.verify(token, "s", now=now + 8 * 86400) is None
    vote, _, _ = feedback.mint("i", "r", "up", "s")
    assert feedback.verify(vote, "s", now=now + 20 * 86400) is not None


def test_build_links_combines_vote_and_deepdive_links(monkeypatch):
    from types import SimpleNamespace

    from radar import pipeline
    from radar.models import Candidate

    c = Candidate(id="i1", url="https://x/1", title="t", source="arxiv")
    monkeypatch.setattr(
        pipeline.feedback, "create_links",
        lambda conn, run_id, items, *, base_url, secret: {i.id: {"up": f"{base_url}/f/u"} for i in items},
    )
    env = SimpleNamespace(feedback_signing_secret="s", feedback_base_url="https://w.test",
                          deepdive_base_url="https://app.test")
    links = pipeline._build_links(None, "run1", [c], env)["i1"]
    assert links["up"] == "https://w.test/f/u" and links["deepdive"].startswith("https://app.test/?t=")

    env.feedback_base_url = None  # no vote Worker configured: the deep-dive button still works
    assert set(pipeline._build_links(None, "run1", [c], env)["i1"]) == {"deepdive"}
    env.deepdive_base_url = ""
    assert pipeline._build_links(None, "run1", [c], env) == {"i1": {}}
    env.feedback_signing_secret = None
    assert pipeline._build_links(None, "run1", [c], env) is None
