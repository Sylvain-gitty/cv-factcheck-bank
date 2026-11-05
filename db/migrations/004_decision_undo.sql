-- 004: decisions from the review app.
-- undone_at: an Undo click marks the decision instead of deleting it, so the decisions
--   table stays append-only and a misclick is still visible in the training data
--   (and excluded from it). The latest decision with undone_at IS NULL is the verdict.
-- score_id: which score row the decision was made against, alongside the snapshot that
--   already lives in `features`.
alter table decisions add column undone_at timestamptz;
alter table decisions add column score_id bigint references scores(id) on delete set null;
