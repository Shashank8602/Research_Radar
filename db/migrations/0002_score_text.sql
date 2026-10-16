-- Persist the generated text and filter breakdown so digests can be previewed/replayed from the DB.
alter table item_scores add column if not exists summary text;
alter table item_scores add column if not exists why_it_matters text;
alter table item_scores add column if not exists filter_parts jsonb;
