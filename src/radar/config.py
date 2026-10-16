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


class AppConfig(BaseModel):
    models: ModelsConfig
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
