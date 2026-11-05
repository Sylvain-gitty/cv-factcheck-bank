-- 005: drafting bookkeeping (step 7).
-- A pursued job is claimed for drafting (state 'drafting'), then lands in
-- 'ready_for_review' or goes back to 'pursued' with the error. After 3 failed attempts it
-- stays in 'pursued' and is no longer retried automatically, so one broken posting
-- cannot make every run fail forever; the review app shows the error.
alter table jobs add column draft_attempts integer not null default 0;
alter table jobs add column draft_error text;
