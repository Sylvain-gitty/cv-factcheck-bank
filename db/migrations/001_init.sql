-- 001_init: the job engine's state. Replaces .state/*.json, decisions.txt/.csv and
-- applications.csv. Documents (CV, letter, package) stay on disk; rows point at them.
--
-- Text + CHECK instead of enum types: states will change during the build, and a CHECK is
-- one ALTER away while an enum is a migration dance.

-- One row per posting. `slug` is the V1 file name and stays the stable human id.
create table jobs (
    id               bigserial primary key,
    slug             text not null unique,
    job_key          text unique,                -- dedupe hash (discover.job_key)
    title            text not null,
    company          text,
    location         text,
    url              text,
    source           text not null,
    language         text,
    posted_at        timestamptz,                -- parsed when the feed format allows
    posted_raw       text,                       -- what the feed actually said
    salary_raw       text,
    tags             text,
    description      text,
    requirements     jsonb,                      -- explicit list, when one exists
    state            text not null default 'new',
    state_changed_at timestamptz not null default now(),
    first_seen       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    raw              jsonb not null,             -- the full original record, for fidelity
    constraint jobs_state_check check (state in (
        'new',              -- discovered, not yet scored
        'scored',           -- in the inbox, waiting for Gate 1
        'skipped',          -- Gate 1: no
        'pursued',          -- Gate 1: yes, nothing built yet
        'drafting',         -- CV + letter draft being built
        'ready_for_review', -- Gate 2+3: CV to read, opening to write
        'approved',         -- gates pass, letter rendered
        'packaged',         -- application folder assembled
        'sent',             -- Gate 4: you submitted it
        'replied', 'interview', 'offer', 'rejected', 'closed'
    ))
);
create index jobs_state_idx on jobs (state);
create index jobs_first_seen_idx on jobs (first_seen desc);

-- Dedupe history. Includes keys of postings that were filtered out, so a dropped job is
-- not re-fetched and re-evaluated every day (V1: .state/seen.json).
create table job_keys (
    job_key    text primary key,
    slug       text,
    source     text,
    first_seen timestamptz not null default now(),
    job_id     bigint references jobs(id) on delete set null
);

-- Workflow runs: heartbeat, error alerts, and "which run produced this score".
create table runs (
    id          bigserial primary key,
    workflow    text not null,
    started_at  timestamptz not null default now(),
    finished_at timestamptz,
    status      text not null default 'running'
                check (status in ('running', 'ok', 'failed')),
    stats       jsonb,
    error       text
);

-- Scores are batch-relative (BM25 IDF depends on the corpus), so every row carries its run.
create table scores (
    id                  bigserial primary key,
    job_id              bigint not null references jobs(id) on delete cascade,
    run_id              bigint references runs(id) on delete set null,
    scored_at           timestamptz not null default now(),
    method              text not null default 'bm25' check (method in ('bm25', 'llm')),
    per_archetype       jsonb,
    archetype           text,
    archetype_confident boolean,
    archetype_label     text,
    margin              numeric,
    raw                 numeric,
    relative            integer,                 -- 0-100 within its batch
    llm                 jsonb                    -- fit_score, missing_requirements, ...
);
create index scores_job_idx on scores (job_id, scored_at desc);

-- Gate 1. History, not a single value: a reopened job gets a second row, latest wins.
-- `features` is the score snapshot AT DECISION TIME -- the training set.
create table decisions (
    id         bigserial primary key,
    job_id     bigint not null references jobs(id) on delete cascade,
    verdict    text not null check (verdict in ('pursue', 'skip')),
    decided_at timestamptz not null default now(),
    features   jsonb,
    origin     text not null default 'app' check (origin in ('app', 'v1-import'))
);
create index decisions_job_idx on decisions (job_id, decided_at desc);

-- CV / letter / package artefacts. Files stay on disk; this records which exist, which
-- variant, what the checks said.
create table documents (
    id         bigserial primary key,
    job_id     bigint not null references jobs(id) on delete cascade,
    kind       text not null check (kind in ('cv', 'letter', 'package')),
    version    integer not null default 1,
    variant    text,
    path       text not null,                    -- relative to the fact-bank root
    render_path text,                            -- rendered HTML/PDF, when there is one
    checks     jsonb,
    status     text not null default 'draft'
               check (status in ('draft', 'failed', 'passed', 'rendered')),
    created_at timestamptz not null default now(),
    unique (job_id, kind, version)
);

-- Gate 4 and after. One application per job.
create table applications (
    id               bigserial primary key,
    job_id           bigint not null unique references jobs(id) on delete cascade,
    archetype        text,
    batch_score      integer,
    cv_variant       text,
    has_letter       boolean not null default false,
    status           text not null default 'ready'
                     check (status in ('ready', 'sent', 'replied', 'interview', 'offer',
                                       'rejected', 'closed', 'withdrawn')),
    sent_date        date,
    first_reply_date date,
    notes            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

-- Append-only log of everything that happens. In three months this is the dataset.
create table events (
    id     bigserial primary key,
    at     timestamptz not null default now(),
    job_id bigint references jobs(id) on delete cascade,
    kind   text not null,                        -- e.g. state_change, decision, imported
    actor  text not null default 'system' check (actor in ('system', 'user', 'n8n', 'import')),
    data   jsonb
);
create index events_job_idx on events (job_id, at);
