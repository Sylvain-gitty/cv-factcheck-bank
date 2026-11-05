# Job engine

A local job-search and application engine. Every time your PC starts, it finds new
postings, scores them against your role profiles, and puts them in an inbox. When you
pursue a job, it builds a tailored CV and a letter draft from your fact bank within
seconds. When you approve the letter, it assembles the application. You make the
decisions in a small web app; nothing leaves your machine, and nothing is ever submitted
for you.

> **Automate the assembly. Never automate the judgment.**
> The engine does the hours of dull work. Deciding which job is worth it, writing the
> two sentences that show you are a person, and pressing send stay yours, and the
> tooling refuses to skip them.

New machine? **Read [ONBOARDING.md](ONBOARDING.md)**: setup from scratch, about 30 minutes.

---

## A normal day

| | What happens | Where you act |
|---|---|---|
| 1 | You start the PC. n8n starts and runs **discover → score**; a Windows notification says "12 new job(s), 140 waiting". | nothing |
| 2 | **Gate 1:** you go through the inbox: **Pursue** or **Skip** (`p` / `s`), with bulk skip and filters. | http://localhost:8000/ |
| 3 | Each pursue is drafted within seconds: the CV is tailored from confirmed facts, and the letter draft has the opening left empty. | nothing |
| 4 | **Gates 2 + 3:** you read the CV, write the opening, and tick **"I read the CV"**. **Approve** unlocks only when every check passes. | /review |
| 5 | Approving packages the application (CV, letter, checklist with your screening answers). The desktop helper prints the PDFs with Edge. | nothing |
| 6 | **Gate 4:** you apply on the employer's site yourself, then click **I sent it**. | /applications |
| 7 | Day 7 and day 14: a follow-up notification. Record the outcome with one click (Replied, Interview, Rejected, …). | /applications |
| 8 | Weekly: a report notification with response rates (with intervals), the funnel, and your skill gaps. | /report |

## How it is built

```
        ┌─────────────────────────── docker compose (all ports 127.0.0.1) ───────────────────────────┐
        │                                                                                              │
 you ───┼─► review app (:8000) ──► factbank-api ◄── HTTP + token ── n8n (:5678)  the engine:          │
        │   inbox · review ·        (Python: the V1    ──webhook──►            startup, schedules,     │
        │   applications · report    stage logic)                              error workflow          │
        │                │                │                                                            │
        │                └──── Postgres ◄─┘  all state: jobs, scores, decisions, documents,            │
        │                                    applications, follow-ups, digests, events                 │
        │                     backup ──► ./backups  (both databases + private files, daily)            │
        └──────────────────────────────────────────────────────────────────────────────────────────────┘
 Windows host: notifier.ps1 (sign-in task): notifications · prints PDFs with Edge · heartbeat warnings
```

| Part | Does |
|---|---|
| **n8n** | **Pipeline:** discover → score → digest, on every startup. **Drafting:** pursue webhook, plus a 15-min safety net. **Weekly report.** **Error alerts.** |
| **factbank-api** (`api/`) | Wraps V1's tested logic: discovery and dedupe, BM25 scoring, tailoring, letter checks, packaging. Also serves the app. |
| **Postgres** | The record of everything. Documents stay files on disk; rows point to them. |
| **Desktop helper** (`scripts/windows/notifier.ps1`) | Notifications, follow-ups, the weekly report, health warnings, and printing PDFs with Edge, which is what V1's CV layout was calibrated against. |
| **Fact bank** (`*.yaml`) | Your history, as atomic, confirmed claims. CVs and letters are *renderings* of it. |

Full design and decisions: [docs/ARCHITECTURE-V2.md](docs/ARCHITECTURE-V2.md).
When something is wrong: [docs/RUNBOOK.md](docs/RUNBOOK.md).

## The guardrails (all kept from V1, some now stricter)

- **Nothing invents claims.** Tailoring selects facts by id, and a fixed renderer builds the
  document, so no generated text reaches the page. Each CV has a `trace.json` listing the
  fact behind every bullet, plus checks for traceability, confirmed-only facts, the deny-list
  and numeric integrity.
- **You write the opening.** The letter's checks fail while the TODO block is there.
  Similarity to letters you have already written (`genericness`), a company-specific
  first two sentences, and banned openers are all checked too.
- **You read the CV.** Approve needs an explicit tick. This was the one V1 gate nothing enforced.
- **You submit.** There is no submit anywhere, and there will not be one: terms of service,
  irreversibility, credentials and screening questions all argue against it.
- **The statistics refuse to over-read.** No rate below 25 resolved applications, no reply within
  21 days counts as "not yet", every rate carries a Wilson interval, and "any reply" is kept
  apart from "interview or offer".
- **Silence is checked.** The heartbeat compares what n8n ran with what was recorded.
- **No scraping.** Only official APIs, RSS feeds and company ATS boards (`sources.yaml`).

## Files

```
docker-compose.yml        the stack: postgres, n8n, factbank-api, backup
.env.example              copy via scripts/init_env.py; .env holds the secrets (gitignored)
api/                      factbank-api: main.py (routes), discovery, scoring, drafting, review,
                          applications, report, heartbeat, digests; static/ = the web app
db/migrations/            the schema, applied automatically at API start
n8n/workflows/            pipeline-on-startup, drafting, weekly-report, error-alerts
scripts/                  init_env.py, n8n_install.py, import_v1.py (one-off),
                          windows/notifier.ps1 + install-notifier.ps1
profile/entities/facts/vocab.yaml   the fact bank (private, gitignored; *.example.yaml are templates)
render_config.yaml        CV variants: ds, ai, pm, span, ds-de
sources.yaml              job sources and filter rules
answers.yaml              screening-question answers (private)
discover.py rank.py tailor.py letter.py render.py package.py track.py
                          V1 stage logic; the engine imports these
validate.py confirm.py    fact-bank tools: still the way to edit and confirm facts
docs/                     ARCHITECTURE-V2, RUNBOOK, archived V1 plans and docs
archive/                  Plan 02 (articles), V1 n8n workflows, retired V1 CLIs
```

### Which V1 commands are still safe to run

Run them inside the container (`docker compose exec factbank-api python <script>`), or on the
host with `pip install pyyaml`.

| Safe | Superseded: do not use |
|---|---|
| `validate.py`, `confirm.py` (the fact bank) | `discover.py`, `rank.py --decide`: they write V1's `.state/` files, which the engine no longer reads |
| `render.py` (CV variants into `out/`) | `package.py --sent`, `track.py`: they write `applications.csv`; applications now live in Postgres |
| `tailor.py jobs/<slug>.yaml --explain` (inspect retrieval) | `status.py`: a V1 board (it reads the V1 files) |

`decisions.txt`, `decisions.csv`, `applications.csv` and `.state/` are frozen V1 records. Their
contents were imported into Postgres on 2026-11-05.

## Privacy

Your CV data, letters, applications and the database never leave this PC. Every port is bound to
`127.0.0.1`. The review app has no login on purpose, and is protected instead against other
websites in your browser: a localhost-only Host header, a same-origin check plus a custom
header on writes, and a strict CSP. The `.gitignore` keeps the private YAML, `letters/`, `out/`,
`jobs/`, `.state/`, `backups/` and `.env` out of git. **Do not remove those lines.**

MIT licensed.
