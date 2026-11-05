> **V1 reference, archived 2026-11-05.** Superseded by [ARCHITECTURE-V2.md](ARCHITECTURE-V2.md); kept for its design reasoning.

# Current system — architecture summary (pre-rebuild snapshot, 2026-11-05)

What this repo is, how it works, what it needs from you, and where. Written as the
reference for the rebuild: what to keep, what to change, and what not to lose.

---

## 1. Repository layout

```
n8n-automations/                  outer repo: branch master, NO commits yet
├── README.md                     shared philosophy + build order for both plans
├── 01-job-application-pipeline.md   Plan 01 design doc (job search)
├── 02-blog-article-pipeline.md      Plan 02 design doc (articles / content)
└── fact-bank/                    NESTED git repo -> github.com/Sylvain-gitty/cv-factcheck-bank
    ├── *.py                      14 Python CLIs, one per stage (~6,900 lines total)
    ├── *.yaml                    config + your personal data (most are gitignored)
    ├── n8n/                      2 workflow JSONs + README (written, never imported/tested)
    ├── jobs/        190 files    discovered postings (gitignored)
    ├── letters/      77 files    letter drafts + evidence packs (gitignored)
    ├── out/         502 files    rendered CVs, digests, tailored job dirs, packages (gitignored)
    ├── articles/      empty      Plan 02 drafts
    └── .state/                   seen.json, scores.json, decisions.json, bridge-token
```

Git state: `fact-bank` is on `main`, last commit 2026-09-18 (`c2bdbc0`), plus a branch
`fix/silent-failures-in-decide-and-tailor` with nothing ahead of main. The outer repo has
never been committed; the two plan docs and README are untracked.

Stack: **Python 3.11 + PyYAML only.** No database, no embeddings, no required API key.
Optional LLM calls via `OPENROUTER_API_KEY` / `OPENAI_API_KEY`. Output is HTML with print CSS
(+ PDF via `render.py --pdf`). n8n is an optional scheduler layer reached through a local HTTP
bridge.

---

## 2. The goal it was built for

**Plan 01 (built, in use):** every morning, a short list of relevant jobs; for the ones
you approve, a tailored CV and letter draft that are ~80% done and factually grounded. You
submit — the machine never does.

**Plan 02 (half-built, unused):** problem-centric pillar articles anchored to repos you
own, for hiring signal first, with a consulting brand kept "latent". Pipeline A (evidence
pack → draft → gates → render) exists; Pipeline B (LinkedIn / newsletter derivatives) was
never built. No article has been written.

**Core principle, enforced throughout:** *automate the assembly, never the judgment.* Each
pipeline is a funnel that ends at a human gate, and the gates are enforced **by the data**
(TODO blocks, `status: draft`) instead of by reminders.

---

## 3. Data model — the fact bank (the spine of everything)

| File | Holds | Shape |
|---|---|---|
| `profile.yaml` | identity, contact, 3 role archetypes, territory, deny-list, forbidden verbs | `owner{}`, `archetypes[{id,label,profile,profile_de,match_text}]`, `deny_list.terms`, `forbidden_verbs{sole,co-authored,team}` |
| `entities.yaml` | things you did over a period (jobs, projects, degrees). **9** entities | `id, kind, authorship (sole/co-authored/team), dates, org, role` |
| `facts.yaml` | atomic claims, each on one entity. **29, all `confirmed`** | `id, entity, type, claim, claim_short, claim_de, outcome(_short/_de), contribution, scope, evidence, metrics[], skills[], archetypes[], strength 1–3, status, publishable, confidential, interview_hook, related` |
| `vocab.yaml` | controlled skill vocabulary + aliases + skill groups | validator rejects unknown tags/aliases |
| `render_config.yaml` | CV variants: `master, ds, ai, pm, span, ds-de` | archetype filter, section order, page target, fact caps, language |
| `answers.yaml` | screening-question answer bank | `why_us: PER_JOB`, salary deliberately null |
| `sources.yaml` | job sources + filter rules | 13 APIs/RSS (10 on), 8 email-alert sources (documented only), 47 company boards (Greenhouse/Lever/Ashby/Personio) |
| `content-sources.yaml` | Plan 02 allow-list: repos you may write about | `tiri, airpollution, cvfactbank` + `authorship, collaborators, share`, voice pack, positioning |

**Two-text rule** used everywhere: one field for humans, one for retrieval
(`claim_short`/`claim`, `profile`/`match_text`).

**Guardrails on the bank:** `status: draft→confirmed`; `contribution: supported` never
renders; `scope: operated` blocks creator verbs; per-authorship forbidden verbs (no "led" on
team work); deny-list; derived skills section (only skills a rendered bullet evidences);
numeric integrity.

---

## 4. The pipeline, stage by stage

```
[0]  Fact bank         validate.py · confirm.py · render.py        one-off, you author it
[1]  Discovery         discover.py  -> jobs/*.yaml                  daily, no LLM
[2a] Rules filter      (inside discover.py)                         free, recall-tuned
[2b] Score + rank      rank.py      -> out/digest.md, decisions.txt BM25 vs archetypes
[2c] LLM re-rank       rank.py --llm (optional, top N)              structured JSON
     ── GATE 1: you tick p/s in decisions.txt -> rank.py --decide ──
[3a] Triage            triage.py    -> sort pursues by bank coverage
[3]  CV tailoring      tailor.py    -> out/jobs/<slug>/cv.html …    BM25 + greedy set cover
     ── GATE 2: you read the CV (not enforced) ──
[4]  Letter            letter.py    -> letters/<slug>.md            draft with TODO opening
     ── GATE 3: you write the opening; --render refuses until gates pass ──
[5]  Package           package.py   -> out/applications/<slug>/     CV+letter+checklist+.ics
     ── GATE 4: YOU submit, then package.py --sent <slug> ──
[6]  Track + report    track.py · status.py -> applications.csv     Wilson intervals, censoring
```

### Stage 0 — fact bank (`validate.py`, `confirm.py`, `render.py`)
- `validate.py`: schema/integrity, vocab, verb guardrails, coverage report. Exit 0/1/2.
- `confirm.py`: writes `out/worksheet.md` + `confirm.txt`; you tick `[x]`; `--apply` flips to confirmed.
- `render.py`: deterministic. Selects, orders, caps, formats — **never writes prose**. Emits
  `<variant>.html/.md/.trace.json`. Calibrated page estimator. Draft watermark.

### Stage 1 + 2a — discovery (`discover.py`)
- Sources: JSON APIs, RSS, 4 ATS adapters, `--url` for a posting you found yourself. **No scraping.**
- Normalise to one schema → exact dedupe (hash of company+title+location) → near-dupe
  (same company, similar title, 14 days) → rules filter: positive title gate, word-boundary
  matching, region-lock phrases (not country names), `max_per_source` cap.
- Output: one YAML per job in `jobs/` (same shape `tailor.py` consumes); history in `.state/seen.json`.
- Email-alert sources (Indeed, StepStone, XING…) are listed but **not implemented** — meant for an n8n IMAP trigger that was never built.

### Stage 2b/2c — ranking (`rank.py`)
- BM25 index over the batch of jobs, each archetype's `match_text` as the query.
- Batch-relative 0–100 score; archetype argmax with a **30% margin rule** (else "ambiguous").
- Optional LLM re-rank of top N → `fit_score, archetype, matched/missing_requirements, red_flags, one_line_why`.
- Writes digest + `decisions.txt`; `--decide` snapshots features at decision time into
  `.state/decisions.json` + `decisions.csv` (training data). `--reopen <slug>` undoes.

### Stage 3a — triage (`triage.py`)
Runs tailoring on every pursue and sorts by how many of the posting's skills the bank
evidences (count first, share second). Exists because Gate 1 produced 59 pursues vs.
~8–10 applications/week of capacity.

### Stage 3 — CV tailoring (`tailor.py`)
- Requirements from the job YAML, or extracted heuristically from the description.
- BM25 retrieval per requirement → greedy set cover (credit capped at 2 requirements per
  fact, weighted by strength) → skill backfill.
- `--llm` is a **challenger**: re-selects fact IDs only, reports the diff vs. baseline.
- Checks: traceability, confirmed_only, deny_list, numeric_integrity (fatal);
  keyword_coverage ≥60%, length (warnings). Outputs uncovered requirements = your skill gap.
- No job argument → batch mode over the whole pursue list (CV + letter draft).

### Stage 4 — letter (`letter.py`)
- Uses the same facts as the CV. Company hooks extracted **from the posting only** (no web fetch).
- Draft in `letters/<slug>.md` with the opening as a TODO block; `--llm` can fill the middle; `--pack` writes a briefing pack.
- Gates: `opening_is_yours, company_specific, no_dead_openers, genericness (<0.75 vs. past letters), numeric_integrity, deny_list, length 250–400`.
- `--render` → HTML/PDF only when fatal gates pass.

### Stage 5 — package (`package.py`)
Assembles CV + letter + `CHECKLIST.md` (answers pre-filled) + `follow-up.ics` (day 7/14).
Refuses while any gate fails. `--list` = ready/blocked queue. `--sent` logs the send.
**No submit flag, by design.**

### Stage 6 — tracking (`track.py`, `status.py`)
- `applications.csv`: slug, company, title, source, archetype, score, cv_variant, letter, sent_date, first_reply_date, status, notes. You edit outcome columns by hand.
- Report: no rate below 25 resolved, Wilson 95% intervals, 21-day censoring window, warns on variant churn.
- `status.py`: board of every pursue (pursued → drafted → tailored → applied), **derived from artefacts**, with the next command per job.

### Plan 02 — articles (`article.py`)
`--list`, `--evidence <repo>` (code-only evidence pack from confirmed facts + declared repo
files), `--new <repo> "<thesis>"` (skeleton, intro/conclusion as TODO), `--check`, `--render`.
Gates: intro/conclusion written, problem-centric title, numeric integrity, ban-list,
shared-work voice ("we" on team work).

### n8n layer (`bridge.py` + `n8n/*.json`)
- `bridge.py`: HTTP server on `127.0.0.1:899`, bearer token in `.state/bridge-token`, fixed
  action allowlist (`discover, rank, decide, tailor, letter, letter_check, package, queue, sent, report, open, validate`), slug regex validation.
- `daily-pipeline.json`: 07:00 weekdays → discover → rank → email digest → **Wait node (Gate 1 via resume links)** → tailor + letter → notify email. Failure alert branch.
- `weekly-report.json`: Friday 18:00 → report + open items + queue → email.
- Status: **written against the schema, never imported into a running n8n.** Needs `BRIDGE_TOKEN, BRIDGE_PORT, NOTIFY_EMAIL` variables and an SMTP credential.

---

## 5. Inputs required from you, and when

| When | Input | Where it goes | Enforced? |
|---|---|---|---|
| Setup (one-off) | Contact details, languages, work authorization | `profile.yaml → owner` | — |
| Setup | 3 archetype texts: `profile` (EN), `profile_de`, `match_text` | `profile.yaml → archetypes` | — |
| Setup | Deny-list (tech/claims you can't defend) | `profile.yaml → deny_list` | checked at validate/render/tailor/letter |
| Setup | Entities: jobs/projects/degrees, dates, authorship | `entities.yaml` | validator |
| Setup | Facts: claim, short claim, outcome, metrics, skills, contribution, strength | `facts.yaml` | validator + vocab |
| Setup | Confirm each fact (true, right verb, defensible, numbers right) | tick `confirm.txt` → `confirm.py --apply` | **yes** — drafts never render |
| Setup | Screening answers (notice, location, salary…) | `answers.yaml` | null flagged; salary never generated |
| Setup | Target employers (probe all 4 ATS patterns) + filter rules | `sources.yaml` | — |
| Setup (n8n only) | Bridge token, port, notify email, SMTP | n8n Variables / credentials | — |
| Optional | `OPENROUTER_API_KEY` / `OPENAI_API_KEY`, `RANK_MODEL`/`TAILOR_MODEL`/`LETTER_MODEL` | env of the bridge/shell | falls back to prompt-to-file |
| **Daily – Gate 1** | Pursue/skip per job | `decisions.txt` → `rank.py --decide` (or n8n email link) | **yes** — nothing tailored without pursue |
| Ad hoc | A posting you found yourself | `discover.py --url <url>` | — |
| **Per job – Gate 2** | Read the tailored CV, pick variant | `out/jobs/<slug>/cv.html` | **no** — discipline only |
| **Per job – Gate 3** | Write the letter's opening two sentences, edit the body | `letters/<slug>.md` → `letter.py --render` | **yes** — TODO block fails gates |
| Per job | "Why us?" answer | portal, by hand | `PER_JOB` marker |
| **Per job – Gate 4** | Submit on the portal; then log it | `package.py --sent <slug>` | **yes** — no submit path exists |
| Ongoing | Reply dates, outcomes, notes | `applications.csv` (by hand) | — |
| Plan 02 | Pick repo + thesis, write intro & conclusion, publish | `article.py --new`, `articles/<slug>.md` | **yes** — TODO blocks |

---

## 6. Current state of the data (what exists to migrate)

| Asset | Count |
|---|---|
| Facts / entities | 29 confirmed / 9 (TIRI, air pollution, n8n automation, 3 education, 3 roles) |
| Job postings discovered | 190 YAMLs |
| Gate 1 decisions | 191 (59 pursue, 132 skip) — labelled dataset with features at decision time |
| Tailored job dirs | 61 |
| Letters | 77 files (drafts + 5 briefing packs) |
| Applications | 14 (7 sent, 7 ready); by archetype: ai-engineer 8, technical-pm 5, data-scientist 1 |
| Articles | 0 |

The six-week archetype experiment from the plan has not reached the 25-resolved threshold.

---

## 7. What's known to be rough or unfinished

- **Docs are stale.** Top-level README still says "Not started"; onboarding says 29 facts, notes say 38.
- **n8n never ran.** Workflows untested; email-alert/IMAP ingestion not built.
- **Gate 2 is the only unenforced gate.**
- **Lexical only.** BM25 misses semantic matches ("paired bootstrap" ≠ "rigorous validation"); embeddings were deferred until the bank grows.
- **Gate 1 too generous for capacity** (59 pursues) — triage was bolted on afterwards.
- **State is spread over flat files** (YAML, CSV, JSON, .txt tick-files); no database, despite the plan's "log everything to Postgres".
- **Personal data and tooling share one folder**; privacy depends on `.gitignore`. The outer repo has no `.gitignore` at all.
- **Two nested git repos**, the outer one uncommitted.
- Plan 02 Pipeline B and the consulting territory (withdrawn 2026-08-28) are open.

---

## 8. Things worth carrying into the new architecture

Whatever the new goal, these held up and were each forced by real failures:

1. A structured, atomic **source of truth**; documents are renderings of it.
2. **Generation = selection by ID + deterministic rendering** (no free text reaches the output), with a trace file.
3. **Human gates enforced by data**, not reminders.
4. **Cheap deterministic baseline first, LLM as a measured challenger.**
5. **Recall-first filters**, word-boundary matching, "missing data is not permission".
6. **Snapshot features at decision time**; decisions are training labels.
7. **Honest statistics**: intervals, censoring, small-n refusals.
8. **Provenance by `git log` + LICENSE**, allow-lists instead of folder scans.
9. **Narrow, authenticated local bridge** between the orchestrator and the code.
10. **Look at the rendered artefact.**
