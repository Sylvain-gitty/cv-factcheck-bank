-- 006: packaging, sending, follow-ups (step 9).

-- PDFs are printed on the Windows HOST by the desktop notifier, with Edge, exactly as V1
-- did: the container has no browser and none of the CV's fonts (Source Sans Pro / Segoe
-- UI), and V1's page-length estimator was calibrated against that Windows render. A PDF
-- printed in the container would break pages differently from the one you checked.
create table pdf_jobs (
    id         bigserial primary key,
    job_id     bigint not null references jobs(id) on delete cascade,
    html_path  text not null,          -- relative to the fact-bank root, inside out/
    pdf_path   text not null,          -- relative to the fact-bank root, inside out/
    status     text not null default 'pending' check (status in ('pending', 'done', 'failed')),
    error      text,
    created_at timestamptz not null default now(),
    done_at    timestamptz
);
create index pdf_jobs_pending_idx on pdf_jobs (id) where status = 'pending';

-- Follow-up reminders, created when you mark an application sent (day 7 and day 14).
create table follow_ups (
    id             bigserial primary key,
    application_id bigint not null references applications(id) on delete cascade,
    kind           text not null,            -- day-7 | day-14
    due_date       date not null,
    shown_at       timestamptz,              -- the desktop notifier announced it
    done_at        timestamptz,              -- you followed up, or a reply made it moot
    closed_reason  text,                     -- done | snoozed | replied | ...
    unique (application_id, kind)
);
create index follow_ups_open_idx on follow_ups (due_date) where done_at is null;

alter table applications add column package_path text;
alter table applications add column package_error text;
