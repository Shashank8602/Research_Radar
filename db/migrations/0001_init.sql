-- Research Radar initial schema. See research-radar.md section 4.
create extension if not exists vector;

create table if not exists items (
  id              uuid primary key default gen_random_uuid(),
  canonical_url   text unique not null,
  url             text not null,
  content_hash    text,
  title           text not null,
  source          text not null,          -- arxiv | hf_papers | hn | github | rss | tavily
  published_at    timestamptz,
  snippet         text,                   -- title/abstract only; full text fetched at deep-dive time
  embedding       vector(384),            -- must match the FastEmbed model dimension
  embedding_model text,
  cluster_id      uuid,
  popularity      int default 0,
  created_at      timestamptz default now()
);
create index if not exists items_published_idx on items (published_at desc);
create index if not exists items_cluster_idx on items (cluster_id);

create table if not exists runs (
  id            uuid primary key default gen_random_uuid(),
  digest_date   date not null,
  is_dry_run    boolean not null default false,
  status        text not null default 'running',  -- running | sent | degraded | failed
  started_at    timestamptz default now(),
  sent_at       timestamptz,
  n_collected   int, n_filtered int, n_sent int,
  cost_usd      real,
  langfuse_trace_id text,
  notes         text
);
-- One real digest per day (the idempotency lock); dry runs are exempt.
create unique index if not exists runs_one_real_per_day
  on runs (digest_date) where not is_dry_run;

create table if not exists item_scores (
  item_id       uuid references items(id),
  run_id        uuid references runs(id),
  best_topic    text not null,
  topic_scores  jsonb,
  relevance     real, novelty real, actionability real,
  rationale     text,
  filter_score  real,
  final_rank    real,
  judge_model   text,
  primary key (item_id, run_id)
);

create table if not exists digests (
  run_id        uuid references runs(id),
  item_id       uuid references items(id),
  section       text,                     -- core | watchlist | exploration
  position      int,
  primary key (run_id, item_id)
);

create table if not exists feedback (
  item_id       uuid references items(id),
  run_id        uuid references runs(id),
  section       text,
  action        text check (action in ('up','down','save','deepdive')),
  created_at    timestamptz default now(),
  primary key (item_id, action)
);

create table if not exists feedback_tokens (
  nonce         text primary key,
  item_id       uuid,
  run_id        uuid,
  action        text,
  expires_at    timestamptz,
  used_at       timestamptz
);

create table if not exists schema_migrations (
  name        text primary key,
  applied_at  timestamptz default now()
);
