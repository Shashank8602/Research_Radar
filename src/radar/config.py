"""Configuration: secrets from env, behavior from topics.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Env(BaseSettings):
    """Secrets and deployment settings. Everything optional so imports never fail;
    call `require()` where a value is actually needed."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str | None = None
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    app_env: str = "development"  # development | production -> Langfuse environment
    app_release: str | None = None  # e.g. git sha, set by CI

    email_backend: str = "smtp"  # smtp | resend
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str | None = None
    email_to: str | None = None
    resend_api_key: str | None = None

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            names_up = ", ".join(m.upper() for m in missing)
            raise RuntimeError(f"Missing required env vars: {names_up}")


class ModelsConfig(BaseModel):
    judge: str
    fallbacks: list[str] = Field(default_factory=list)
    embedding: str = "BAAI/bge-small-en-v1.5"  # 384-dim; must match items.embedding


class SectionConfig(BaseModel):
    max_items: int


class DigestConfig(BaseModel):
    sections: dict[str, SectionConfig]


class TopicSources(BaseModel):
    arxiv: list[str] = Field(default_factory=list)
    hn_queries: list[str] = Field(default_factory=list)
    rss: list[str] = Field(default_factory=list)


class Topic(BaseModel):
    name: str
    weight: float = 1.0
    description: str
    anchors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    sources: TopicSources = Field(default_factory=TopicSources)


class RssSource(BaseModel):
    name: str
    feed: str


class GlobalSources(BaseModel):
    hf_daily_papers: bool = True
    rss: list[RssSource] = Field(default_factory=list)


class WatchlistEntry(BaseModel):
    name: str
    feed: str


class FilterWeights(BaseModel):
    cosine: float = 0.55
    keyword: float = 0.20
    recency: float = 0.15
    popularity: float = 0.10
    feedback: float = 0.0  # off until the ablation shows it helps (Phase 2)


class FilterConfig(BaseModel):
    top_n: int = 30
    recency_halflife_days: float = 3.0
    max_age_days: int = 14
    watchlist_window_days: int = 7
    weights: FilterWeights = Field(default_factory=FilterWeights)


class DedupeConfig(BaseModel):
    similarity_threshold: float = 0.92
    resend_window_days: int = 14


class JudgeConfig(BaseModel):
    batch_size: int = 6
    snippet_chars: int = 700
    w_relevance: float = 0.6
    w_novelty: float = 0.2
    w_actionability: float = 0.2
    min_relevance: float = 4.0  # items judged below this are not eligible for the digest


class DiversifyConfig(BaseModel):
    mmr_lambda: float = 0.7


class AppConfig(BaseModel):
    models: ModelsConfig
    filter: FilterConfig = Field(default_factory=FilterConfig)
    dedupe: DedupeConfig = Field(default_factory=DedupeConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    diversify: DiversifyConfig = Field(default_factory=DiversifyConfig)
    digest: DigestConfig
    topics: list[Topic]
    global_sources: GlobalSources = Field(default_factory=GlobalSources)
    watchlist: list[WatchlistEntry] = Field(default_factory=list)


@lru_cache
def get_env() -> Env:
    return Env()


def load_config(path: Path | None = None) -> AppConfig:
    path = path or ROOT / "topics.yaml"
    with path.open(encoding="utf-8") as f:
        return AppConfig.model_validate(yaml.safe_load(f))
