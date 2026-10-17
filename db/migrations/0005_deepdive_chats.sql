-- Deep-dive chat transcripts, so reopening a link (or an app restart) keeps the conversation.
-- One row per item: the rendered chat (role, text, citations) as JSON. Deleted with its item and
-- by radar-maintain after chat_keep_days. Owner connections bypass RLS; the public API gets nothing.
create table if not exists deepdive_chats (
  item_id     uuid primary key references items(id) on delete cascade,
  transcript  jsonb not null default '[]'::jsonb,
  updated_at  timestamptz not null default now()
);
alter table deepdive_chats enable row level security;
