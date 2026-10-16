"""Verify that every pinned model ID still exists at its provider.

Free-tier catalogs change without notice (gemini-2.5-flash-lite was retired for new users in
Oct 2026, decision D-037). Running this in CI turns a silent fallback into a visible failure.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from radar.config import AppConfig, Env


@dataclass
class ModelStatus:
    model: str
    ok: bool
    detail: str


def _groq_ids(env: Env) -> set[str]:
    r = httpx.get("https://api.groq.com/openai/v1/models",
                  headers={"Authorization": f"Bearer {env.groq_api_key}"}, timeout=30)
    r.raise_for_status()
    return {m["id"] for m in r.json()["data"]}


def _gemini_ids(env: Env) -> set[str]:
    ids, token = set(), None
    while True:
        params = {"key": env.gemini_api_key, "pageSize": 200}
        if token:
            params["pageToken"] = token
        r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        ids |= {m["name"].removeprefix("models/") for m in data.get("models", [])}
        token = data.get("nextPageToken")
        if not token:
            return ids


def _openrouter_ids(_: Env) -> set[str]:
    r = httpx.get("https://openrouter.ai/api/v1/models", timeout=30)
    r.raise_for_status()
    return {m["id"] for m in r.json()["data"]}


LISTERS = {"groq": _groq_ids, "gemini": _gemini_ids, "openrouter": _openrouter_ids}


def check_models(config: AppConfig, env: Env) -> list[ModelStatus]:
    cache: dict[str, set[str] | Exception] = {}
    out = []
    for model in [config.models.judge, *config.models.fallbacks]:
        provider, _, model_id = model.partition("/")
        if provider not in LISTERS:
            out.append(ModelStatus(model, False, f"unknown provider '{provider}'"))
            continue
        if provider not in cache:
            try:
                cache[provider] = LISTERS[provider](env)
            except Exception as e:  # missing key, network, provider down
                cache[provider] = e
        ids = cache[provider]
        if isinstance(ids, Exception):
            out.append(ModelStatus(model, False, f"could not list models: {str(ids)[:100]}"))
        elif model_id in ids:
            out.append(ModelStatus(model, True, "available"))
        else:
            out.append(ModelStatus(model, False, "NOT FOUND at provider (retired or renamed?)"))
    return out
