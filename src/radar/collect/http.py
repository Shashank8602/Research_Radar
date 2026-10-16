"""Shared HTTP client for collectors: polite UA, timeouts, retry with backoff."""

from __future__ import annotations

import time

import httpx

USER_AGENT = "research-radar/0.1 (personal research digest; contact via GitHub)"


def get(url: str, *, params: dict | None = None, retries: int = 3, timeout: float = 30) -> httpx.Response:
    """GET with retry on 429/5xx/transport errors (exponential backoff)."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.get(
                url,
                params=params,
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"{resp.status_code} from {url}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last = e
            if attempt < retries:
                time.sleep(2 * (2**attempt))
    raise RuntimeError(f"GET {url} failed after {retries + 1} attempts: {last}")
