> **V1 reference, archived 2026-11-05.** Superseded by [ARCHITECTURE-V2.md](ARCHITECTURE-V2.md); kept for its design reasoning.

# n8n Automations — Roadmaps

Two pipelines, one philosophy. Read this file before either plan; it contains the
reasoning that both plans assume.

| Plan | What it does | Status |
|---|---|---|
| [01 — Job Application Pipeline](v1-plan-job-application-pipeline.md) | Discover → score → tailor CV → draft letter → hand you a ready-to-send package | Not started |
| [02 — Blog & Content Pipeline](../archive/plan02/02-blog-article-pipeline.md) | Projects → pillar articles → light distribution. **Hiring signal first**, with a consulting brand built quietly underneath | Not started |

**Confirmed decisions:** n8n self-hosted locally in Docker · job search runs all three role
archetypes as a six-week experiment · a current CV exists, so Plan 01 Stage 0 is
decomposition not authoring · Plan 02 optimises for hiring signal, with consulting
positioning kept **latent** — assets built now, the offer switched on later.

---

## The one idea both plans are built on

> **Automate the assembly. Never automate the judgment.**

The scarce resource in both workflows is not your typing speed. It is your judgment —
which job is worth pursuing, which claim in your capstone is actually interesting. A
pipeline that automates the drudgery and stops at your desk is worth a lot. A pipeline
that automates the judgment produces volume that actively damages you: generic
applications that tank your response rate, LLM-slop articles that a hiring manager reads
as a negative signal.

So both pipelines are designed as **funnels that terminate in a human gate**, not as
end-to-end robots. Every gate below is deliberate. When you are tempted to remove one,
re-read the "why this gate exists" line first.

## Why this is the professional pattern, not timidity

Three separate arguments, and they stack:

1. **Quality economics.** Response rate matters more than application count. 20 tailored
   applications at a 15% response rate beat 200 generic ones at 1%. Same for articles.
2. **Irreversibility.** A submitted application with the wrong company name in the letter
   cannot be recalled. A published article with a fabricated metric is a credibility
   event. Actions that cannot be undone get a human.
3. **Terms of service.** Most job platforms prohibit automated submission and bot
   traffic. An account ban mid-search is a self-inflicted catastrophe.

## The two hats, applied

You asked to see this from both positions. They ask different questions about the same
pipeline, and you should run both passes on every stage you build.

**Product Manager asks:**
- What is the actual bottleneck? (Not "what is automatable" — those are different.)
- What is the smallest version that delivers value this week?
- What is the cost of a wrong output, and who pays it?
- How do I know this is working? What number moves?

**Data Scientist asks:**
- What is the input distribution, and how does it drift?
- Where is the ground truth, and am I collecting it?
- What is the cheap filter, and what is the expensive model? (Never run the expensive
  one on everything.)
- What is the failure mode when the model is confidently wrong?

Applied to Plan 01, those two passes produce the same architecture as your own capstone:
a **cheap high-recall filter feeding an expensive precise re-ranker**. You already built
this in TIRI. You are about to build it again for your own career. Notice that.

## Shared infrastructure decisions

These are decided once and used by both plans.

### Self-host n8n

Recommended: **Docker, locally.** Reasons, in order of weight:

1. Plan 01 handles your CV, address, and application history. That is personal data. It
   does not need to live on someone else's server.
2. Plan 02 needs to read this Bootcamp folder. n8n Cloud cannot see your local disk.
   (Alternative: push the projects to GitHub and use the GitHub node — you already have
   most of them there under `Sylvain-gitty`. That works too, and is more portable.)
3. Cost: free, versus a subscription, while you are learning and will build many broken
   workflows.

Cost of self-hosting: you own uptime and backups. For a personal workflow that runs once
a day, that is an acceptable trade.

### Model tiering

Never use one model for everything. Budget dies in the filter stage.

| Job | Model class | Why |
|---|---|---|
| Embedding / similarity | Small embedding model | Thousands of calls, no reasoning needed |
| Bulk filtering, extraction | Cheap fast model | High volume, structured output, low judgment |
| Drafting, re-ranking, critique | Strong model | Low volume, high judgment, quality is the point |

### Structured output, always

Every LLM step returns JSON against a schema, never free prose that a later node has to
parse. In n8n: the **Structured Output Parser** attached to the LLM node. Free-text
outputs are how pipelines break silently at 3am.

### The n8n human-gate pattern

You will use this repeatedly. The canonical implementation:

- **Wait node** set to *On webhook call* — pauses the execution and gives you a resume URL.
- **n8n Form Trigger** or a Telegram/Slack message with buttons — the thing you actually
  click.
- The click hits the resume URL, the execution continues with your decision in the payload.

Learn this one node pattern properly. It is the whole architecture of both plans.

### Log everything, from day one

Both pipelines write every decision to a database (Postgres, or Airtable/NocoDB if you
want a UI for free). Not because you need it now — because in three months that table is
a dataset, and you cannot retroactively collect what you did not log.

## Suggested build order

Plan 01 carries deadline pressure that Plan 02 does not, so it leads on *engineering* time.
But Plan 02 has two week-one tasks that need no code and should not wait, because they gate
everything downstream and they compound slowly.

**Plan 01 gets the engineering time.** The job search is the priority, and a content pipeline
that eats the hours you should spend applying has inverted the goal. Plan 02's early tasks
are writing, not building, so they fit around it.

| When | Plan 01 (engineering) | Plan 02 (writing, minimal code) |
|---|---|---|
| **Weeks 1–2** | Stage 0 fact bank, Stage 1 discovery, keyword filter, daily digest | Sharpen the territory sentence. Stand up the owned home + canonical URLs + an about page with an email. |
| **Weeks 3–4** | Stages 2–3: embeddings, LLM re-rank, CV tailoring | Hand-write one pillar, start to finish, no automation |
| **Weeks 5–6** | Stages 4–6: letters, tracking, weekly report | Pipeline A stages A0, A2, A5 — angle mining, evidence packs, asset prep |
| **Week 7+** | Six-week archetype review: commit to one or two | Pipeline B (light), then A3/A4 only if drafting is genuinely the bottleneck |

Three things to notice:

- **Plan 02's first task is a sentence, not a workflow.** A content pipeline without a
  territory produces a scrapbook. Thirty minutes with a blank page beats a week of n8n.
- **Pipeline A comes before Pipeline B** — the generation path before the distribution path.
  Under a hiring-signal goal the reader arrives via the link on your CV, so quality per piece
  dominates reach. (This is the reverse of what an audience-growth goal would dictate, which
  is exactly why the goal question gets asked before the design.)
- **Automate the bottleneck, not the stage that looks most impressive to automate.** Write
  one article by hand first and find out which stage is actually slow. My bet is evidence
  gathering and figure prep, not drafting.

**The two plans feed each other more than they compete.** Plan 01's fact bank doubles as
Plan 02's proof-point store. And building Plan 01 *is* Plan 02's second article — "I
automated my job search, here is what I refused to automate and why" is stronger than most
bootcamp write-ups, because the content is the restraint. Take notes while you build; you
are producing the tooling and the material in the same hours.
