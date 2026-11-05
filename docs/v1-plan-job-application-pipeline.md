> **V1 reference, archived 2026-11-05.** Superseded by [ARCHITECTURE-V2.md](ARCHITECTURE-V2.md); kept for its design reasoning.

# Plan 01 — Job Application Pipeline

**Goal:** every morning, receive a short list of genuinely relevant jobs; for the ones you
approve, receive a tailored CV and a motivation letter draft that are 80% done and
factually grounded. You submit. You never let a machine submit.

**Explicitly not the goal:** mass auto-apply. See [the V1 roadmap](v1-roadmap.md).

**Confirmed setup:**
- **n8n:** self-hosted, Docker, local.
- **Target:** undecided between three archetypes — `data-scientist` / `ml-engineer`,
  `ai-engineer`, `technical-pm`. The pipeline scores every job against all three and
  reports which identity the market is asking for. See the note below on why this is the
  right call and what it costs.
- **CV:** a current one you are happy with exists. Stage 0 is therefore a *decomposition*
  job, not a writing job — roughly 2–3 hours.

---

## Pipeline at a glance

```
[Stage 0]  Master Profile (fact bank)          <- one-off, human-authored
     |
[Stage 1]  Discovery -> normalize -> dedupe    <- scheduled daily, no LLM
     |
[Stage 2]  Rules filter -> embedding score -> LLM re-rank
     |
     +--------------- HUMAN GATE 1: daily digest, you pick ---------------
     |
[Stage 3]  CV tailoring (RAG over your fact bank) -> automated checks
     |
     +--------------- HUMAN GATE 2: you read the CV ----------------------
     |
[Stage 4]  Company research -> letter draft -> genericness check
     |
     +--------------- HUMAN GATE 3: you rewrite the opening --------------
     |
[Stage 5]  Package assembly -> "Ready to send" queue
     |
     +--------------- HUMAN GATE 4: YOU submit. Always. -----------------
     |
[Stage 6]  Outcome tracking -> weekly report -> feeds back into Stage 2
```

Four gates. Each is defended below. Gates 1 and 4 are the ones a junior removes first, and
they are the two that matter most.

---

## Stage 0 — The Master Profile

**This is the whole foundation. Build it before you touch n8n.**

You have a CV you are happy with, so this is a decomposition exercise: **take that CV apart
into records.** Go line by line and turn every bullet into one fact. Then add everything the
CV had to leave out for space — the bootcamp projects, the specific decisions, the numbers
you trimmed. Expect the fact bank to end up 3–4x the size of the CV. That is the point: the
CV is one *rendering* of the bank for one audience, and Stage 3 renders a different one per
job.

Two bonuses from having a CV you already like: it is your **layout template** for Stage 3,
and its phrasing is your **voice reference** for the tailoring prompt.

Not a PDF. Not a Word file. A **structured fact bank** — YAML or JSON — where every single
claim you might ever make about yourself is one addressable record.

```yaml
facts:
  - id: tiri-f2-ensemble
    type: project
    project: TIRI
    period: 2026-07..2026-08
    claim: >
      Built a recall-first (F2) ensemble to rank 2,873 academic papers for relevance
      screening, on 1,852 human-labelled examples across six research questions.
    evidence: github.com/Sylvain-gitty/TIRI---The-Data-science-project
    metrics: [F2, recall@k]
    skills: [python, scikit-learn, embeddings, model-evaluation, imbalanced-data]
    tags: [ml, nlp, ranking, evaluation]
    verified: true

  - id: tiri-logo-insight
    type: insight
    project: TIRI
    claim: >
      Identified that leave-one-use-case-out validation was measuring the wrong thing for
      a per-customer siloed model, and moved the team to grouped k-fold within silo.
    evidence: TIRI/CONTEXT.md section 1
    skills: [experimental-design, cross-validation, stakeholder-communication]
    tags: [ml, evaluation, judgment]
    verified: true
```

### Why this design, and not "give the LLM my CV.pdf"

This is the single most important technical decision in Plan 01, so understand it properly.

An LLM asked to "tailor my CV to this job" from a PDF will, reliably and without warning,
**invent** — a job title that sounds better, a year of experience you do not have, a
technology you have never used. Not often. Often enough. And you will not catch it every
time, because you will be reading the twentieth CV that week.

Structurally preventing this beats prompting against it. If the model's only permitted
operation is **select from and re-phrase these records**, it cannot invent an employer,
because no record contains one. The generation problem becomes a retrieval-and-phrasing
problem — and retrieval you can verify mechanically (Stage 3's traceability check).

This is the same lesson as your `DS-RAG` workshop: ground the generation in retrieved
source material and the hallucination surface collapses. You built it for PDFs. Now build
it for yourself.

### Also in Stage 0

- **Role archetypes.** Write a target-profile paragraph for each of the three, and tag every
  fact with the archetypes it serves. Most facts serve two; a few serve one, and those are
  the interesting ones.

  **On keeping all three open — the honest trade-off.** You chose this, and it is
  defensible: you genuinely do not know yet, and the pipeline can answer the question with
  data instead of a guess. But be clear about the cost, because "keep options open" is
  never free:

  - Three profile paragraphs, three embeddings, three-way tagging of every fact. Maybe 40%
    more Stage 0 work.
  - Your Gate 1 labels get split three ways, so the Stage 2 tuning that needed ~100
    decisions now needs closer to 250 before any single archetype has enough signal.
  - Three positioning stories means none of them is sharp yet. A `technical-pm` CV and an
    `ml-engineer` CV should lead with different projects and a different first sentence.

  So treat this as a **time-boxed experiment, not a permanent state.** Run all three for
  six weeks, then look at response rate by archetype and commit to one or two. Write that
  decision date into the plan now, because the failure mode is running all three for six
  months and being mediocre in each. This is ordinary product discipline: exploration is
  correct early, and expensive if you never exploit.
- **A deny-list.** Technologies and claims that must never appear (Spark, Kubernetes,
  "5 years experience" — whatever is true for you). Stage 3 checks it mechanically.
- **A CV template** with named placeholders. Google Docs (native n8n node, easiest v1) or
  LaTeX/Typst (better output, more setup). Start with Docs.

- **An `outcome` field on every fact, where one exists.** Not just what you built — what
  changed because you built it. "Ranked 2,873 papers so analysts read the relevant ones
  first" beats "built an ensemble classifier."

  This costs you ten extra minutes and pays twice. CV bullets with outcomes beat CV bullets
  with technologies, and the same field is exactly what [Plan 02](../archive/plan02/02-blog-article-pipeline.md)
  needs for its consulting proof points later. **The fact bank is the shared spine of both
  plans** — build it once, render it as a CV, as article evidence, and eventually as
  case-study material. Notice how often a well-structured store of facts turns out to be
  worth more than any single artifact you render from it.

**PM note:** you will resent this stage. It is 4–6 hours of unglamorous writing with no
visible output. It is also the reason the rest of the pipeline works. Every hour skipped
here is paid back threefold in Stage 3 debugging.

### Stage 0 ends with a new CV — not the old one

**Status: the bank is built and seeded** — see [`fact-bank/`](../README.md).
38 facts, 11 entities, all `status: draft` until you confirm them.

The existing Lebenslauf was the *input* to the bank, not the output. It contains no
projects at all, states responsibilities rather than outcomes, and claims six skills the
bank cannot currently evidence. So the last action of Stage 0 — **after** the outcomes are
filled in and the facts confirmed — is to render a fresh CV from the completed bank:

```
current CV  ->  fact bank  ->  fill outcomes + add projects  ->  NEW CV
   (input)      (source of truth)      (the real work)         (output)
```

Render a master CV (2–3 pages, never sent, your reference), then one per archetype at one
page each. Rebuilding the CV *before* the bank is finished only reformats the same gaps.
Do not move to Stage 1 engineering thinking Stage 0 is done until that new CV exists.

---

## Stage 1 — Discovery, normalization, deduplication

**Status: built.** `fact-bank/discover.py` + `fact-bank/sources.yaml`. Runs standalone
today; the n8n wrapper is a Schedule Trigger plus an Execute Command node calling it.

**What the sources actually permit, tested 2026-09-01 rather than assumed:**

| Source | Access | Status |
|---|---|---|
| RemoteOK | public JSON API | working, requires link-back attribution |
| Working Nomads | public JSON API | working |
| Berlin Startup Jobs | RSS | working |
| Arbeitnow | documented free API | working, German market |
| Bundesagentur für Arbeit | official API | ready, needs a free client ID |
| Indeed.de, StepStone.de, XING, JobLeads | — | `robots.txt` disallows job paths |
| Welcome to the Jungle | — | HTTP 403 |
| justjoin.it | — | API returns 503/404 |
| relocate.me, EuroJobs | — | no feed offered |

**For the eight that permit nothing: subscribe to their alert emails.** You use the
service exactly as designed, they push matches to you, and an n8n IMAP trigger reads the
mailbox. It is legal, it survives the redesigns that break scrapers, and it cannot get
your account banned mid-search. The trade-off is that you only see what their matcher
sends — so set the alert criteria broad and let Stage 2 filter, rather than pre-filtering
in their UI.

**The tier that beats all of them is still empty:** company career boards. Greenhouse,
Lever, Ashby and Personio each expose public JSON per company. Pick the 30–50 employers
you actually want and you see their openings the day they post, before any aggregator
indexes them. `company_boards` in `sources.yaml` is where those go.

**Two things the first real runs taught, both worth more than the code:**

1. **A positive relevance gate is not optional.** With only negative rules, "remote"
   admits every job on the planet — the first run surfaced an MOT Tester, a Shunter and a
   Handyperson. Dropping what you do not want is not the same as keeping what you do.
2. **Match on word boundaries, never substrings.** `"ai" in title` matches ret**ai**l,
   m**ai**ntenance, c**ai**ptain and m**ai**l, which is how a Bell Captain reached the
   shortlist. Short tokens are exactly where naive substring matching fails.

Live run: **332 postings → 7.** Stage 2a is tuned for recall at zero cost, not precision;
its job is to make the survivors reviewable in thirty seconds.

**n8n:** `Schedule Trigger` -> `HTTP Request` xN -> `Code` (normalize) -> `Merge` ->
`Postgres` (dedupe + insert).

### Sources — use APIs, not scrapers

Ranked by "will this still work in six months":

| Tier | Source | Note |
|---|---|---|
| Best | **Bundesagentur fuer Arbeit Jobsuche API** | Official, free, huge German coverage |
| Best | **Greenhouse / Lever / Ashby / Personio boards** | Public JSON endpoints per company. Build a watchlist of 30–50 target employers. Highest signal of any source. |
| Good | **Adzuna, Jooble, The Muse, Remotive, Arbeitnow** | Free API tiers, aggregate coverage |
| Good | **Company careers RSS** | Where offered |
| Avoid | **LinkedIn / Indeed scraping** | Against ToS, actively blocked, risks the account you are job-searching with. Search those manually. |

The company-board tier is the one juniors overlook and it is the best one: you decide
which 40 companies you actually want, and you see their openings the day they post, before
aggregators index them.

### Normalize to one schema

```
job_id            hash(company_norm + title_norm + location_norm)
title, company, location, remote_flag, seniority_hint
posted_at, url, source, salary_raw, language
description_raw
```

### Dedupe

The same job appears on five boards. Two layers:

1. **Exact:** the `job_id` hash. Catches most of it.
2. **Near-duplicate:** two postings from the same company whose description embeddings
   have cosine > 0.95 within a 14-day window are one job. Keep the source closest to the
   employer (company board beats aggregator).

**DS note:** this is your first real data-engineering problem here and it is a good one.
Normalizing company names is deceptively hard — "Zalando SE", "Zalando", "zalando.de".
Do not over-engineer it. Lowercase, strip legal suffixes, strip punctuation: that gets 90%
in ten minutes. Ship it, look at what leaks through, fix only what actually appears.

---

## Stage 2 — Three-stage scoring

The architecture is **kill cheaply, then think expensively**. Never send 200 job
descriptions to a strong model; you will spend 40 euros in a week and learn nothing.

### 2a — Rules (free, kills 50–70%)

Deterministic drops: wrong country, wrong language, clearance you lack, "10+ years",
explicitly senior/principal, contract types you refuse, agency-spam patterns.

Keep these in an editable list, not hardcoded in a Code node. You will change them weekly.

### 2b — Embedding similarity (cheap, ranks the rest)

Embed the job description; cosine against each of your three role-archetype embeddings.
Keep the max **and the argmax** — the score, and which identity this job wants.

Do not treat the threshold as fixed truth. Set it loose at first (deliberately high
recall), then tune it against your own Gate 1 decisions once you have ~100 of them. That is
exactly the recall-first-then-tune-precision posture from TIRI's `CONTEXT.md`.

**n8n:** Embeddings node + a vector store (pgvector on the same Postgres, or Qdrant).

### 2c — LLM re-rank (expensive, top ~15/day only)

Structured output:

```json
{
  "fit_score": 0,
  "archetype": "ml-engineer | data-scientist | technical-pm",
  "matched_requirements": ["..."],
  "missing_requirements": ["..."],
  "red_flags": ["unpaid trial task", "no salary band"],
  "one_line_why": "..."
}
```

`missing_requirements` is the most valuable field and the one you would not think to ask
for. Aggregated over 100 jobs it tells you exactly which skill gap is costing you
interviews — a **curriculum generated from the market** rather than from a bootcamp
syllabus.

---

## HUMAN GATE 1 — The daily digest

**What happens:** one message (Telegram or email) at 08:00 with the top 10. Each shows
title, company, fit score, archetype, the one-line why, top 2 missing requirements, link.
Two buttons: **Pursue** / **Skip**.

**Why this gate exists:** the model does not know you met someone from that company and
disliked them, that the commute is impossible, that you are done with agencies. It also
cannot yet know what you want, because you have only told it what you wrote in a profile
paragraph.

**The part juniors miss:** this gate does *two* jobs. It filters today, and it **collects
labels**. Every Pursue/Skip is a training example. After ~150 decisions you can fit a model
on `(job features, embedding score, LLM fields) -> your decision` and either replace or
calibrate Stage 2. Your job search becomes a supervised learning problem with you as the
annotator — precisely the loop `academic_research_agent` implements for papers. Same
pattern, different domain. Build the logging now, even though you cannot use it for two
months.

**n8n:** `Wait` (on webhook call) + a Telegram inline keyboard, or a Form Trigger.

---

## Stage 3 — CV tailoring

**Status: built.** `fact-bank/tailor.py` — run it on a job YAML and it produces a tailored
CV, a traceability file and a check report. See [`README.md`](../README.md).

Two deviations from what this plan originally specified, both deliberate:

- **Retrieval is BM25, not embeddings.** For 38 facts, embedding infrastructure is
  over-engineering: BM25 is instant, deterministic, needs no key, and is inspectable via
  `--explain`. Switch when the bank passes a few hundred facts.
- **The LLM is optional and runs as a challenger.** The deterministic selector runs first
  and always; `--llm` re-selects from the same candidates and reports the diff. Ship the
  baseline, measure the challenger.

Runs only on approved jobs — typically 2–5 per day, not 200, which is why you can afford a
strong model here.

**Step 1 — Retrieve.** For each requirement extracted in 2c, pull the top-k matching
records from the Stage 0 fact bank by embedding similarity. This is RAG over yourself.

**Step 2 — Select and phrase.** The LLM receives the job's requirements, the retrieved fact
records, and the CV structure. It returns JSON: which facts go in which section, in what
order, phrased for this job. **Every bullet must carry the `id` of the fact it came from.**

**Step 3 — Render deterministically.** JSON -> template. The LLM never produces the
document; it produces the *content decisions*, and code produces the file. This keeps
formatting stable and diffs readable.

**Step 4 — Automated checks, before you ever see it:**

| Check | Fails when |
|---|---|
| **Traceability** | a bullet's `fact_id` is missing or not in the fact bank |
| **Deny-list** | a forbidden technology or claim appears |
| **Length** | over one page (two only with justification) |
| **Keyword coverage** | fewer than X% of the job's hard requirements appear verbatim — ATS parsers do literal matching, this is not superstition |
| **Numeric integrity** | a number appears that is not in the source record |

A failed check does not silently regenerate. It flags, and names the check that failed.
Silent retries hide systematic problems.

---

## HUMAN GATE 2 — Read the CV

**Every time. No exceptions, no "it has been fine for twenty in a row."**

**Why this gate exists:** the automated checks catch mechanical failures. They cannot catch
the CV that is accurate, passes every check, and is subtly *wrong for this job* — leads
with the wrong project, buries the thing they actually care about. That is judgment, and it
costs you thirty seconds.

Also: the traceability check verifies a bullet came from a record. It does not verify the
record was rephrased **honestly**. "Contributed to model evaluation" can become "led model
evaluation" with a perfectly valid `fact_id` attached. You are the only check on that — and
it is the check that matters, because that sentence is what you will be asked about in the
interview.

---

## Stage 4 — Motivation letter

**Status: built.** `fact-bank/letter.py`. Draft, gates, render.

**One deviation, and it matters.** The plan said to fetch the company's about page. The
build does not: guessing a homepage from a company name is fragile, and a wrong page
produces a letter that is confidently specific about the *wrong company* — the worst
failure this stage can have. Hooks are extracted from the posting instead, which is the one
document you know is theirs.

**Gate 3 is enforced by the data, not by discipline.** The draft ships with the opening as a
TODO block and every gate fails while it is present, exactly like `status: draft` on facts.
`--render` produces nothing until you have written those two sentences yourself.

Tested against a deliberately generic opening — *"I am writing to apply… 12 years of
experience delivering value"* — five gates fired simultaneously: no company noun, a dead
opener, too similar to a previous letter, a fabricated number, and a deny-listed phrase.

**Step 1 — Company research.** Deterministically fetch the company's about/product page
and, where available, recent news or their engineering blog. Extract 3–5 concrete facts.
Not vibes — facts: a product name, a market, a stated engineering principle, a launch.

**Step 2 — Draft.** Three blocks:
- **Hook:** why *this* company. Must contain at least one fact from Step 1.
- **Evidence:** two proof points from the fact bank, mapped to their top two requirements.
- **Close:** what you want and what you bring. Short.

**Step 3 — Genericness check.** My favourite check in either plan, and pure data science
applied to your own output:

- Embed the draft, compare against your last 20 letters. **Cosine > 0.90 -> reject as
  boilerplate.** If a machine cannot tell this letter apart from the last one, neither can
  the reader.
- Require at least one proper noun from Step 1 in the first two sentences.
- Reject any draft opening with "I am writing to apply for" and friends. Maintain the
  ban-list; add to it every time you cringe.

---

## HUMAN GATE 3 — Rewrite the opening yourself

**Why this gate exists:** the first two sentences are the only part with a high probability
of being read carefully, and they are where a human voice is most detectable and most
valuable. An LLM writes competent, forgettable openings. That is the one place in this
entire pipeline where forgettable is fatal.

Rule of thumb: automation gets a letter to 70%. The last 30% is you, and it is the 30% that
does the work. If you find yourself sending unedited drafts, the pipeline has become a
liability — turn it off and write by hand until you care again.

---

## Stage 5 — Package and queue

**Status: built.** `fact-bank/package.py` + `answers.yaml`.

Assembles the tailored CV, the rendered letter, a submission checklist with your screening
answers filled in, and a two-date follow-up `.ics` into one folder — and **refuses to
assemble while any gate is failing**, naming which.

**There is no `--submit` flag and there will not be one.** That is Gate 4, and the four
reasons are in the module docstring. What the stage removes is the twenty minutes of
assembly around a submission, not the submission.

Two screening answers are deliberately never generated: *"why us?"* is marked `PER_JOB`
(a stored answer to it is the generic-letter problem in a different hat), and *salary
expectation* is left blank, because a number invented on your behalf is a number you would
have to defend.

n8n assembles a record in your tracker (Notion / Airtable / Postgres with a simple view):

- CV PDF, letter, job URL, deadline, contact if known
- Pre-written answers to the common screening questions
- Status: `ready` -> `sent` -> `responded` -> `interview` -> `closed`

### HUMAN GATE 4 — You submit. Always.

Four independent reasons, any one of which is sufficient:

1. **Terms of service.** Automated submission is prohibited on most job platforms. The
   downside is losing the account you are job-searching with.
2. **Irreversibility.** A letter with the wrong company name cannot be recalled, and it is
   the single most common catastrophic failure in automated applications. Everyone has done
   it once by hand — now imagine it firing eight times before you notice.
3. **Credentials and personal data.** Portal logins, CAPTCHAs, address and salary fields.
   Automating credential entry and form submission on your behalf is exactly the category
   of action that stays in human hands.
4. **Screening questions.** "Why us?", "Notice period?", "Salary expectation?" — answered by
   a person, or answered badly.

**What n8n *can* do here:** produce the email draft for email applications (unsent),
pre-fill your answer bank so you paste rather than type, and set follow-up reminders at day
7 and day 14. That is most of the pain without any of the risk.

---

## Stage 6 — Track and learn

**Status: built.** `fact-bank/track.py`, logging to `applications.csv`.

The report is built to refuse conclusions the data cannot support:

- **Below 25 resolved applications it prints no rate at all**, and shows the Wilson
  interval instead. At 7/19 that interval is 19%–59%.
- **Applications inside a 21-day window are censored, not counted as rejections.** No reply
  is not-yet-observed, and treating it as failure biases every rate downwards precisely
  when you are most active.
- **It compares point estimates rather than listing them.** On simulated data seeded with a
  real effect it reported 50% against 12% and still said the intervals overlap, so it is
  not yet a difference you can act on.

That last one is the whole stage in one line, and it is your own bootstrap discipline
turned on your job search.

Every application row records: fit score, archetype, source, CV version, letter version,
sent date, outcome, days-to-response.

**Weekly n8n report:**
- Response rate by source, by fit-score bucket, by archetype, by CV version
- Funnel: surfaced -> pursued -> sent -> responded -> interview
- Where the drop-off is worst — that is where next week's work goes

### How to read this like a data scientist, not a gambler

1. **n is small and you will over-read it.** 12 applications and 1 response is not evidence
   about your CV. Wait for ~40 before believing anything, and think in intervals, not point
   estimates.
2. **You are changing every variable at once.** New CV, new sources, new letter tone, same
   week — then you cannot attribute anything. **Hold the CV template fixed for 25
   applications** before changing it. A/B discipline at a sample size that barely supports
   it is exactly why you must be strict.
3. **The outcome is censored.** "No reply" after 5 days is not a rejection, it is
   not-yet-observed. Treat time-to-response as survival data, not a binary. Your
   `DS-hypothesis-testing` and `DS-timeseries` work both apply here.

**PM framing:** your job search is a product with one metric — interviews per week — and a
four-stage funnel. Instrument it like one and you will make better decisions than someone
applying to twice as many jobs on vibes.

---

## Risk register

| Risk | Mitigation |
|---|---|
| Hallucinated CV claim | Fact bank + traceability check + Gate 2 |
| Wrong company in letter | Genericness check + Gate 3 + Gate 4 |
| Account ban | No scraping, no auto-submit, respect rate limits |
| Cost runaway | Model tiering; hard daily cap on 2c calls |
| Duplicate application | Dedupe on `job_id` plus a company-level 60-day cooldown |
| PII leaving your machine | Self-hosted n8n; never log full CVs to third-party services |
| Credential leakage | n8n credential store only; never in Code nodes; `.env` out of git |
| Pipeline silently dead | `Error Trigger` workflow to alert you, plus a daily heartbeat |

---

## MVP: what to build first

**Week 1 is Stage 0 + Stage 1 + a keyword filter + a digest email.** No embeddings, no LLM.
If that alone saves an hour a day and surfaces jobs you would have missed, the project is
already justified — and you will have learned n8n fundamentals on a workflow simple enough
to debug.

Add 2b/2c in week 2. Do not build Stages 3–4 until Stage 2 surfaces jobs you genuinely want
to apply to. Building a CV tailor on top of a pipeline that surfaces bad jobs is optimising
the wrong half.
