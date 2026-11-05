# V2 — Job search & application engine (proposal, 2026-11-05)

**Status: design confirmed 2026-11-05. Steps 1–2 done (branch `rebuild/n8n-engine`).**

Run the stack (step 2):

```bash
python scripts/init_env.py        # once: .env with fresh secrets (gitignored)
docker compose up -d --build      # n8n :5678 · factbank-api :8000 · Postgres :5433, all 127.0.0.1
```

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
5. **Daily workflow.** 07:00: discover → score → upsert into Postgres → "N new jobs" notification. ✅ *Milestone: runs daily without you*

### Week 2: the full flow without a terminal
6. **Review app: Inbox.** Job cards, Pursue/Skip → n8n webhook → decision stored
7. **Drafting workflow.** On pursue: tailor → letter draft → `ready_for_review`
8. **Review app: Review screen.** CV + letter editor + live gates + Approve
9. **Package + send.** On approve: package. *I sent it* button, then follow-up reminders. ✅ *Milestone: discovery to sent, all clicks*

### Week 3: smarter + safer
10. **LLM steps in n8n.** Re-rank top N (structured output) and an optional letter middle. Both stay challengers, and generated text never bypasses the gates
11. **Tracking.** Outcome buttons, weekly report (Wilson intervals, censoring kept), funnel view
12. **Reliability.** Error workflow, daily heartbeat, Postgres backup, rate-limit / cost caps
13. **Hardening + docs.** End-to-end test on real jobs, README/ONBOARDING rewritten. Buffer for slippage

---

## Decisions (confirmed 2026-11-05)

- **A. Review UI:** custom small web app, served from the stack on localhost
- **B. Python logic:** kept as the containerised `factbank-api`; n8n calls it over HTTP
- **C. Phone access:** desktop only for now; notifications link to the localhost app. Revisit in week 3
- **D. LLM:** none for now. Everything runs deterministically; step 10 stays parked until a provider is chosen

Environment found: Docker 29.6 + Compose installed (daemon currently **stopped**), Node 26,
Python 3.11. n8n not installed yet. No LLM key set in the environment.
