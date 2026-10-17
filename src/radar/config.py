"""Configuration: secrets from env, behavior from topics.yaml."""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Env(BaseSettings):
    """Secrets and deployment settings. Everything optional so imports never fail;
    call `require()` where a value is actually needed."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str | None = None
    dashboard_database_url: str | None = None  # optional SELECT-only role for the public dashboard
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    feedback_signing_secret: str | None = None  # HMAC key shared with the Worker
    feedback_base_url: str | None = None  # e.g. https://research-radar-feedback.<sub>.workers.dev
    github_token: str | None = None  # optional; raises the GitHub search limit (Actions provides one)
    deepdive_base_url: str | None = "https://research-radar-deepdive.streamlit.app"  # empty = no Deep dive links
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
    github_queries: list[str] = Field(default_factory=list)  # repo search terms (new repos with stars)
    rss: list[str] = Field(default_factory=list)


class Topic(BaseModel):
    name: str
    label: str = ""  # friendly name shown in the email
    angle: str = ""  # the reader's lens for this topic; shapes example + why_it_matters
    scope_note: str = ""  # extra guidance for the judge on when to pick this topic
    weight: float = 1.0
    description: str
    anchors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    sources: TopicSources = Field(default_factory=TopicSources)


class RssSource(BaseModel):
    name: str
    feed: str


class GithubSettings(BaseModel):
    window_days: int = 14  # only repos created this recently
    min_stars: int = 100  # ...that have already caught on
    per_query: int = 10
    max_repos: int = 40  # README is fetched for these only
    readme_chars: int = 1200
    exclude: list[str] = Field(default_factory=lambda: ["nsfw", "porn", "hentai", "casino", "betting", "airdrop"])


class GlobalSources(BaseModel):
    hf_daily_papers: bool = True
    github: GithubSettings = Field(default_factory=GithubSettings)
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
    mmr_lambda: float = 0.6
    max_per_topic: int = 2  # in the core section
    max_per_source: dict[str, int] = Field(default_factory=dict)  # e.g. {github: 2} in the core section


class PersonalizeConfig(BaseModel):
    """Vote-based ranking (radar.personalize). Off until the ablation shows a gain."""

    k: int = 5  # nearest voted items considered on each side
    min_votes: int = 5  # below this, votes are ignored entirely
    final_blend: float = 0.0  # added to final_rank as blend * score(-1..1)


class RetentionConfig(BaseModel):
    """Storage clean-up (radar.maintain). Items in a real digest, voted on or labeled are kept forever."""

    slim_after_days: int = 30  # drop abstract + embedding, keep title/link
    delete_after_days: int = 180  # delete the row entirely
    dry_run_keep_days: int = 14  # test runs' digests and unlabeled scores
    token_grace_days: int = 7  # feedback-link tokens after expiry
    chat_keep_days: int = 14  # saved deep-dive chats, counted from the last message
    warn_db_mb: int = 400  # free tier is ~500 MB


class EvalConfig(BaseModel):
    """Thresholds for `radar-eval --gate` (CI). The gate is skipped until enough labels exist."""

    min_labels_for_gate: int = 100
    min_precision_at_5: float = 0.5
    min_items_for_text_gate: int = 15  # writing checks need this many real entries to mean anything
    max_jargon_rate: float = 0.35
    max_reading_grade: float = 11.0  # Flesch-Kincaid grade of digest entries
    min_faithfulness: float = 0.85
    max_sameness_gap: float = 0.03  # written entries may be at most this much more alike than sources


class AppConfig(BaseModel):
    timezone: str = "Asia/Kolkata"  # a digest is dated by the reader's local day, not the runner's UTC day
    models: ModelsConfig
    filter: FilterConfig = Field(default_factory=FilterConfig)
    dedupe: DedupeConfig = Field(default_factory=DedupeConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    diversify: DiversifyConfig = Field(default_factory=DiversifyConfig)
    personalize: PersonalizeConfig = Field(default_factory=PersonalizeConfig)
    evals: EvalConfig = Field(default_factory=EvalConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    digest: DigestConfig
    topics: list[Topic]
    global_sources: GlobalSources = Field(default_factory=GlobalSources)
    watchlist: list[WatchlistEntry] = Field(default_factory=list)


def local_today(tz: str = "Asia/Kolkata", now: datetime | None = None) -> date:
    """Today's date in the reader's timezone. A run at 22:00 UTC is already tomorrow's digest in IST."""
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(tz)).date()


@lru_cache
def get_env() -> Env:
    return Env()


def load_config(path: Path | None = None) -> AppConfig:
    path = path or ROOT / "topics.yaml"
    with path.open(encoding="utf-8") as f:
        return AppConfig.model_validate(yaml.safe_load(f))
