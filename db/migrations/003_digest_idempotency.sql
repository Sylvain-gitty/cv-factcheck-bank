-- 003: one digest per n8n execution, whatever retries.
-- Seen on the first startup test: the error workflow's HTTP node posted the same failure
-- three times, 5 s apart (its retry interval), although the API answered 200 each time,
-- during n8n's own startup. Rather than depend on why, the write is made idempotent: the
-- workflow sends the id of the execution it is reporting, and a repeat is a no-op.
alter table digests add column source_execution text;
create unique index digests_source_execution_uq on digests (source_execution)
    where source_execution is not null;
