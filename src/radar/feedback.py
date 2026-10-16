"""Signed, single-use feedback links (verified by the Cloudflare Worker in worker/src/index.js).

Token = base64url(JSON{n: nonce, i: item, r: run, a: action, e: expiry}) + "." + base64url(HMAC-SHA256).
Each token's nonce is stored in `feedback_tokens`; the database marks it used on the first valid POST.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

import psycopg

from radar.models import Candidate

ACTIONS = ("up", "down", "save")
TTL_DAYS = 30


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def mint(item_id: str, run_id: str, action: str, secret: str, *, ttl_days: int = TTL_DAYS,
         now: float | None = None) -> tuple[str, str, datetime]:
    """Returns (token, nonce, expires_at)."""
    now = time.time() if now is None else now
    nonce = secrets.token_urlsafe(16)
    expiry = int(now + ttl_days * 86400)
    payload = _b64(json.dumps({"n": nonce, "i": item_id, "r": run_id, "a": action, "e": expiry},
                              separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}", nonce, datetime.fromtimestamp(expiry, tz=UTC)


def verify(token: str, secret: str, *, now: float | None = None) -> dict | None:
    """Python-side verifier (the Worker does the real one); used by tests."""
    try:
        payload, sig = token.split(".")
        want = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            return None
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:
        return None
    if claims["e"] < (time.time() if now is None else now):
        return None
    return claims


def create_links(
    conn: psycopg.Connection, run_id: str, items: list[Candidate], *, base_url: str, secret: str
) -> dict[str, dict[str, str]]:
    """Mint and store tokens for every item/action. Returns {item_id: {action: url}}."""
    base = base_url.rstrip("/")
    out: dict[str, dict[str, str]] = {}
    for c in items:
        out[c.id] = {}
        for action in ACTIONS:
            token, nonce, expires = mint(c.id, run_id, action, secret)
            conn.execute(
                "insert into feedback_tokens (nonce, item_id, run_id, action, expires_at) "
                "values (%s,%s,%s,%s,%s)",
                (nonce, c.id, run_id, action, expires),
            )
            out[c.id][action] = f"{base}/f/{token}"
    conn.commit()
    return out


def prune_expired(conn: psycopg.Connection) -> int:
    cur = conn.execute(
        "delete from feedback_tokens where expires_at < %s", (datetime.now(UTC) - timedelta(days=7),)
    )
    conn.commit()
    return cur.rowcount
