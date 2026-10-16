-- Lock down the public (anon) API and expose exactly two functions for the feedback Worker.
-- Our pipeline connects as the database owner (bypasses RLS), so this only affects the public key.

alter table items            enable row level security;
alter table runs             enable row level security;
alter table item_scores      enable row level security;
alter table digests          enable row level security;
alter table feedback         enable row level security;
alter table feedback_tokens  enable row level security;
alter table schema_migrations enable row level security;

revoke all on all tables in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;

-- Hand-labelled relevance judgments for evals (the "golden set").
create table if not exists golden_labels (
  item_id     uuid primary key references items(id),
  relevant    boolean not null,
  labeled_at  timestamptz default now()
);
alter table golden_labels enable row level security;

-- Shows the confirm page what it is about to record. Reveals only a headline and token status.
create or replace function public.feedback_token_info(p_nonce text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  t feedback_tokens%rowtype;
  h text;
begin
  select * into t from feedback_tokens where nonce = p_nonce;
  if not found then
    return jsonb_build_object('status', 'invalid');
  end if;
  select coalesce(nullif(s.headline, ''), i.title) into h
    from items i
    left join item_scores s on s.item_id = i.id and s.run_id = t.run_id
    where i.id = t.item_id;
  return jsonb_build_object(
    'status', case when t.used_at is not null then 'used'
                   when t.expires_at < now() then 'expired' else 'ok' end,
    'headline', h);
end $$;

-- Records one vote. Single-use token, idempotent, latest up/down wins.
create or replace function public.record_feedback(p_nonce text, p_item uuid, p_run uuid, p_action text)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  t feedback_tokens%rowtype;
  sec text;
begin
  select * into t from feedback_tokens where nonce = p_nonce for update;
  if not found then return 'invalid'; end if;
  if t.item_id <> p_item or t.run_id <> p_run or t.action <> p_action then return 'invalid'; end if;
  if t.used_at is not null then return 'used'; end if;
  if t.expires_at < now() then return 'expired'; end if;

  select section into sec from digests where run_id = p_run and item_id = p_item;
  update feedback_tokens set used_at = now() where nonce = p_nonce;

  if p_action = 'up' then
    delete from feedback where item_id = p_item and action = 'down';
  elsif p_action = 'down' then
    delete from feedback where item_id = p_item and action = 'up';
  end if;

  insert into feedback (item_id, run_id, section, action)
  values (p_item, p_run, sec, p_action)
  on conflict (item_id, action) do update
    set created_at = now(), run_id = excluded.run_id, section = excluded.section;
  return 'ok';
end $$;

revoke all on function public.feedback_token_info(text) from public;
revoke all on function public.record_feedback(text, uuid, uuid, text) from public;
grant execute on function public.feedback_token_info(text) to anon;
grant execute on function public.record_feedback(text, uuid, uuid, text) to anon;
