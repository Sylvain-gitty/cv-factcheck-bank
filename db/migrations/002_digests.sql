-- 002_digests: the local digest. One row per pipeline run, written by n8n (success) or by
-- its error workflow (failure). Read by the Windows notifier and the app's first screen.
-- Nothing is sent anywhere: this table IS the notification channel.
create table digests (
    id              bigserial primary key,
    created_at      timestamptz not null default now(),
    status          text not null check (status in ('ok', 'failed')),
    trigger         text,                     -- n8n execution mode: trigger (startup) | manual | ...
    new_count       integer not null default 0,
    inbox_size      integer,
    fetched         integer,
    sources_run     integer,
    sources_failed  jsonb not null default '[]'::jsonb,
    top             jsonb not null default '[]'::jsonb,   -- [{id, slug, title, company, url, relative, archetype}]
    discover_run_id bigint references runs(id) on delete set null,
    score_run_id    bigint references runs(id) on delete set null,
    workflow        text,                     -- for failures: which workflow broke
    failed_node     text,
    error           text,
    execution_url   text,
    notified_at     timestamptz              -- set once the desktop notifier has shown it
);
create index digests_created_idx on digests (created_at desc);
create index digests_unnotified_idx on digests (id) where notified_at is null;
