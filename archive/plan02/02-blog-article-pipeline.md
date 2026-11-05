# Plan 02 — Blog & Content Pipeline

**Primary goal: hiring signal.** Articles that make a hiring manager think "I want to talk
to this person," each anchored to a repo they can open.

**Secondary, woven in: a consulting brand.** The same articles quietly build the asset base
you would need to sell services later — without announcing it while you are job hunting.
The weaving is the interesting design problem, and most of this plan is about doing it
without compromising the primary goal.

**n8n:** self-hosted locally, so it can read this folder directly.

---

## Two audiences, one body of work

Write down what each actually wants before designing anything. They are closer than they
look, and the places they diverge are the places that need a decision.

| | **Hiring manager** | **Consulting buyer** |
|---|---|---|
| Core question | "Can this person do the work and think well?" | "Can this person solve *my* problem?" |
| Reads for | Depth, judgment, honesty about failure, how you decide | Outcomes, business framing, "they've seen this before" |
| Finds you via | Your CV link, LinkedIn, a Google of your name | Search for a problem, referral, LinkedIn |
| Junior framing | Fine, even attractive — growth is the point | Actively harmful — nobody buys "I'm learning" |
| Time horizon | Now, weeks | Later, months to years |

### Where they overlap — which is most of it

Both want **evidence of judgment applied to a real problem, with the reasoning shown.** That
is one artifact, not two. The projects, the numbers, the decision logs, the honesty about
what did not work — all of it serves both audiences unchanged.

So the split is not in the *content*. It is in the *framing*, and it is narrow.

### Where they conflict — and the rule that dissolves it

The conflict is self-framing. "What I learned building X" reads well to a hiring manager and
badly to a buyer. "How I help companies do X" reads fine to a buyer and, from someone six
months out of a bootcamp, reads as overreach to a hiring manager.

**The rule that serves both: write about the problem, not about yourself.**

> Not "What I learned about imbalanced classification in my bootcamp capstone."
> Not "How I help R&D teams screen literature."
> But **"Why F1 is the wrong metric for literature screening — and what we used instead."**

Problem-centric writing is audience-agnostic. The hiring manager sees someone who thinks
clearly about a hard problem. The buyer sees someone who understands their problem. Neither
is being sold to, and you never have to choose a frame. Every self-centric title forces the
choice; every problem-centric title avoids it.

This one rule does more work than any pipeline stage below. If you take nothing else from
this plan, take this.

---

## The timing risk, stated plainly

**Loud consulting positioning during an active job search can cost you interviews.** A
hiring manager who sees "Freelance ML Consultant — available for projects" in your LinkedIn
headline may read flight risk, or divided attention, or padding. That is not paranoia; it is
a common and quiet rejection reason.

**Mitigation — build the asset, keep the offer latent:**

| Build now (serves both, no risk) | Defer until you have a role or decide to go independent |
|---|---|
| Problem-centric articles anchored to repos | "Available for consulting" in your LinkedIn headline |
| A recognisable problem territory | A services/rates page |
| An email list, quietly collected | Outbound pitching, lead magnets, case-study-with-CTA format |
| A contact path on your own site | Anything that reads as actively selling |

The consulting offer is a **headline change plus one page** — a weekend of work, whenever
you want it. The credibility behind it takes two years. So build the two-year thing now and
flip the switch later. That is what "woven in" should mean operationally, and it costs the
job search nothing.

---

## Your consulting territory — WITHDRAWN 2026-08-28

**This section was wrong.** It rested on `TIRI` *plus* `academic_research_agent` as a matched
pair: the modelling half and the product half of one problem. The Academic Agent belongs to
**Warren Fauvel** — 378 commits, proprietary licence, all rights reserved — and was shared
with you as the data source for TIRI. Half the foundation was never yours, and TIRI itself
is roughly a quarter yours by commit count.

A consulting territory has to stand on work you own and can show. What is actually there:
TIRI as a co-author, the air pollution project as one of three, your MSc research, and the
automation tooling you are building now. That may still amount to a position, but it is a
different one and it has to be built from what is really there.

`profile.yaml` marks this territory `status: needs-rethink`. **Do not build content on it
until it is re-grounded.**

**The wider lesson for this pipeline:** the allow-list in Stage A0 exists precisely to stop
this, and it still would have — `sources.yaml` requires an `authorship` field per repo, and
filling that in honestly would have caught it. What failed was upstream of the pipeline: I
read a README and inferred ownership from a directory's location. **Authorship comes from
`git log` and the LICENSE, never from a README.**


## What changed from the audience-growth version

Three consequences of the new priority, including one reversal of a call I made explicitly
last time.

**1. Cadence drops, and the depletion problem largely goes away.** Audience growth needed
~50 pieces a year. Hiring signal over a 3–6 month search needs maybe 10–13 good ones, at
**one per two weeks**. You have five pillar-grade projects plus a serial that generates more
as you build. That is enough runway. The four-tier content pyramid was load-bearing for a
volume goal and is now over-engineering — it collapses to pillars, a serial, and light
derivatives.

**2. Build Pipeline A before Pipeline B — reversing what I said last time.** Under audience
growth, reach was the bottleneck, so distribution deserved automation first. Under hiring
signal, the hiring manager arrives via the link on your CV; reach is largely solved by the
application itself. **Quality per piece now dominates.** So build the pillar path first, and
keep distribution light.

That reversal is the point of asking the goal question before designing. The stages barely
moved; the build order inverted completely.

**3. SEO becomes the consulting long game, not an urgent task.** It does almost nothing for
the job search — nobody googles "recall-first literature screening" and hires you. It does
almost everything for inbound consulting in two years. So do the cheap, permanent parts now
(good titles, canonical URLs, alt text, internal links) and skip keyword research entirely
for now.

---

## Content audit

### Pillar material

| Project | The angle | Hiring | Consulting |
|---|---|---|---|
| **TIRI** | README states the thesis outright: *"the obvious approach was measurably the wrong one."* `CONTEXT.md` holds four more — LOGO vs. within-silo validation, recall-first F2, why no pooled model can ship, the labelled/borderline/never-reviewed distinction. | Strong — depth + honesty | Strong — core territory |
| **DS-airpollutionproject** | PM2.5 from satellite data where no ground sensors exist. Team of three, Zindi leaderboard, three models compared. | Strong — collaboration + applied ML | Weak — off-territory |
| **The n8n pipelines** | Your serial. Build-in-public, starts now, runs for months. | Strong — judgment over tooling | Medium — shows systems thinking |

**On the serial:** building Plan 01 generates content as a by-product. "I automated my job
search — here is what I refused to automate and why" is stronger than most bootcamp
write-ups, because the content is the restraint rather than the tooling. Take notes while
you build; you are producing the tooling and the material in the same hours.

### Supporting evidence, not subjects

The ~20 `DS-*` tutorial repos. Curriculum you completed, not work you did. Excellent *inside*
a pillar — "I'd done the textbook RAG workshop, which is exactly why the failure in TIRI
surprised me" — and weak as subjects, because a tutorial write-up signals "I follow
instructions."

### Must never enter the pipeline

**`Expected-Throwing-Value` is not your work.** The README names Braden Eberhard, Jacob
Miller and Nate Sandholz. You cloned it to study. Same for `developer-roadmap`, `public-apis`,
and the neuefische workshop repos.

A folder-scanning pipeline cannot tell these apart and will cheerfully draft "How I built an
ML framework for Ultimate Frisbee." Publishing that is career-ending rather than
embarrassing. **The pipeline takes an explicit allow-list, never a folder scan.**

This matters doubly now: a fabricated or misattributed credential is survivable-ish in a job
hunt and fatal in consulting, where your name *is* the product.

---

## Pipeline A — the pillar path (the main build)

**Status: built.** `fact-bank/article.py` + `fact-bank/content-sources.yaml`.

    python article.py --list
    python article.py --evidence tiri
    python article.py --new tiri "<thesis>"
    python article.py --check <slug>
    python article.py --render <slug>

Three things the build made concrete:

- **The allow-list carries `authorship`, `collaborators` and `share`**, and they travel
  into the checks. TIRI is recorded as co-authored at ~27% of commits, so a draft using
  first-person singular fails a gate rather than merely looking wrong.
- **The evidence pack is code-only.** TIRI's has 366 values, 24 from confirmed facts and
  the rest from declared repo files, each with its source. `numeric_integrity` then rejects
  any figure in a draft that is not in it.
- **Intro and conclusion ship as TODO blocks** and gates fail while they are present, the
  same mechanism as the letter opening and `status: draft`.

Verified against a deliberately bad draft — *"How I built a ranking model… 0.947 ROC-AUC…
37% improvement… 9,412 papers"* — four gates fired simultaneously: self-centric title, all
three fabricated numbers, four banned phrases, and seven first-person uses on joint work.

**Pipeline B is not built.** See the note at the end of this plan.

```
Stage A0  Allow-list + angle mining
  GATE 1  you pick the claim
Stage A1  Brief: thesis + outline + dual-audience check
  GATE 2  you approve the thesis
Stage A2  Evidence pack (deterministic, no LLM)
Stage A3  Section-by-section draft, grounded
Stage A4  Three critics -> comments
  GATE 3  you write intro + conclusion
Stage A5  Assets + frontmatter + permanent-SEO basics
  GATE 4  you publish
```

### Stage A0 — Allow-list and angle mining

`sources.yaml` is the provenance gate:

```yaml
repos:
  - name: TIRI
    url: github.com/Sylvain-gitty/TIRI---The-Data-science-project
    authorship: co-authored          # two-person capstone - say "we"
    collaborators: ["<partner name>"]
    lens: [ds]
    territory: evidence-triage       # counts toward the consulting position
  # academic_research_agent is DELIBERATELY ABSENT: Warren Fauvel's repo, proprietary
  # licence, all rights reserved. Never publishable. Same for data_sci_virtual_coaches.
  # The allow-list is exactly the mechanism that keeps them out -- use it.
  - name: DS-airpollutionproject
    authorship: team                 # Andrea, Ghada, Sylvain - credit them
    lens: [ds]
    territory: null                  # hiring signal only, and that is fine
```

`authorship` is not bureaucracy — two of your three strongest projects are team work, and
"we" versus "I" is the line between an honest article and quiet overclaiming. `territory`
tracks which pieces compound into the consulting position, so you can see the balance
without letting it distort what you write.

**Angle mining.** n8n pulls each repo's README, decision docs, commit messages and notebook
markdown, then asks a strong model for **candidate claims, not article ideas**:

> For each repo, list non-obvious claims the author is in a position to make. A claim is
> non-obvious if a competent practitioner might believe the opposite. Give the claim, the
> supporting evidence in the repo, and who would disagree.

"Write an article about TIRI" produces a summary. "What did TIRI prove that someone might
reasonably doubt?" produces an article.

**GATE 1 — you pick.** The model mines candidates; it cannot know which claim you can defend
in an interview, which is too close to confidential work, or which you find interesting
enough to write 1,500 words about. Rule: if you cannot state the claim in one arguable
sentence, send it back.

### Stage A1 — Brief

Thesis (one arguable sentence), reader, 5–7 section outline, evidence map, and **gaps** —
what the article needs that the repo does not contain. That last field often reveals you
need to re-run an experiment or plot a new chart; better to learn it now than at draft stage.

**Plus the dual-audience check**, which is the one genuinely new step in this version:

- Is the title problem-centric rather than self-centric?
- Would a hiring manager finish it and think "competent"?
- Would someone with this exact problem finish it and think "they understand my situation"?
- Does it avoid selling? (Any sentence that reads as a pitch gets cut. Now especially.)

If it fails the third check, that is fine — `DS-airpollutionproject` will. Not every piece
needs to serve both. But you should know which one you are writing.

**GATE 2 — approve thesis and outline.** Ten minutes, saves an hour. A draft on a mushy
thesis cannot be edited into a good article; it has to be rewritten. Fix it while it is six
lines of text.

### Stage A2 — Evidence pack (deterministic, no LLM)

**The credibility firewall.** Code — not a model — extracts real values from real files:
metrics from results CSVs, numbers from executed notebook outputs, figure paths from
`reports/`, quotes from decision docs with file and line.

```json
{
  "claim_slot": "f2_gain_over_baseline",
  "value": 0.71,
  "source_file": "notebooks/main/03_ensemble.ipynb",
  "cell": 42,
  "extracted_at": "2026-08-26"
}
```

A model summarising a notebook will occasionally produce a plausible number that is not in
it. A plausible-but-wrong F2 score is invisible to your reader and glaring to the one person
you wanted to impress. **The model may only reference values present in the pack**, and A3
enforces it mechanically.

### Stage A3 — Drafting

Section by section, never one shot. Each call gets the thesis, this section's outline line,
the relevant evidence slice, the previous section's closing paragraph, and the voice pack.

**The voice pack.** Your READMEs have a real style — direct, comfortable saying what did not
work, allergic to marketing language. TIRI's *"The interesting part is not the accuracy
number"* is a good specimen. Feed 3–5 such excerpts, plus a ban-list: "delve", "in today's
fast-paced world", "leverage" as a verb, "game-changer", "unlock", "it's important to note",
rhetorical-question openers, three-adjective lists.

**Numeric-integrity check:** extract every numeral from the draft, verify each against the
evidence pack, flag unmatched ones for you rather than deleting them silently. Worth more
than any amount of "please do not hallucinate" in a prompt.

### Stage A4 — Three critics

Comments, not rewrites — a critic that rewrites launders its own errors into the text.

- **DS critic:** are the claims defensible from the evidence pack? Causal language on
  correlational evidence? A metric without its baseline? A validation scheme that does not
  support the conclusion?
- **PM critic:** is the thesis clear in the first hundred words? Does it respect what the
  reader already knows? What is the one takeaway, and does a skimmer get it?
- **Editor:** ban-list, passive voice, generic openers, paragraphs doing two jobs, length.
  Plus: flag any sentence that reads as self-promotion or as a pitch.

The DS critic is the one that saves you. Publishing an overreaching claim is far easier than
publishing a typo, and far more costly for both audiences.

**GATE 3 — you write the intro and the conclusion.** Every time. Those are the two sections
people actually read and where voice is most visible. The middle of a well-grounded article
can be assembled; an opening cannot, because it has to convey a specific person having a
specific thought. Read the draft aloud once; cut anything you would not say.

### Stage A5 — Assets and the permanent basics

Do the cheap things that never expire, skip the rest for now.

- **Figures.** Reuse the repo's real plots — `reports/eda_quickstart_*.png`, `F2 per stage
  per use case.png`, `REsidual distribution.png`, `train-validate-holdout-EM.png`. Regenerate
  at web resolution in one consistent style so the set reads as a series. Alt text on every
  one: accessibility first, search second.
- **Titles:** generate 8 candidates, you pick. Problem-centric, per the rule above. High
  leverage and cheap to iterate.
- **Canonical URL:** set once, every cross-post points at the original. Costs nothing now,
  saves your search ranking later.
- **Internal linking:** every pillar links to two others. This is what makes a body of work
  compound rather than scatter — and it is the mechanism by which five articles read as a
  territory rather than five posts.
- **A quiet contact path:** an about page with an email address. Not a services page. This
  is the entire consulting funnel for now, and it is enough.

**Skip for now:** keyword research, search-intent optimisation, lead magnets. All of it
serves the consulting goal on a two-year horizon and none of it serves the job search.

**GATE 4 — you publish.** Outward-facing and effectively irreversible: a corrected article
still lives in caches, feeds and someone's screenshot. Also the last realistic moment to
catch a claim that overstates a teammate's contribution.

---

## Pipeline B — derivatives and distribution (NOT BUILT)

Deliberately deferred rather than forgotten. Atomising a published piece into LinkedIn
posts and a newsletter is the safest thing in either plan to automate, precisely because it
only ever compresses text that already cleared Pipeline A's gates — but it is worth nothing
until a first article exists to compress. Build it when there is one.

The design below stands.

Smaller than in the audience-growth version, because reach is no longer the bottleneck. Keep
the safety property, drop the volume.

**B1 — Atomise.** Split the approved article into 4–6 standalone claims. **Extraction from
approved text only — never a new claim.** That constraint is what lets B run fast and
unsupervised.

**B2 — Reformat per platform.**

| Platform | Format | Priority now |
|---|---|---|
| **Your site** | Canonical full article | Essential — this is the link on your CV |
| **LinkedIn** | Hook, 3–5 short lines, one concrete number, link | High — where hiring managers actually look you up |
| **dev.to / Hashnode** | Full cross-post, canonical set | Medium — cheap technical discovery |
| **Newsletter** | Digest with a short personal opening | Low effort, plant it now — the owned list is the consulting asset that no algorithm can take from you |
| **X / Mastodon / Bluesky** | Optional | Only if you will genuinely be present there |

**B3 — Schedule.** Space derivatives over the two weeks between pillars. Consistency beats
bursts.

**GATE 5 — weekly batch approval.** One message, Monday, the week's queued posts. Ten
minutes. Deliberately lighter than Gates 1–4 because the content already cleared them —
re-litigating each post is waste. Right-sizing a gate to its actual risk is the skill; an
over-gated process gets abandoned, and an abandoned gate is worse than a light one.

**B4 — Engagement: human, always.** Replying to comments is where both a reputation and a
referral network get built, and automated replies are detectable. In a professional niche
this small, being caught bot-replying is unrecoverable — people talk. n8n's job is to notify
you and collect comments in one place. Then you type, personally.

---

## Measurement

**Primary — hiring:**
- Did an article come up in an interview or a recruiter message? Log it. This is the only
  metric that directly serves the primary goal, and almost nobody tracks it.
- Referral traffic from your site to your GitHub repos (GitHub traffic API).
- Inbound messages mentioning a specific article.

**Secondary — the consulting asset, leading indicators only:**
- Newsletter subscribers (slow, and that is fine — you are planting).
- Search impressions on territory articles, checked quarterly, not weekly.
- Any inbound that describes a *problem* rather than a job.

**Read it like a data scientist:**

1. **n is tiny.** Ten articles is not a dataset. Treat everything here as directional.
2. **The consulting signal is lagged by months to years.** Judging a territory article on
   week-one traffic measures the wrong window entirely, and it is the most common reason
   people abandon this kind of asset at month two. Check quarterly, not weekly.
3. **Beware attribution.** If you get an interview after publishing, the article may or may
   not have caused it. Ask in the interview — people will tell you.

---

## Risk register

| Risk | Mitigation |
|---|---|
| Consulting positioning costs you interviews | Latent positioning: build assets, defer the offer. No "available for consulting" while searching. |
| Publishing another's work as yours | Explicit allow-list, `authorship` field, Gate 4 |
| Under-crediting teammates | `collaborators` inherited into every prompt; "we" by default on team projects |
| Fabricated metric | Deterministic evidence pack + numeric-integrity check + DS critic |
| Reads as AI-generated | Voice pack, ban-list, Critic 3, and Gate 3 — you write the parts that get read |
| Reads as a sales pitch | Problem-centric title rule + editor critic flags pitch sentences |
| Overclaiming seniority | Junior framing is an asset for hiring; just never claim outcomes you did not own |
| Content competing with the job search for time | Hard cap: one pillar per two weeks. The job search wins ties. |
| Publishing someone else's proprietary work | The allow-list, plus `git log` and LICENSE checked before any repo enters it |

---

## Build order

**Weeks 1–2 — writing, no code.**
1. Sharpen the territory sentence with me (30 minutes, highest leverage in the plan).
2. Stand up the owned home: a simple site, canonical URL scheme, an about page with an
   email address.
3. Hand-write one pillar end to end, no automation. TIRI's recall-first finding is the
   obvious first — the README already hands you the thesis.

You need one hand-made article before automating, for the same reason you build the baseline
before the ensemble: no comparison point otherwise, and no felt sense of which parts were
slow. My prediction is that evidence-gathering (A2) and figure prep (A5) are the slow parts,
not the writing — in which case build those two and leave drafting manual for a while.

**Weeks 3–6 — Pipeline A stages A0, A2, A5.** Angle mining, evidence packs, asset prep. Keep
drafting manual longer than feels necessary; it is where automation quality degrades most
visibly and where your voice is the actual product.

**Weeks 7+ — Pipeline B, then A3/A4** if drafting is genuinely the bottleneck by then. It
may not be.

Note this runs *behind* Plan 01 for engineering time. The job search is the priority; a
content pipeline that eats the hours you should spend applying has inverted the goal.

### First four pieces

1. **TIRI — "Why F1 is the wrong metric for literature screening."** Problem-centric,
   technically deep, and squarely in your territory. Serves both audiences unchanged.
2. **Serial — "What I refused to automate in my job search."** From Plan 01. Demonstrates
   judgment rather than tool proficiency, which is the rarer and more valuable signal.
3. **Air pollution — "GroupKFold, and the leakage you only find by looking for it."**
   Your cleanest concrete leakage story, and one you can publish freely with your two
   teammates credited.
4. **Craft — "I let an AI seed my CV from my own repos, and it invented a job I never had."**
   The provenance failure documented in `fact-bank/README.md`, written up honestly. It is a
   genuinely useful warning for anyone building the same kind of tooling, and it
   demonstrates the judgement rather than describing it.

**Note what changed here.** The original list had two Academic Agent pieces on it. Removing
them is not a small edit: it removes most of the product-management material, which was the
distinctive half of the positioning. Getting the sequence right now matters less than being
honest about what you have to sequence.
