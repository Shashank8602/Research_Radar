-- Plain-language digest fields.
alter table item_scores add column if not exists headline text;
alter table item_scores add column if not exists example text;
