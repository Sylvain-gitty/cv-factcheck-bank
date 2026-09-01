# cv-fact-bank

Your CV, motivation letters and portfolio claims are all **renderings** of the same
underlying data — so store the data, not the documents.

This is a small, dependency-light toolchain that keeps every claim you make about yourself
in one structured store, renders CVs from it, tailors one to a specific job posting, and
refuses to let you say things you cannot defend.

```bash
pip install pyyaml
for f in profile entities facts vocab; do cp $f.example.yaml $f.yaml; done

python validate.py                    # integrity + guardrails + coverage
python render.py --pdf                # all CV variants -> out/ (HTML + PDF)
python discover.py                    # fetch jobs -> jobs/*.yaml
python rank.py --llm                  # score + re-rank -> out/digest.md
python tailor.py jobs/<slug>.yaml --explain
python letter.py jobs/<slug>.yaml     # draft -> you write the opening -> render
python package.py <slug>              # assemble; you submit
python track.py                       # the report
```

PyYAML is the only dependency. No LaTeX, no headless browser, no API key, no build step.
Output is self-contained HTML with print CSS — open it and Ctrl+P to PDF.

---

## The idea

An LLM asked to "tailor my CV to this job" from a PDF will, reliably and without warning,
invent: a job title that sounds better, a year of experience you do not have, a technology
you have never used. Not often. Often enough. And you will not catch it every time, because
you will be reading the twentieth CV that week.

Prompting against that does not work. **Structure does.** If the only permitted operation is
*select from and rephrase these records*, nothing can invent an employer, because no record
contains one. Generation becomes retrieval, and retrieval can be verified mechanically.

So:

- **`facts.yaml`** holds atomic claims. One claim per record.
- **`render.py`** selects, orders, caps and formats. **It never writes.** Every word of every
  bullet comes verbatim from the bank, and a `trace.json` proves it line by line.
- **`tailor.py`** decides *which* facts fit a job. Even with the optional LLM selector
  enabled, it returns **fact ids only** — the renderer still builds the document, so no
  generated text can reach the page.

## Two layers

An **entity** is a thing you did over a period (a job, a project, a degree). A **fact** is
one claim about it.

A CV renders entities in reverse-chronological order with selected bullets underneath;
retrieval works on individual facts. Splitting them means dates, employers and authorship
live in exactly one place and cannot drift apart — ordinary normalisation, applied to your
own history.

## Guardrails

Every one of these exists because it caught something real.

| Guardrail | Catches |
|---|---|
| `status: draft` → `confirmed` | Anything you have not personally asserted. Nothing renders until you flip it. |
| `contribution: led / joint / supported` | Team work quietly becoming solo work. **`supported` facts never render to a CV** — you do not put a teammate's work on your CV — but stay in the bank for context. |
| `scope: created / operated / contributed` | "I worked inside a good system" becoming "I built it". When set to `operated`, creator verbs are rejected. |
| `forbidden_verbs` per authorship | `led` / `owned` / `architected` appearing on team work. |
| `deny_list` | Technologies you cannot defend, checked again at render time. |
| Controlled skill vocabulary | `sklearn` / `scikit-learn` / `Scikit-Learn` drifting into three tags and silently halving your retrieval recall. |
| Derived skills section | A skills list that outruns the evidence. It is computed from the facts actually rendered, so it **cannot** contain a skill no bullet supports. |
| Numeric integrity | Any number in a rendered bullet that is not in its source fact. |

The design principle behind the two verb checks: **deny-lists, not allow-lists.** An
allow-list of permitted verbs fights you constantly and gets switched off. A narrow
deny-list of credit-claiming verbs fires rarely and only on the failure that matters.

A check that cries wolf is worse than no check.

## Finding jobs

`discover.py` fetches from the sources in `sources.yaml`, normalises them to one schema,
deduplicates, applies a free rules filter, and writes one YAML per job straight into the
shape `tailor.py` consumes.

**Every source is an official API, a published RSS feed, or an alert email you subscribed
to. Nothing is scraped.** Not because scraping is hard, but because the downside is losing
the account you are job-searching with, mid-search. `sources.yaml` records what was tested
and what each site actually permits, including the eight that permit nothing — for those,
subscribe to their alert emails and let an IMAP trigger read the mailbox. You use the
service as designed, it survives redesigns that break scrapers, and it cannot get you
banned.

The filter is string matching, no model, no API call. On a real run it took 332 postings
down to 7. Two things it taught, both the hard way:

- **A positive gate is not optional.** Dropping what you do not want is not the same as
  keeping what you do: with only negative rules, "remote" admits every job on earth, and
  the first run returned MOT Testers, Shunters and a Handyperson.
- **Match on word boundaries, never substrings.** `"ai" in title` matches ret**ai**l,
  m**ai**ntenance, c**ai**ptain and m**ai**l. That is how a Bell Captain and a Rural Mail
  Carrier reached the shortlist.

Stage 2a is tuned for recall at zero cost, not precision. Its job is to make the survivors
reviewable in thirty seconds — deciding which to pursue is yours.

### Missing data is not permission

Three bugs in the location filter, all the same shape, all found by reading one posting
that should not have been there:

1. **A list of dicts parsed to an empty string.** One feed sends
   `locations: [{city: "Lisbon", country_code: "PT"}]`; the extractor skipped dicts and
   returned `""`.
2. **A blank location skipped the check entirely.** The rule read `if allow and loc:` —
   so a job with no stated location passed unexamined. **Unknown is not the same as
   allowed**, and a filter that opts out when data is missing is a filter with a hole in
   it.
Together those two let a Volkswagen role in **Portugal** — on-site, no remote flag — rank
third on a search restricted to Germany, the EU and remote.

A third "fix" was written and then **reverted**, and the reversal is the more useful
lesson. It dropped any remote posting naming another country, on the theory that "remote —
Singapore" means remote *within* Singapore. Sometimes it does. More often it means the
company is in Singapore and hires remotely, which is perfectly workable from Berlin. The
filter was conflating *where the company sits* with *who they can hire*, and throwing away
good jobs for it.

**A genuine restriction is a phrase, not a place name** — "must be based in", "authorized
to work in the US", "only candidates located in". Those are what `drop_if_region_locked`
matches. A country name on its own disqualifies nothing.

Over-filtering costs more than it looks: a job wrongly dropped never appears, so you never
learn it was dropped. Under-filtering shows up in the digest and costs thirty seconds.
**When the two errors are that asymmetric, bias toward letting things through.**

### Company boards

Greenhouse, Lever, Ashby and Personio each serve a public JSON endpoint per company so the
employer can embed its own board. Using it is exactly what it is for. You pick the
employers, so there is no aggregator noise and postings appear the day they go live.

**Tokens are not guessable — probe them, across all four patterns.** Round one tried one
pattern per company and found 16 of 51. Round two tried all four for every candidate and
found 32 more — including DeepL, Aleph Alpha, Synthesia, deepset, Enpal and Parloa, every
one of which was in round one's "not found" list. **A 404 on one pattern says nothing.**

47 boards now fetch in about 35 seconds, so breadth is nearly free.

**Most boards will be silent on any given day, and that is fine.** On a representative run
24 employers contributed and 23 did not. A one-job board costs one request and shows you
that job the day it appears — which is the entire argument for this tier over an
aggregator. Do not prune on a quiet day.

**One board will try to eat the digest.** OpenAI's 767 postings yielded 84 survivors
against 51 from every other source combined. Each was individually valid, so no filter
change addresses it — the problem is dominance, not correctness. Hence `max_per_source`:
freshest first, then capped. A 767-posting board is not more important than a 12-posting
one.

**A flag can be true and still not mean what you want.** Ashby exposes `isRemote`, and
OpenAI sets it on San Francisco roles — remote *within the US*. The filter honours it,
because a remote job elsewhere is genuinely workable from Berlin, and second-guessing the
flag is how you start dropping good jobs again. It is Gate 1's call, not the filter's.

### Judging a source

Measure yield per source before keeping it, but **cut on structural reasons, not on one
sample.** After the location fix, Landing.jobs contributed zero — not a bad day, but
because it is Lisbon-focused, which no amount of re-running changes. The Muse went the
same way: US-centric across 20,442 pages. Sources that scored nothing for reasons that
might just be a quiet day were kept.

And treat the ranking itself sceptically. After adding six sources the new top result was
a talent-marketplace recruiting advert, not a job — dense with exactly the vocabulary in
your `match_text`. Rank measures lexical match, not whether the job is real.

## Ranking a batch

`rank.py` scores every discovered job against each role archetype's `match_text`, ranks
the batch, writes a digest, and captures your pursue/skip decisions.

**BM25 again, and the orientation matters:** the index is built over the *jobs*, and each
archetype's `match_text` is the *query*. Many documents, short query — the regime BM25 was
designed for. Querying three archetype "documents" with a job description would give
degenerate IDF over a corpus of three.

**Scores are batch-relative, and the digest says so.** BM25's IDF depends on the corpus, so
today's 14.2 and tomorrow's are not the same scale. Only the rank within a run is
meaningful. Reporting a raw score as a percentage would be a number that looks absolute and
is not.

**An argmax without a margin is a point estimate with no error bar.** The three archetypes
share most of their vocabulary, so the winner is often noise. On a real batch, margins
between the top two ranged from 76% (unambiguous) down to 21% — a coin flip. Below a 30%
margin the label is reported as ambiguous rather than asserted:

```
 1. [100] technical-pm                 Manager, Applied AI Architects
 2. [ 96]~ai-engineer?/data-scientist? Data Scientist (m/w/d) - Machine Learning
```

**Decisions are the point of Gate 1, twice over.** Ticking `p`/`s` in `decisions.txt`
filters today, and `.state/decisions.json` snapshots the scores *at decision time* — the
training set for tuning the ranker against your own judgement later. Re-deriving those
features afterwards would mean scoring against a corpus that no longer exists.

The optional `--llm` pass adds structured judgement on the top N. Its most valuable output
is `missing_requirements`, aggregated across the batch: the market telling you what to
learn next.

## Tailoring to a job

`tailor.py` takes a job as a small YAML file and produces `cv.html`, `cv.md`, `trace.json`,
`selection.json` and `checks.json`.

**Retrieval is BM25, not embeddings.** For a bank of a few dozen facts, embedding
infrastructure is over-engineering: BM25 is instant, deterministic, needs no API key or
model download, and `--explain` shows you exactly why it ranked what it ranked. Switch when
the bank passes a few hundred facts, or when you start missing facts that are semantically
right but share no words with the requirement.

**Selection is greedy set cover, not top-N.** Taking the highest-scoring N facts produces a
redundant CV: five bullets answering the requirement you match best and nothing for the
other four. Two refinements, both forced by real runs rather than designed up front:

1. **Coverage credit per fact is capped at two requirements.** Uncapped, the winner was a
   generic keyword-dense line that lexically matched four requirements at once and was the
   weakest fact in the bank. A reader does not credit one bullet with satisfying four
   separate requirements, so neither should the objective.
2. **Skill backfill.** A posting's skills are detected across the whole description, but
   retrieval only queries the requirement lines — so a skill mentioned in prose ("our stack
   is Postgres and Docker") could never pull in the fact evidencing it, and the coverage
   check would report it missing while a perfectly good fact sat unselected. Backfill now
   prefers facts covering an uncovered job skill before falling back to strength.

**The LLM is a challenger, not the default.** `--llm` runs *after* the deterministic
selector and reports the diff (`+3 / -2, 13 agreed`). Ship the cheap thing, then measure
whether the expensive thing beats it. Without an API key it writes the prompt to a file for
you to paste anywhere.

### The most useful output is the uncovered list

When requirements go uncovered, `tailor.py` names them. That is not a tool failure — it is
**your skill gap for that job, stated precisely.** Aggregated over thirty applications it is
a curriculum written by the market rather than by a syllabus.

## Motivation letters

`letter.py` builds a draft from the same facts `tailor.py` selected, so the letter and the
CV argue from one body of evidence.

**You write the opening, and the tool will not let you skip it.** The draft ships with the
first paragraph as a marked TODO block, and every gate fails while it is there — the same
mechanism as `status: draft` on facts. The thing you must do by hand is enforced by the
data, not by your memory at 11pm.

The reason is narrow. The first two sentences are the only part of a motivation letter with
a high probability of being read carefully, and they are where a human voice is most
detectable. A model writes competent, forgettable openings, and this is the one place in
the pipeline where forgettable is fatal.

| Gate | Catches |
|---|---|
| `opening_is_yours` | the TODO block still present |
| `company_specific` | no proper noun from *this* posting in the first two sentences |
| `no_dead_openers` | "I am writing to apply for…" and its relatives |
| `genericness` | lexical similarity to a previous letter above 0.75 |
| `numeric_integrity` | a number that appears in no cited fact |
| `deny_list` | a forbidden claim that survived into prose |

`--render` refuses to produce anything while a fatal gate is failing.

**Company hooks come from the posting, never from a web fetch.** Guessing a homepage from a
company name is fragile, and a wrong page produces a letter that is confidently specific
about the wrong company — the worst failure this stage has. The posting is the one document
you know is theirs.

Extracting those hooks needed three passes. Matching capitalised spans harvested
`Instead`, `Have` and `Some`, because every sentence starts with a capital — so
sentence-initial spans are skipped, since a real name recurs mid-sentence. Spans built only
from job-title words are dropped, because they restate the role rather than describe the
company. And the generic-technology exclusion list is **`vocab.yaml` itself**: "Machine
Learning" is not a company signal, and reusing the controlled vocabulary means that list
maintains itself.

Tested against a deliberately generic opening — *"I am writing to apply… 12 years of
experience delivering value"* — five gates fired at once, including the fabricated `12`
and the deny-listed phrase carrying it.

## Assembling an application

`package.py <slug>` gathers the tailored CV, the rendered letter, a submission checklist
with your screening answers filled in, and a two-date follow-up `.ics` — into one folder.

**It refuses to assemble while any gate is failing**, and it reports which: no tailored CV
yet, the letter opening still unwritten, a fatal letter check outstanding.

**There is no `--submit` flag and there will not be one.** Automated submission breaks most
platforms' terms and risks the account you are searching with; a wrong-company letter cannot
be recalled; portal logins and CAPTCHAs are not things to automate on someone's behalf; and
"why us?" is answered by a person or answered badly. What this stage removes is the twenty
minutes of assembly around the submission, not the submission.

`answers.yaml` holds the screening answers you retype on every portal. Write each once.
Two are deliberately not generated: **"why us?"** is marked `PER_JOB`, because a stored
answer to it is the generic-letter problem wearing a different hat, and **salary
expectation** is left blank, because a number invented on your behalf is a number you would
have to defend.

## Tracking outcomes

`track.py` keeps `applications.csv` — open it in a spreadsheet and edit the outcome columns
by hand. `--add` snapshots a job's score at the moment you apply, because re-deriving it
later would score against a corpus that no longer exists.

Your job search is a product with one metric and a four-stage funnel. The report exists to
stop you drawing conclusions the data cannot support.

**Small n is not a rate.** Below 25 resolved applications the report refuses to print a
percentage, and shows you the interval instead. At 7/19 that interval is **19%–59%** — it
spans nearly every value it could take, which is exactly the point. A number there would
look like a finding and be an anecdote.

**No reply is not a rejection.** It is not-yet-observed. Applications inside a 21-day
window are held out as censored rather than counted as failures — otherwise every rate is
biased downwards, worst precisely when you are most active.

**Point estimates get compared, not just listed.** On simulated data seeded with a real
effect (boards replying at 30%, aggregators at 8%), the report showed 50% against 12% — and
still said:

```
greenhouse-celonis looks better than arbeitnow, but the intervals
overlap — not yet a difference you can act on
```

Two numbers can look decisive while their intervals overlap completely. Saying so is the
difference between a report and a rationalisation, and it is the same instinct as declining
to claim an F2 gain whose interval crossed zero — turned on your own job search.

It also warns when you have run several CV variants across too few applications to
attribute anything: hold one fixed for 25 before changing it.

## Confirming facts

```bash
python confirm.py            # writes out/worksheet.md + confirm.txt
python confirm.py --apply    # flips every ticked fact to confirmed
```

Ticking a box asserts four things: it is true and at the right scope, the verb matches what
you did, **you can defend it under follow-up**, and the numbers are right. The third is the
one people skip, and it is the one that costs you — a fact you cannot survive a follow-up on
turns a good interview into a bad one at the worst moment.

The worksheet shows each bullet exactly as it will render, its evidence, every structured
metric, and a list of things worth a second look: team work where the bullet must not claim
sole credit, `operated` scope, missing outcomes, recall-only evidence, and every number
extracted for verification.

## Page length

Variants declare a `page_target` and the run warns when you exceed it. The estimator's
constants were **measured from a real browser render**, not guessed — an earlier version
counted bullet characters only and reported 1.1 pages where the truth was 1.76, because it
ignored the profile paragraph, the skills grid and the education block.

If you change the CSS, re-calibrate. Open a rendered variant and run:

```js
(() => { const w = document.body.getBoundingClientRect().width;
         const page = (297 - 26) * (w / 190);
         return document.documentElement.scrollHeight / page; })()
```

A length check that lies is worse than none: it tells you a two-page CV fits on one.

**The rule that matters is not "one page."** It is: never spill a little onto a second sheet.
Land at 1.8–2.0, or cut to a genuine single page. 1.4 is the bad number.

## Things only a screenshot caught

Three defects passed every validator, every character count and every traceability check,
and were invisible until the rendered page was actually looked at:

1. **The CV rendered dark-on-dark.** The CSS set a text colour but no background, so a
   browser in dark mode painted the page dark and the near-black text became unreadable. A
   CV is a print document; it is always light, whatever theme the reader is in.
2. **Entity headers wrapped and pushed the dates out of alignment**, because name,
   organisation and role all ran on one line.
3. **An entity heading rendered with no bullets under it** — `by_entity` is a `defaultdict`,
   so the per-entity cap check *created* an empty entry for entities whose facts were all
   dropped by the total cap.

**Look at the artefact.**

## Privacy

`.gitignore` excludes `profile.yaml`, `entities.yaml`, `facts.yaml`, `vocab.yaml`,
`confirm.txt`, `out/` and real job files. Those hold your phone number, your address, your full employment history
and your rendered CVs.

**Do not remove those lines.** If you need to share a bank, share the `.example.yaml` files.

## Files

```
profile.yaml        identity, role archetypes, deny-list, verb guardrails
entities.yaml       jobs, projects, degrees: dates and authorship live here
facts.yaml          atomic claims, each attached to an entity
vocab.yaml          controlled vocabulary for skill tags
render_config.yaml  CV variants: archetype, section order, page budget, language
sources.yaml        where jobs come from, and what each site permits
discover.py         fetch, normalise, deduplicate, filter -> jobs/*.yaml
rank.py             score against archetypes, rank, digest, capture decisions
validate.py         integrity, guardrails, coverage report
render.py           bank -> HTML / Markdown / traceability
tailor.py           tailor to one job posting, with checks
letter.py           motivation letter: evidence, draft, gates, render
package.py          assemble a ready-to-send application; refuses to send it
answers.yaml        screening-question answer bank
track.py            application log, funnel, response rates with intervals
confirm.py          the draft -> confirmed human gate
```

MIT licensed.
