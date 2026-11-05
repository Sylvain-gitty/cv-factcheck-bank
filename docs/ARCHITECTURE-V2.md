# V2 — Job search & application engine (proposal, 2026-11-05)

**Status: design confirmed 2026-11-05. Steps 1–9, 11 and 12 done (branch `rebuild/n8n-engine`). Step 10 (LLM) parked.**

API (step 4), all except `/health` need `Authorization: Bearer $API_TOKEN`:
`POST /discover {limit?, sources?}` · `POST /score {top?}` · `GET /validate` · `GET /health`.
Postgres is now the source of truth for jobs. Don't run the V1 `discover.py` / `rank.py`
CLIs any more: they still work, but they write to the old `.state/` files, which the engine
no longer reads.

Run the stack (step 2):

```bash
python scripts/init_env.py        # once: .env with fresh secrets (gitignored)
docker compose up -d --build      # n8n :5678 · factbank-api :8000 · Postgres :5433, all 127.0.0.1
                                  # the API applies db/migrations/*.sql on startup
docker compose exec factbank-api python scripts/import_v1.py   # once: V1 files -> Postgres
```

Pipeline + notifications (step 5):

```bash
python scripts/n8n_install.py     # import + publish the workflows, restart n8n (runs the pipeline)
powershell -ExecutionPolicy Bypass -File scripts\windows\install-notifier.ps1   # once: sign-in task
```

- **The pipeline runs every time n8n starts**, not at a fixed time: discover → score → record a
  digest. With Docker Desktop set to start at sign-in, that is every PC startup. A manual
  "Run now" trigger sits in the same workflow.
- **The digest is local.** It's a row in `digests`, shown at http://localhost:8000/ and announced by
  a Windows notification (`scripts/windows/notifier.ps1`, started at sign-in, checks every
  2 min). A failed run is recorded by the error workflow and gets its own notification. If the
  API can't be reached for ~6 min, the notifier says so.
- **Per-source cap is per 24 h**, not per run, so restarts can't let one large board flood the inbox.
- Digest writes are idempotent on the n8n execution they report (`source_execution`).

Review app (step 6): http://localhost:8000/, the inbox (Gate 1). Keys: `j`/`k` to move,
`p` pursue, `s` skip, `x` select, `e` expand, `o` open the posting, `u` undo, `/` search.
Filters by source, role profile and text; bulk skip of the selection or of everything shown,
behind a confirm dialog. Decisions are written by the API directly (not via n8n) with the score
snapshot. Undo marks the decision `undone_at`, so the table stays append-only. **No login:**
app requests must carry a localhost Host header, and writes must come from the app's own origin
with an `X-Job-Engine` header, which blocks other websites in your browser (see `api/main.py`).

Drafting (step 7): a Pursue click pings the n8n webhook `job-engine/draft`. The
**drafting** workflow (also on startup, every 15 min as a safety net, and a manual "Run now")
calls `POST /draft`, which runs V1's `tailor.py` + `letter.py` per job:
`pursued → drafting → ready_for_review`, usually within ~2 s. Rules kept from V1:
- the CV variant follows the score (`span` when two profiles are tied);
- a letter whose opening you wrote is never touched;
- an unwritten draft is rebuilt with the CV, and the old one goes to `letters/.superseded/`.

Each attempt is a `documents` version with its check results. A failed draft returns the job to
`pursued` with `draft_error`. It gets at most one attempt per run and 3 in total, and the failure
reaches you as a failed digest (Windows notification). The webhook takes no input and
only means "there may be work", so a stray call is harmless.

Review (step 8): http://localhost:8000/review. A queue of jobs to review, waiting, drafting
and approved, then for the selected job:
- **CV:** the tailored CV with its checks, and a variant switch with Rebuild.
- **Letter:** an "Your opening" box that replaces the TODO block, the letter source editor
  (autosave), a reader-view preview, live checks, and the hooks and evidence from the posting.
- **Approve** needs every fatal letter check to pass, the CV's fatal checks to pass, and the
  **"I read the CV"** tick (Gate 2, which V1 never enforced). It sets `APPROVED: yes`, renders
  with V1's `letter.py --render`, and moves the job to `approved`. Reopen and Drop are also there.
- **The letter file stays the source of truth:** each save keeps the previous version in
  `letters/.history/<slug>/`, and a save based on a stale copy is refused (409).
- **genericness change:** the gate now compares against letters whose opening is written,
  not against other unwritten drafts (those share a template and scored 1.00, so the gate
  could never pass).

Applications (step 9): http://localhost:8000/applications.
- **Approve packages automatically,** with V1's `package.assemble(record=False)`: CV, letter,
  `CHECKLIST.md` with your screening answers, and `follow-up.ics`, in `out/applications/<slug>/`.
- **PDFs are printed on Windows** by the desktop helper (`notifier.ps1`, now every 30 s) with Edge,
  the same path V1 used. The container has no browser and none of the CV's fonts, so its page
  breaks would differ from what you checked. Paths from the API are only accepted inside `out\`.
- **There is still no submit.** You apply on the employer's site, then click **I sent it**
  (with a date; it can be undone). That schedules day-7 and day-14 follow-ups, which the helper
  announces as Windows notifications and the screen lists with Done and Snooze (3 days).
- **Outcome buttons:** Replied, Interview, Offer, Rejected, "No reply, close it", "I withdrew". A
  reply sets `first_reply_date` once and closes the open follow-ups. No-reply and withdrawn are
  recorded, but never counted as replies.
- V1 applications sent in September have no follow-ups scheduled, so they don't fire
  retroactively.

Report (step 11): http://localhost:8000/report, computed live from Postgres with V1's rules:
- **No rate below 25 resolved applications**, only the interval, for scale.
- **21-day censoring:** no reply inside the window is not yet a rejection.
- **Wilson 95% intervals** on every proportion, and an overlap verdict on every breakdown.
- **CV-variant churn warning.**

One change from V1: it reports **any reply** (rejections included) and **interview or offer**
separately. V1 folded rejections that had a reply date into its single "response rate".

Also on the screen:
- **Last 7 days:** discovered, decided, pursued, approved, sent, replies.
- **The funnel.**
- **Skills postings asked for that no fact evidences**, counted across every pursued job's CV.
- **Your Gate 1 pursue share per role profile.**

The **weekly report** workflow asks for a snapshot at startup and daily at 09:00. The API stores
one only when the last is 7+ days old, and the desktop helper announces it. Snapshots accumulate
in `report_snapshots`, so the metrics become a time series. Chart colours are validated with the
dataviz checks: light `#1f5fae` on white, dark `#5b95e6` on `#20201d`.

Reliability (step 12), see [RUNBOOK.md](RUNBOOK.md):
- **Heartbeat** (`GET /heartbeat`, `api/heartbeat.py`): compares n8n's own execution log (read-only)
  with what the engine recorded, so a run with no digest (the step-6 failure) or a failure nobody
  recorded is raised as critical. Also: n8n down, no discovery for 3 days, stuck drafting or PDFs,
  stale backups. It appears as the Inbox banner and as one notification per issue (plus one when
  it clears), checked every ~5 min.
- **Backups:** the `backup` service dumps both databases and tars the irreplaceable files into
  `backups/`, at start and every 24 h, keeping 14 days. A restore was tested.
- **n8n execution pruning:** 14 days.
- **Optional 12-hour pipeline trigger:** present in the workflow but **off** (decision E stands).

Schema: `db/migrations/001_init.sql`. The V1 files are left untouched by the import, and it
refuses to run twice unless given `--replace`.

## Goal

A job search and application engine that runs itself. Every day it finds and scores new
postings. For the jobs you approve, it prepares a tailored CV, a letter draft and an
application folder. You only make the calls a machine shouldn't, and you make them in a
web UI with clicks, not with terminal commands or md tick-files.

Out of scope: article writing (Plan 02). `article.py`, `content-sources.yaml`, `articles/` and
`02-blog-article-pipeline.md` move to their own repo or branch. Nothing gets deleted.

Kept as-is: the fact bank (`profile`, `entities`, `facts`, `vocab`, `render_config`,
`answers`) and the documents rendered from it: CVs and letters, their gates, traceability, and
selection by fact ID.

---

## Shape

```
                ┌──────────────────────── docker compose ────────────────────────┐
                │                                                                 │
  You ──browser──►  Review app  ──webhook──►   n8n  ───HTTP───►  factbank-api     │
     (1 click)  │   (UI)        ◄──reads────   (engine)          (Python, the     │
                │      │                        │  │             existing logic)  │
                │      └────────── Postgres ◄───┘  └── LLM / email / schedules    │
                │                 (all state)                                     │
                └─────────────────────────────────────────────────────────────────┘
```

| Component | Owns | Built from |
|---|---|---|
| **n8n** | schedules, the flow between steps, LLM calls, notifications, follow-up reminders, error alerts | new workflows |
| **Postgres** | all state: jobs, scores, decisions, documents, applications, events | replaces `.state/*.json`, `decisions.*`, `applications.csv` |
| **factbank-api** | deterministic work: discover/normalise, BM25 scoring, tailoring, letter gates, rendering, packaging | `bridge.py` rewritten to return JSON. Stage scripts become importable functions |
| **Review app** ❓ | the only surface you touch | see decision A |

Every job moves through one state machine, stored in Postgres:

```
new → scored → [GATE 1] pursue | skip
pursue → drafting → ready_for_review → [GATE 2+3] approved → packaged
       → [GATE 4] sent → replied | interview | rejected | no_reply(closed)
```

## The gates, with less friction (same rules)

| Gate | Before (V1) | V2 |
|---|---|---|
| 1 Pursue / skip | tick `[p]` in `decisions.txt`, then run a command | job cards in the app: **Pursue / Skip** buttons or keyboard shortcuts (`p` / `s`). Features are snapshotted on click |
| 2 Read the CV | open an HTML file by hand | **Review screen**: CV preview next to the letter, plus a variant switcher |
| 3 Write the opening | edit md file, run `--check`, `--render` | same screen: opening text box, **gates re-run live**, *Approve* disabled until they pass |
| 4 Submit | `package.py --sent` | still you, on the portal. Then one **I sent it** click. Follow-ups at day 7/14 are scheduled automatically |
| Outcomes | edit CSV by hand | **Replied / Interview / Rejected** buttons on the application card |

Still never automated: choosing jobs, writing the opening, submitting.

## Data model (Postgres)

- `jobs`: normalised posting, `job_key` unique (dedupe), raw description, source, url, first_seen
- `scores`: one row per job per run: per-archetype BM25, argmax, margin, LLM fields (fit, missing_requirements, red_flags, why)
- `decisions`: verdict, decided_at, **feature snapshot**. The 191 existing decisions are migrated
- `documents`: CV and letter versions per job: variant, html path, trace, check results, `opening` text
- `applications`: sent_date, first_reply_date, status, cv_variant, notes. The 14 existing applications are migrated
- `events`: append-only log of every transition (*log everything*)
- `runs`: one row per workflow run, used by the heartbeat and error alerts

---

## Build order: automated as early as possible

Each step: I propose → you confirm → I build → I show it working → you verify → commit.

### Week 1: automated discovery by Friday
1. **Branch + cleanup.** Branch `rebuild/n8n-engine` in the `fact-bank` repo. Move the Plan 02 files out. Bring the plan docs inside the repo
2. **Infrastructure.** `docker-compose.yml`: n8n, Postgres, factbank-api. `.env.example`. Personal data mounted, never baked into an image
3. **Schema + migration.** SQL schema, plus a one-off import of the 190 jobs, 191 decisions and 14 applications
4. **factbank-api v1.** `/discover`, `/score`, `/validate` returning JSON. Token auth, no shell strings
5. **Pipeline workflow.** On every startup: discover → score → upsert into Postgres → local digest + Windows notification. ✅ *Milestone: runs without you*

### Week 2: the full flow without a terminal
6. **Review app: Inbox.** Job cards, Pursue/Skip → API stores the decision (step 7 hands pursues to n8n)
7. **Drafting workflow.** On pursue (webhook ping, within seconds): tailor → letter draft → `ready_for_review`
8. **Review app: Review screen.** CV + letter editor + live gates + Approve
9. **Package + send.** On approve: package (PDFs printed on Windows). *I sent it* → day-7/14 follow-ups as notifications; outcome buttons. ✅ *Milestone: discovery to sent, all clicks*

### Week 3: smarter + safer
10. **LLM steps in n8n.** Re-rank top N (structured output) and an optional letter middle. Both stay challengers, and generated text never bypasses the gates
11. **Tracking.** Report screen (Wilson intervals, censoring kept, any-reply vs interview), funnel, skill gaps, weekly snapshot + notification
12. **Reliability.** Heartbeat (silent-failure checks), daily backups + tested restore, execution pruning, optional periodic run (off)
13. **Hardening + docs.** End-to-end test on real jobs, README/ONBOARDING rewritten. Buffer for slippage

---

## Decisions (confirmed 2026-11-05)

- **A. Review UI:** custom small web app, served from the stack on localhost
- **B. Python logic:** kept as the containerised `factbank-api`; n8n calls it over HTTP
- **C. Phone access:** desktop only. **Notifications are local** (2026-11-05): the digest page plus Windows notifications. No email, no Telegram, nothing leaves the machine. Email and then Telegram were considered and dropped. Telegram stays a one-node option if phone notifications are wanted later
- **E. Schedule:** the pipeline runs **on every n8n startup** instead of at 07:00 (2026-11-05). A PC left on for days gets no new run until the next restart; a periodic fallback can be added in step 12 if that matters
- **D. LLM:** none for now. Everything runs deterministically; step 10 stays parked until a provider is chosen

Environment found: Docker 29.6 + Compose installed (daemon currently **stopped**), Node 26,
Python 3.11. n8n not installed yet. No LLM key set in the environment.
