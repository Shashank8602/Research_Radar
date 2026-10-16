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
