-- 007: weekly report snapshots (step 11).
-- The live report is always computed on demand. Once a week a snapshot is stored as well,
-- so the metrics themselves become a time series (how the funnel moved, when replies came)
-- instead of being overwritten, and the desktop helper announces it.
create table report_snapshots (
    id          bigserial primary key,
    created_at  timestamptz not null default now(),
    data        jsonb not null,
    notified_at timestamptz
);
create index report_snapshots_created_idx on report_snapshots (created_at desc);
