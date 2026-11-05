-- 008: heartbeat bookkeeping (step 12).
-- watch_since: the heartbeat only judges n8n executions after this moment. Executions
-- from before it existed (including the step-6 runs whose digests were refused, already
-- diagnosed and fixed) would otherwise raise alarms about history.
create table heartbeat_state (
    key   text primary key,
    value timestamptz not null
);
insert into heartbeat_state (key, value) values ('watch_since', now());
